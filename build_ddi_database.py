#!/usr/bin/env python3
"""
Free-source DDI pipeline for AbsorbAI.
Sources:
  1. OpenFDA drug labels  — drug_interactions_text NLP parsing
  2. RxNorm (NLM)         — structured DDI pairs via RxCUI
  3. OpenFDA FAERS        — co-occurrence reaction signal

Output: core/drugdb/ddi_database.py  (DRUG_INTERACTIONS, FOOD_DRUG_INTERACTIONS)
"""

import json
import re
import time
import requests
from collections import defaultdict

# ── Paths
LABELS_PATH   = "openfda_labels.json"
ADVERSE_PATH  = "openfda_adverse_reactions.json"
OUT_PATH      = "core/drugdb/ddi_database.py"

# ── Drug name → canonical key map (matches drug_data.py keys)
with open(LABELS_PATH) as f:
    LABELS = json.load(f)

ALL_DRUGS = list(LABELS.keys())

# ────────────────────────────────────────────
# LAYER 1: Parse OpenFDA drug_interactions text
# Extract drug names + severity keywords via NLP
# ────────────────────────────────────────────

SEVERITY_PATTERNS = [
    (r'\bcontraindicated\b',          'high',   0.95),
    (r'\bavoid\s+concomitant\b',       'high',   0.90),
    (r'\bdo\s+not\s+use\b',           'high',   0.90),
    (r'\bserious\s+bleeding\b',        'high',   0.88),
    (r'\bsignificantly\s+increas',     'high',   0.85),
    (r'\bsignificantly\s+decreas',     'high',   0.85),
    (r'\bincreas\w*\s+risk\s+of\b',    'high',   0.82),
    (r'\bpotentiat',                   'moderate', 0.75),
    (r'\bmonitor\s+closely\b',         'moderate', 0.72),
    (r'\buse\s+with\s+caution\b',      'moderate', 0.70),
    (r'\bmonitor\b',                   'moderate', 0.65),
    (r'\bcaution\b',                   'moderate', 0.60),
    (r'\binteract',                    'low',    0.50),
    (r'\bmay\s+affect\b',              'low',    0.45),
]

# Known drug names to scan for in text (subset — high-value interactors)
DRUG_NAME_TOKENS = {
    'warfarin': ['warfarin','coumadin'],
    'aspirin':  ['aspirin','acetylsalicylic'],
    'clopidogrel': ['clopidogrel','plavix'],
    'heparin':  ['heparin'],
    'metformin': ['metformin'],
    'insulin_glargine': ['insulin'],
    'atorvastatin': ['atorvastatin','statin'],
    'simvastatin': ['simvastatin'],
    'rosuvastatin': ['rosuvastatin'],
    'clarithromycin': ['clarithromycin'],
    'fluconazole': ['fluconazole'],
    'ciprofloxacin': ['ciprofloxacin','fluoroquinolone'],
    'amiodarone': ['amiodarone'],
    'digoxin': ['digoxin'],
    'phenytoin': ['phenytoin'],
    'carbamazepine': ['carbamazepine'],
    'valproate': ['valproate','valproic'],
    'lithium': ['lithium'],
    'methotrexate': ['methotrexate'],
    'cyclosporine': ['cyclosporine','ciclosporin'],
    'rifampin': ['rifampin','rifampicin'],
    'ketoconazole': ['ketoconazole'],
    'itraconazole': ['itraconazole'],
    'verapamil': ['verapamil'],
    'diltiazem': ['diltiazem'],
    'omeprazole': ['omeprazole','proton pump','ppi'],
    'ibuprofen': ['ibuprofen','nsaid','non-steroidal'],
    'naproxen': ['naproxen'],
    'celecoxib': ['celecoxib'],
    'morphine': ['morphine','opioid'],
    'tramadol': ['tramadol'],
    'diazepam': ['diazepam','benzodiazepine'],
    'alprazolam': ['alprazolam'],
    'sertraline': ['sertraline','ssri','serotonin reuptake'],
    'fluoxetine': ['fluoxetine'],
    'venlafaxine': ['venlafaxine','snri'],
    'haloperidol': ['haloperidol','antipsychotic'],
    'quetiapine': ['quetiapine'],
    'clozapine': ['clozapine'],
    'levodopa_carbidopa': ['levodopa','carbidopa'],
    'amlodipine': ['amlodipine','calcium channel'],
    'lisinopril': ['lisinopril','ace inhibitor','acei'],
    'losartan': ['losartan','arb','angiotensin receptor'],
    'furosemide': ['furosemide','loop diuretic','diuretic'],
    'spironolactone': ['spironolactone','potassium-sparing'],
    'hydrochlorothiazide': ['hydrochlorothiazide','thiazide'],
    'vancomycin': ['vancomycin'],
    'metronidazole': ['metronidazole'],
    'levothyroxine': ['levothyroxine','thyroid'],
    'theophylline': ['theophylline'],
    'enoxaparin': ['enoxaparin','lmwh','low molecular weight heparin'],
    'azathioprine': ['azathioprine'],
    'imatinib': ['imatinib','tyrosine kinase'],
    'tamoxifen': ['tamoxifen'],
}

# Food interactors
FOOD_TOKENS = {
    'grapefruit': ['grapefruit'],
    'dairy':      ['calcium','dairy','milk'],
    'vitamin_k':  ['vitamin k','leafy green','spinach','kale'],
    'alcohol':    ['alcohol','ethanol'],
    'high_fat_meal': ['fatty meal','high.fat','fat meal'],
    'iron':       ['iron','ferrous'],
    'caffeine':   ['caffeine','coffee'],
    'tyramine':   ['tyramine','aged cheese','fermented'],
    'high_protein': ['high.protein','protein.rich'],
    'low_sodium': ['low.sodium','sodium.restrict'],
    'potassium':  ['potassium.rich','banana'],
    'antacid':    ['antacid','magnesium','aluminum hydroxide'],
}

FOOD_MECHANISMS = {
    'grapefruit':     'CYP3A4 inhibition by furanocoumarins',
    'dairy':          'Chelation complex formation (Ca2+)',
    'vitamin_k':      'Competitive antagonism of anticoagulant effect',
    'alcohol':        'CYP induction/inhibition + CNS/hepatic effect',
    'high_fat_meal':  'Altered GI motility and absorption rate',
    'iron':           'Chelation complex formation (Fe2+/Fe3+)',
    'caffeine':       'CYP1A2 substrate competition / CNS effect',
    'tyramine':       'MAO inhibition → hypertensive crisis risk',
    'high_protein':   'Amino acid competition at BBB transport',
    'low_sodium':     'Altered renal clearance via Na+ balance',
    'potassium':      'Electrolyte interaction',
    'antacid':        'pH-dependent absorption reduction',
}

def parse_fda_ddi_text(drug_name: str, text: str) -> list:
    """Extract structured DDI rows from FDA label drug_interactions_text."""
    if not text or len(text) < 50:
        return []

    text_lower = text.lower()
    rows = []
    seen = set()

    for other_drug, tokens in DRUG_NAME_TOKENS.items():
        if other_drug == drug_name:
            continue

        # Find if any token for this drug appears in text
        match_pos = -1
        for token in tokens:
            idx = text_lower.find(token)
            if idx != -1:
                match_pos = idx
                break

        if match_pos == -1:
            continue

        # Get context window around mention
        ctx_start = max(0, match_pos - 200)
        ctx_end   = min(len(text_lower), match_pos + 300)
        context   = text_lower[ctx_start:ctx_end]

        # Score severity from context
        sev = 'low'
        conf = 0.40
        for pattern, severity, confidence in SEVERITY_PATTERNS:
            if re.search(pattern, context):
                sev = severity
                conf = confidence
                break

        # Deduplicate pair
        pair_key = tuple(sorted([drug_name, other_drug]))
        if pair_key in seen:
            continue
        seen.add(pair_key)

        # Extract mechanism hint
        mech = 'See FDA label'
        cyp_match = re.search(r'cyp\s*(\w+)', context)
        if cyp_match:
            mech = f'CYP{cyp_match.group(1).upper()} interaction'
        elif re.search(r'bleed|anticoagul|inr', context):
            mech = 'Increased bleeding risk'
        elif re.search(r'serotonin', context):
            mech = 'Serotonin syndrome risk'
        elif re.search(r'qt\s*prolong|torsade', context):
            mech = 'QT prolongation'
        elif re.search(r'nephrotox|renal', context):
            mech = 'Nephrotoxicity potentiation'
        elif re.search(r'hepatotox|liver', context):
            mech = 'Hepatotoxicity potentiation'
        elif re.search(r'p-gp|p-glycoprotein', context):
            mech = 'P-glycoprotein interaction'
        elif re.search(r'absorpt|bioavail', context):
            mech = 'Absorption interference'

        rows.append({
            'drug_a':    drug_name,
            'drug_b':    other_drug,
            'severity':  sev,
            'confidence': conf,
            'mechanism': mech,
            'source':    'OpenFDA label',
            'auc_ratio': None,
            'onset_hours': None,
        })

    return rows

def parse_fda_food_interactions(drug_name: str, text: str, warnings: str = '') -> list:
    """Extract food-drug interactions from FDA label text."""
    combined = (text + ' ' + warnings).lower()
    rows = []

    for food, tokens in FOOD_TOKENS.items():
        for token in tokens:
            if re.search(token, combined):
                sev = 'moderate'
                conf = 0.65
                ctx_match = re.search(f'.{{0,150}}{re.escape(token)}.{{0,150}}', combined)
                ctx = ctx_match.group(0) if ctx_match else ''
                for pattern, severity, confidence in SEVERITY_PATTERNS:
                    if re.search(pattern, ctx):
                        sev = severity
                        conf = confidence
                        break

                rows.append({
                    'drug':      drug_name,
                    'food':      food,
                    'severity':  sev,
                    'confidence': conf,
                    'mechanism': FOOD_MECHANISMS.get(food, 'See FDA label'),
                    'source':    'OpenFDA label',
                    'separation_hrs': 2 if food in ('dairy','iron','antacid') else None,
                })
                break  # one match per food sufficient

    return rows


# ────────────────────────────────────────────
# LAYER 2: RxNorm structured DDI pairs
# ────────────────────────────────────────────

RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"

SEVERITY_MAP_RXNORM = {
    'high-severity':    ('high',    0.92),
    'moderate-severity':('moderate',0.80),
    'low-severity':     ('low',     0.60),
    'N/A':              ('low',     0.50),
}

def get_rxcui_for_drug(drug_name: str) -> str | None:
    """Get base RxCUI from openfda_labels.json (already fetched)."""
    entry = LABELS.get(drug_name, {})
    rxcuis = entry.get('openfda_rxcui') or []
    if rxcuis:
        return rxcuis[0]
    return None

def fetch_rxnorm_interactions(rxcui: str, drug_name: str) -> list:
    """Fetch structured DDI pairs from RxNorm API."""
    try:
        url = f"{RXNORM_BASE}/interaction/interaction.json?rxcui={rxcui}"
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    rows = []
    seen = set()

    for group in data.get('interactionTypeGroup', []):
        for itype in group.get('interactionType', []):
            for pair in itype.get('interactionPair', []):
                sev_raw  = pair.get('severity', 'N/A')
                sev, conf = SEVERITY_MAP_RXNORM.get(sev_raw, ('low', 0.50))
                desc      = pair.get('description', '')

                concepts = pair.get('interactionConcept', [])
                names = [c.get('minConceptItem', {}).get('name', '').lower()
                         for c in concepts]

                # Map RxNorm name to our drug key
                other_name = None
                for n in names:
                    if n and n not in drug_name.replace('_',' '):
                        # Try to find matching key
                        for key in ALL_DRUGS:
                            if key.replace('_',' ') in n or n in key.replace('_',' '):
                                other_name = key
                                break
                        if not other_name:
                            other_name = n.split()[0]  # use first word as fallback
                        break

                if not other_name:
                    continue

                pair_key = tuple(sorted([drug_name, str(other_name)]))
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                # Extract mechanism from description
                mech = desc[:80] if desc else 'RxNorm DDI'

                rows.append({
                    'drug_a':     drug_name,
                    'drug_b':     other_name,
                    'severity':   sev,
                    'confidence': conf,
                    'mechanism':  mech,
                    'source':     'RxNorm',
                    'auc_ratio':  None,
                    'onset_hours': None,
                })

    return rows


# ────────────────────────────────────────────
# LAYER 3: OpenFDA FAERS co-occurrence signal
# High reaction count when two drugs co-prescribed
# ────────────────────────────────────────────

HIGH_RISK_PAIRS = [
    ('warfarin',    'aspirin'),
    ('warfarin',    'clopidogrel'),
    ('warfarin',    'ibuprofen'),
    ('warfarin',    'naproxen'),
    ('warfarin',    'metronidazole'),
    ('warfarin',    'fluconazole'),
    ('warfarin',    'amiodarone'),
    ('warfarin',    'clarithromycin'),
    ('digoxin',     'amiodarone'),
    ('digoxin',     'spironolactone'),
    ('lithium',     'ibuprofen'),
    ('lithium',     'lisinopril'),
    ('lithium',     'furosemide'),
    ('methotrexate','ibuprofen'),
    ('methotrexate','aspirin'),
    ('sertraline',  'tramadol'),
    ('fluoxetine',  'tramadol'),
    ('morphine',    'diazepam'),
    ('morphine',    'quetiapine'),
    ('atorvastatin','clarithromycin'),
    ('simvastatin', 'clarithromycin'),
    ('carbamazepine','valproate'),
    ('phenytoin',   'valproate'),
]

FAERS_BASE = "https://api.fda.gov/drug/event.json"

def fetch_faers_cooccurrence(drug_a: str, drug_b: str) -> dict | None:
    """
    Query FAERS for top reactions when both drugs co-reported.
    Returns co-occurrence metadata.
    """
    a_label = drug_a.replace('_',' ')
    b_label = drug_b.replace('_',' ')

    try:
        url = (f"{FAERS_BASE}?search=patient.drug.medicinalproduct:"
               f"{requests.utils.quote(a_label)}+"
               f"AND+patient.drug.medicinalproduct:"
               f"{requests.utils.quote(b_label)}"
               f"&count=patient.reaction.reactionmeddrapt.exact&limit=5")
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        results = data.get('results', [])
        if not results:
            return None

        top_reactions = [row['term'].lower() for row in results[:5]]
        total_reports = sum(row['count'] for row in results[:5])

        # Classify severity from top reactions
        danger_terms = {'haemorrhage','hemorrhage','death','cardiac arrest',
                        'thrombocytopenia','anaphylaxis','seizure','respiratory failure',
                        'hepatic failure','renal failure','serotonin syndrome',
                        'international normalised ratio increased'}
        warn_terms   = {'dyspnoea','dizziness','nausea','hypotension','bradycardia',
                        'arrhythmia','confusion','bleeding','prolonged prothrombin time'}

        sev = 'low'
        conf = 0.55
        for term in top_reactions:
            if any(d in term for d in danger_terms):
                sev = 'high'; conf = 0.80; break
            elif any(w in term for w in warn_terms):
                sev = 'moderate'; conf = 0.70

        return {
            'severity':      sev,
            'confidence':    conf,
            'top_reactions': top_reactions,
            'report_count':  total_reports,
            'source':        'OpenFDA FAERS',
        }
    except Exception:
        return None


# ────────────────────────────────────────────
# MAIN PIPELINE
# ────────────────────────────────────────────

def run():
    ddi_rows   = []  # drug-drug
    fdi_rows   = []  # food-drug
    seen_pairs = set()

    print("=" * 60)
    print("AbsorbAI DDI Pipeline — 3 free sources")
    print("=" * 60)

    # ── Layer 1: FDA label text parsing
    print("\n[1/3] Parsing OpenFDA drug_interactions_text...")
    fda_ddi_count = 0
    fda_fdi_count = 0
    for drug_name, entry in LABELS.items():
        ddi_text  = entry.get('drug_interactions_text', '')
        warn_text = entry.get('warnings_summary', '')

        new_ddi = parse_fda_ddi_text(drug_name, ddi_text)
        new_fdi = parse_fda_food_interactions(drug_name, ddi_text, warn_text)

        for row in new_ddi:
            key = tuple(sorted([row['drug_a'], row['drug_b']]))
            if key not in seen_pairs:
                seen_pairs.add(key)
                ddi_rows.append(row)
                fda_ddi_count += 1

        fdi_rows.extend(new_fdi)
        fda_fdi_count += len(new_fdi)

    print(f"    DDI pairs extracted: {fda_ddi_count}")
    print(f"    FDI pairs extracted: {fda_fdi_count}")

    # ── Layer 2: RxNorm structured DDI
    print("\n[2/3] Fetching RxNorm structured interactions...")
    rxnorm_count = 0
    rxnorm_fails = 0
    for drug_name in ALL_DRUGS:
        rxcui = get_rxcui_for_drug(drug_name)
        if not rxcui:
            continue

        rows = fetch_rxnorm_interactions(rxcui, drug_name)
        time.sleep(0.12)  # ~8 req/sec, well within free limit

        if not rows:
            rxnorm_fails += 1
            continue

        added = 0
        for row in rows:
            key = tuple(sorted([row['drug_a'], row['drug_b']]))
            if key not in seen_pairs:
                seen_pairs.add(key)
                # RxNorm is more authoritative — higher confidence
                ddi_rows.append(row)
                added += 1
                rxnorm_count += 1
            else:
                # Upgrade confidence/severity if RxNorm says worse
                for existing in ddi_rows:
                    ek = tuple(sorted([existing['drug_a'], existing['drug_b']]))
                    if ek == key:
                        if row['confidence'] > existing['confidence']:
                            existing['confidence'] = row['confidence']
                            existing['severity']   = row['severity']
                            existing['source']     = 'RxNorm (upgraded)'
                        break

        if added:
            print(f"    {drug_name} ({rxcui}): +{added} pairs")

    print(f"    RxNorm new pairs: {rxnorm_count} | no-data: {rxnorm_fails}")

    # ── Layer 3: FAERS co-occurrence for high-risk pairs
    print("\n[3/3] Fetching FAERS co-occurrence for high-risk pairs...")
    faers_upgraded = 0
    for drug_a, drug_b in HIGH_RISK_PAIRS:
        result = fetch_faers_cooccurrence(drug_a, drug_b)
        time.sleep(0.15)
        if not result:
            print(f"    {drug_a} x {drug_b}: no FAERS data")
            continue

        print(f"    {drug_a} x {drug_b}: sev={result['severity']} "
              f"reports={result['report_count']} "
              f"top={result['top_reactions'][0] if result['top_reactions'] else '—'}")

        # Find and upgrade existing pair or add new
        key = tuple(sorted([drug_a, drug_b]))
        found = False
        for row in ddi_rows:
            ek = tuple(sorted([row['drug_a'], row['drug_b']]))
            if ek == key:
                found = True
                if result['confidence'] > row['confidence']:
                    row['confidence']    = result['confidence']
                    row['severity']      = result['severity']
                    row['faers_reports'] = result['report_count']
                    row['top_reactions'] = result['top_reactions']
                    row['source']        = row['source'] + '+FAERS'
                    faers_upgraded += 1
                break

        if not found and result['severity'] in ('high', 'moderate'):
            ddi_rows.append({
                'drug_a':      drug_a,
                'drug_b':      drug_b,
                'severity':    result['severity'],
                'confidence':  result['confidence'],
                'mechanism':   f"FAERS signal: {result['top_reactions'][0] if result['top_reactions'] else 'co-occurrence'}",
                'source':      'OpenFDA FAERS',
                'faers_reports': result['report_count'],
                'top_reactions': result['top_reactions'],
                'auc_ratio':   None,
                'onset_hours': None,
            })

    print(f"    FAERS upgraded {faers_upgraded} existing pairs")

    # ── Deduplicate FDI
    fdi_seen = set()
    fdi_unique = []
    for row in fdi_rows:
        k = (row['drug'], row['food'])
        if k not in fdi_seen:
            fdi_seen.add(k)
            fdi_unique.append(row)
    fdi_rows = fdi_unique

    # ── Sort by severity
    sev_order = {'high': 0, 'moderate': 1, 'low': 2}
    ddi_rows.sort(key=lambda r: (sev_order.get(r['severity'], 9), -r['confidence']))
    fdi_rows.sort(key=lambda r: (sev_order.get(r['severity'], 9), -r['confidence']))

    # ── Write output module
    print(f"\n{'='*60}")
    print(f"Total DDI pairs: {len(ddi_rows)}")
    print(f"Total FDI pairs: {len(fdi_rows)}")
    print(f"Writing → {OUT_PATH}")

    import pprint
    with open(OUT_PATH, 'w') as f:
        f.write('"""\n')
        f.write('Auto-generated DDI/FDI database for AbsorbAI.\n')
        f.write('Sources: OpenFDA Labels, RxNorm (NLM), OpenFDA FAERS\n')
        f.write('All free, no API key required.\n')
        f.write(f'Total DDI pairs: {len(ddi_rows)} | FDI pairs: {len(fdi_rows)}\n')
        f.write('"""\n\n')
        f.write('DRUG_INTERACTIONS = ')
        f.write(pprint.pformat(ddi_rows, width=120))
        f.write('\n\nFOOD_DRUG_INTERACTIONS = ')
        f.write(pprint.pformat(fdi_rows, width=120))
        f.write(f'\n\n_DDI_COUNT = {len(ddi_rows)}\n')
        f.write(f'_FDI_COUNT = {len(fdi_rows)}\n')
        f.write('_SOURCES = ["OpenFDA Labels", "RxNorm (NLM)", "OpenFDA FAERS"]\n')

    print("Done.")

    # ── Print severity breakdown
    from collections import Counter
    sev_counts = Counter(r['severity'] for r in ddi_rows)
    src_counts = Counter(r['source'].split('+')[0] for r in ddi_rows)
    print(f"\nSeverity breakdown: {dict(sev_counts)}")
    print(f"Source breakdown:   {dict(src_counts)}")


if __name__ == '__main__':
    run()
