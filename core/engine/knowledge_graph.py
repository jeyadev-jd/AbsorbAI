"""
Layer 5: Causal Mechanistic Knowledge Graph
Not a lookup table — stores causal mechanisms with direction, magnitude,
confidence, and enzyme pathway. Enables first-principles interaction reasoning.
Layer 6 partial: temporal kinetics of enzyme inhibition onset/offset.
"""
import networkx as nx
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
import math

try:
    from ..drugdb.drug_data import DRUG_INTERACTIONS as _HAND_INTERACTIONS, FOOD_DRUG_INTERACTIONS as _HAND_FOOD
except ImportError:
    _HAND_INTERACTIONS = []
    _HAND_FOOD = []

try:
    from ..drugdb.ddi_database import DRUG_INTERACTIONS as _AUTO_INTERACTIONS, FOOD_DRUG_INTERACTIONS as _AUTO_FOOD
except ImportError:
    _AUTO_INTERACTIONS = []
    _AUTO_FOOD = []

# Hand-coded pairs win (higher precision); auto-generated fills the rest
_HAND_KEYS = {tuple(sorted([r['drug_a'], r['drug_b']])) for r in _HAND_INTERACTIONS}
_HAND_FOOD_KEYS = {(r['drug'], r['food']) for r in _HAND_FOOD}
_DB_INTERACTIONS = _HAND_INTERACTIONS + [
    r for r in _AUTO_INTERACTIONS
    if tuple(sorted([r['drug_a'], r['drug_b']])) not in _HAND_KEYS
]
_DB_FOOD = _HAND_FOOD + [
    r for r in _AUTO_FOOD
    if (r['drug'], r['food']) not in _HAND_FOOD_KEYS
]


@dataclass
class CausalEdge:
    """A causal relationship between two entities in the pharmacological network"""
    source: str           # e.g. 'grapefruit', 'warfarin', 'CYP3A4'
    target: str           # e.g. 'CYP3A4', 'amlodipine_clearance'
    mechanism: str        # 'competitive_inhibition', 'induction', 'chelation', 'substrate', etc.
    direction: str        # 'inhibits', 'induces', 'substrate_of', 'chelates', 'activates'
    magnitude: float      # e.g. IC50 in µM, or fold-change
    magnitude_unit: str   # 'µM_IC50', 'fold_change', 'AUC_ratio', 'fraction_clearance'
    confidence: float     # 0.0-1.0
    evidence_count: int   # number of clinical studies
    references: List[str] = field(default_factory=list)
    # Temporal kinetics (Layer 6)
    onset_hours: float = 1.0   # hours until effect builds
    offset_hours: float = 24.0  # hours until enzyme recovers after cessation
    is_irreversible: bool = False  # mechanism-based (permanent until resynthesis)


class PharmacologicalKnowledgeGraph:
    """
    Causal knowledge graph of drug-enzyme-drug interactions.
    Traversal computes interaction magnitude from first principles.
    """

    def __init__(self):
        self.G = nx.DiGraph()
        self._build_base_graph()
        self._load_drugdb_interactions()

    def _build_base_graph(self):
        """Populate with evidence-based causal edges"""
        edges = [
            # ─── ENZYME NODES ───
            # CYP3A4 substrates
            CausalEdge('amlodipine', 'CYP3A4', 'substrate_metabolism', 'substrate_of',
                       0.70, 'fraction_clearance', 0.95, 8,
                       ['FDA Norvasc Label', 'PMID 8568566']),
            CausalEdge('atorvastatin', 'CYP3A4', 'substrate_metabolism', 'substrate_of',
                       0.70, 'fraction_clearance', 0.92, 12,
                       ['FDA Lipitor Label', 'PMID 9920423']),
            CausalEdge('omeprazole', 'CYP2C19', 'substrate_metabolism', 'substrate_of',
                       0.87, 'fraction_clearance', 0.95, 15,
                       ['FDA Prilosec Label']),

            # CYP3A4 inhibitors
            CausalEdge('grapefruit', 'CYP3A4', 'intestinal_inhibition', 'inhibits',
                       1.0, 'µM_IC50', 0.92, 6,
                       ['PMID 8568566', 'PMID 9218827'],
                       onset_hours=0.5, offset_hours=72.0),
            CausalEdge('clarithromycin', 'CYP3A4', 'mechanism_based_inhibition', 'inhibits',
                       2.5, 'µM_IC50', 0.93, 11,
                       ['FDA Label', 'PMID 10573201'],
                       onset_hours=12.0, offset_hours=120.0, is_irreversible=True),
            CausalEdge('fluconazole', 'CYP3A4', 'competitive_inhibition', 'inhibits',
                       15.0, 'µM_IC50', 0.90, 14,
                       ['FDA Diflucan Label'],
                       onset_hours=2.0, offset_hours=48.0),
            CausalEdge('fluconazole', 'CYP2C9', 'competitive_inhibition', 'inhibits',
                       2.8, 'µM_IC50', 0.95, 20,
                       ['PMID 8706019']),

            # CYP2C9 substrates
            CausalEdge('warfarin', 'CYP2C9', 'substrate_metabolism', 'substrate_of',
                       0.92, 'fraction_clearance', 0.97, 25,
                       ['FDA Coumadin Label', 'PMID 2060551']),

            # CYP2D6 substrates and inhibitors
            CausalEdge('metoprolol', 'CYP2D6', 'substrate_metabolism', 'substrate_of',
                       0.75, 'fraction_clearance', 0.93, 10),
            CausalEdge('fluoxetine', 'CYP2D6', 'competitive_inhibition', 'inhibits',
                       0.2, 'µM_IC50', 0.95, 18,
                       ['PMID 9274810'],
                       onset_hours=6.0, offset_hours=240.0),  # long washout

            # P-glycoprotein
            CausalEdge('digoxin', 'P-gp', 'substrate_transport', 'substrate_of',
                       0.60, 'fraction_clearance', 0.88, 12,
                       ['FDA Lanoxin Label']),
            CausalEdge('clarithromycin', 'P-gp', 'competitive_inhibition', 'inhibits',
                       5.0, 'µM_IC50', 0.85, 8),

            # ─── DRUG-NUTRIENT INTERACTIONS ───
            # Calcium chelation
            CausalEdge('calcium', 'levothyroxine_absorption', 'chelation_complex', 'chelates',
                       0.40, 'AUC_reduction_fraction', 0.95, 12,
                       ['DrugBank DB01089', 'PMID 2060551'],
                       onset_hours=0.0, offset_hours=4.0),
            CausalEdge('calcium', 'fluoroquinolone_absorption', 'chelation_complex', 'chelates',
                       0.50, 'AUC_reduction_fraction', 0.93, 9),
            CausalEdge('iron', 'levothyroxine_absorption', 'chelation_complex', 'chelates',
                       0.30, 'AUC_reduction_fraction', 0.90, 8,
                       ['PMID 2060551']),

            # Vitamin K antagonism
            CausalEdge('vitamin_k', 'warfarin_anticoagulation', 'clotting_factor_competition', 'antagonizes',
                       1.0, 'fold_change', 0.99, 30,
                       ['FDA Coumadin Label', 'PMID 7803476'],
                       onset_hours=12.0, offset_hours=96.0),

            # Food effects on absorption
            CausalEdge('high_fat_meal', 'levothyroxine_absorption', 'GI_barrier', 'reduces',
                       0.25, 'AUC_reduction_fraction', 0.85, 6,
                       ['PMID 9922410']),
            CausalEdge('food_generic', 'metformin_absorption', 'GI_motility', 'reduces',
                       0.17, 'Cmax_reduction_fraction', 0.88, 5,
                       ['PMID 1888786']),

            # Grapefruit → CYP3A4 substrates
            CausalEdge('grapefruit', 'amlodipine_exposure', 'CYP3A4_intestinal', 'increases',
                       1.40, 'AUC_ratio', 0.88, 4,
                       ['PMID 8568566']),
            CausalEdge('grapefruit', 'atorvastatin_exposure', 'CYP3A4_intestinal', 'increases',
                       1.83, 'AUC_ratio', 0.85, 3,
                       ['PMID 15140266']),

            # ─── DRUG-DRUG INTERACTIONS ───
            CausalEdge('warfarin', 'aspirin', 'platelet_function', 'synergizes',
                       2.5, 'bleeding_risk_ratio', 0.92, 18,
                       ['PMID 15998703']),
            CausalEdge('metformin', 'contrast_media', 'renal_clearance', 'reduces',
                       3.0, 'lactic_acidosis_risk', 0.80, 6,
                       ['FDA Label']),
            CausalEdge('digoxin', 'amiodarone', 'P-gp_inhibition', 'increases',
                       1.7, 'AUC_ratio', 0.90, 9,
                       ['PMID 3513566']),
        ]

        for e in edges:
            self.G.add_node(e.source, node_type='entity')
            self.G.add_node(e.target, node_type='entity')
            self.G.add_edge(
                e.source, e.target,
                mechanism=e.mechanism,
                direction=e.direction,
                magnitude=e.magnitude,
                magnitude_unit=e.magnitude_unit,
                confidence=e.confidence,
                evidence_count=e.evidence_count,
                references=e.references,
                onset_hours=e.onset_hours,
                offset_hours=e.offset_hours,
                is_irreversible=e.is_irreversible,
            )

    def _load_drugdb_interactions(self):
        """Load drug-drug and food-drug interactions from local drug database."""
        _sev_map = {'high': 0.85, 'major': 0.90, 'moderate': 0.55, 'mod': 0.55,
                    'low': 0.25, 'minor': 0.20, 'critical': 0.95}

        def _parse_sev(val, default=0.5):
            if val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return _sev_map.get(str(val).lower().strip(), default)

        def _parse_onset(row):
            v = row.get('onset_hrs') or row.get('onset_hours')
            try:
                return float(v) if v is not None else 6.0
            except (TypeError, ValueError):
                return 6.0

        # Drug-drug interactions from DRUG_INTERACTIONS
        for row in _DB_INTERACTIONS:
            a = row['drug_a'].lower()
            b = row['drug_b'].lower()
            # Skip if edge already exists (base graph takes priority)
            if self.G.has_edge(a, b):
                continue
            self.G.add_node(a, node_type='entity')
            self.G.add_node(b, node_type='entity')
            magnitude = row.get('auc_ratio') or 1.0
            self.G.add_edge(
                a, b,
                mechanism=row.get('mechanism', 'pharmacokinetic_interaction'),
                direction=row.get('direction', 'interacts'),
                magnitude=float(magnitude),
                magnitude_unit='AUC_ratio' if row.get('auc_ratio') else 'severity_score',
                confidence=float(row.get('confidence', 0.80)),
                evidence_count=len(row.get('references', [])) or 2,
                references=row.get('references', []),
                onset_hours=_parse_onset(row),
                offset_hours=24.0,
                is_irreversible=False,
                severity=_parse_sev(row.get('severity')),
            )

        # Food-drug interactions from FOOD_DRUG_INTERACTIONS
        for row in _DB_FOOD:
            food = row['food'].lower()
            drug = row['drug'].lower()
            if self.G.has_edge(food, drug):
                continue
            self.G.add_node(food, node_type='dietary')
            self.G.add_node(drug, node_type='entity')
            auc_chg = row.get('auc_change_pct')
            magnitude = abs(auc_chg) / 100.0 if auc_chg else 0.2
            sev_map = {'CRITICAL': 0.95, 'HIGH': 0.80, 'MODERATE': 0.55, 'LOW': 0.25}
            severity = sev_map.get(row.get('severity', 'LOW'), 0.25)
            self.G.add_edge(
                food, drug + '_absorption',
                mechanism=row.get('mechanism', 'food_drug_interaction'),
                direction='increases' if (auc_chg or 0) > 0 else 'reduces',
                magnitude=magnitude,
                magnitude_unit='AUC_change_fraction',
                confidence=0.85,
                evidence_count=1,
                references=[row.get('reference', '')],
                onset_hours=0.5,
                offset_hours=6.0,
                is_irreversible=False,
                severity=severity,
            )

    def _node_matches(self, node: str, drug: str) -> bool:
        """Node matches drug if equal or is a derived target (e.g. warfarin_anticoagulation)"""
        return node == drug or node.startswith(drug + '_')

    def _edge_to_dict(self, src: str, tgt: str, hops: int = 1) -> Dict:
        ed = self.G[src][tgt]
        return {
            'path': [src, tgt],
            'mechanism': ed['mechanism'],
            'direction': ed['direction'],
            'magnitude': ed['magnitude'],
            'magnitude_unit': ed['magnitude_unit'],
            'confidence': ed['confidence'],
            'evidence_count': ed['evidence_count'],
            'references': ed['references'],
            'onset_hours': ed['onset_hours'],
            'offset_hours': ed['offset_hours'],
            'is_irreversible': ed['is_irreversible'],
            'hops': hops,
        }

    def query_interaction(self, drug_a: str, drug_b: str) -> List[Dict]:
        """
        Find causal interaction paths between two drugs.
        Handles both direct edges and derived targets (e.g. warfarin_anticoagulation).
        """
        a = drug_a.lower().replace(' ', '_')
        b = drug_b.lower().replace(' ', '_')
        interactions = []
        seen = set()

        if not self.G.has_node(a):
            return []

        # 1-hop: a → any node that matches b
        for tgt in list(self.G.successors(a)):
            if self._node_matches(tgt, b):
                key = (a, tgt)
                if key not in seen:
                    seen.add(key)
                    interactions.append(self._edge_to_dict(a, tgt, hops=1))

        # 2-hop: a → mid → any node matching b (enzyme/transporter pathway)
        for mid in list(self.G.successors(a)):
            e1 = self.G[a][mid]
            for tgt2 in list(self.G.successors(mid)):
                if not self._node_matches(tgt2, b):
                    continue
                key = (a, mid, tgt2)
                if key in seen:
                    continue
                seen.add(key)
                e2 = self.G[mid][tgt2]
                # Compose magnitudes
                if e1['magnitude_unit'] == 'µM_IC50' and e2['magnitude_unit'] == 'fraction_clearance':
                    inhibition_frac = min(1.0 / (1.0 + max(e1['magnitude'], 0.001)), 0.95)
                    auc_increase = 1.0 / max(1.0 - e2['magnitude'] * inhibition_frac, 0.05)
                    composed_magnitude = auc_increase
                    composed_unit = 'AUC_ratio'
                    composed_direction = 'increases'
                else:
                    composed_magnitude = e1['magnitude'] * e2['magnitude']
                    composed_unit = e2['magnitude_unit']
                    composed_direction = e2['direction']
                interactions.append({
                    'path': [a, mid, tgt2],
                    'mechanism': f"{e1['mechanism']} → {e2['mechanism']}",
                    'direction': composed_direction,
                    'magnitude': composed_magnitude,
                    'magnitude_unit': composed_unit,
                    'confidence': e1['confidence'] * e2['confidence'],
                    'evidence_count': min(e1['evidence_count'], e2['evidence_count']),
                    'references': e1['references'] + e2['references'],
                    'onset_hours': max(e1['onset_hours'], e2.get('onset_hours', 0)),
                    'offset_hours': max(e1['offset_hours'], e2.get('offset_hours', 24)),
                    'is_irreversible': e1.get('is_irreversible', False) or e2.get('is_irreversible', False),
                    'hops': 2,
                    'intermediate': mid,
                })

        return sorted(interactions, key=lambda x: x['confidence'], reverse=True)

    def _expand_drug_name(self, drug: str) -> List[str]:
        """Expand a drug name to all related node names in the graph"""
        base = drug.lower().replace(' ', '_')
        variants = [base]
        # Add common suffix variants used as targets
        for suffix in ('_absorption', '_exposure', '_anticoagulation', '_clearance'):
            candidate = base + suffix
            if self.G.has_node(candidate):
                variants.append(candidate)
        return variants

    def query_drug_interactions_for_regimen(self, drugs: List[str],
                                             dietary_factors: List[str] = None) -> List[Dict]:
        """
        Compute all pairwise + diet-drug interactions for a polypharmacy regimen.
        Returns interactions sorted by clinical severity.
        """
        base_entities = [d.lower().replace(' ', '_') for d in drugs]
        if dietary_factors:
            base_entities += [f.lower().replace(' ', '_') for f in dietary_factors]

        # Expand to include absorption/exposure variants
        all_entities = []
        for e in base_entities:
            all_entities.extend(self._expand_drug_name(e))

        results = []
        seen_paths = set()

        for a in all_entities:
            for b in all_entities:
                if a == b:
                    continue
                ints = self.query_interaction(a, b)
                for itx in ints:
                    path_key = tuple(itx['path'])
                    if path_key in seen_paths:
                        continue
                    seen_paths.add(path_key)
                    severity = self._compute_severity(itx)
                    results.append({**itx, 'severity': severity,
                                    'entity_a': a, 'entity_b': b})

        return sorted(results, key=lambda x: x['severity'], reverse=True)

    def counterfactual_risk_contribution(self, drugs: List[str]) -> Dict[str, float]:
        """
        Layer 5: counterfactual reasoning.
        Returns per-drug contribution to total interaction risk.
        'Remove Drug X → risk drops by N%'
        """
        total_risk = self._total_interaction_risk(drugs)
        contributions = {}
        for drug in drugs:
            remaining = [d for d in drugs if d != drug]
            risk_without = self._total_interaction_risk(remaining)
            drop_pct = (total_risk - risk_without) / max(total_risk, 0.001) * 100.0
            contributions[drug] = round(drop_pct, 1)
        return contributions

    def _total_interaction_risk(self, drugs: List[str]) -> float:
        all_ints = self.query_drug_interactions_for_regimen(drugs)
        return sum(i['severity'] * i['confidence'] for i in all_ints)

    def _compute_severity(self, interaction: Dict) -> float:
        """Normalize interaction to 0-1 severity score"""
        mag = interaction['magnitude']
        unit = interaction['magnitude_unit']
        if unit == 'AUC_ratio':
            return min((mag - 1.0) / 4.0, 1.0) if mag > 1.0 else 0.0
        elif unit == 'AUC_reduction_fraction':
            return mag * 0.8
        elif unit == 'fraction_clearance':
            return 0.3
        elif unit == 'µM_IC50':
            return min(1.0 / (1.0 + mag), 0.9)  # lower IC50 = more potent inhibitor
        elif unit == 'fold_change':
            return min((mag - 1.0) / 3.0, 1.0)
        elif unit in ('bleeding_risk_ratio', 'lactic_acidosis_risk'):
            return min((mag - 1.0) / 3.0, 1.0)
        return 0.2

    def get_reasoning_chain(self, interaction: Dict) -> str:
        """
        Layer 9: Generate human-readable reasoning chain for an interaction.
        """
        path = interaction.get('path', [])
        mech = interaction.get('mechanism', '')
        mag = interaction.get('magnitude', 0)
        unit = interaction.get('magnitude_unit', '')
        conf = interaction.get('confidence', 0)
        refs = interaction.get('references', [])
        hops = interaction.get('hops', 1)
        onset = interaction.get('onset_hours', 1)
        offset = interaction.get('offset_hours', 24)
        irreversible = interaction.get('is_irreversible', False)

        chain = []
        if hops == 1:
            chain.append(f"{path[0]} directly {interaction.get('direction','interacts with')} {path[1]}")
            chain.append(f"via {mech}")
        elif hops == 2:
            chain.append(f"{path[0]} {interaction.get('direction','affects')} {path[1]} "
                         f"(the intermediate enzyme/transporter)")
            chain.append(f"{path[1]} is responsible for {path[2]} via {mech}")

        if unit == 'AUC_ratio':
            chain.append(f"Expected exposure increase: {mag:.1f}× (AUC ratio)")
        elif unit == 'AUC_reduction_fraction':
            chain.append(f"Expected absorption reduction: {mag*100:.0f}%")
        elif unit == 'µM_IC50':
            chain.append(f"IC50 = {mag} µM (lower = stronger inhibition)")

        chain.append(f"Confidence: {conf*100:.0f}% ({interaction.get('evidence_count',0)} studies)")
        if refs:
            chain.append(f"Key reference: {refs[0]}")

        if onset > 0:
            chain.append(f"Interaction builds over {onset:.0f} hrs; "
                         f"{'irreversible (requires enzyme resynthesis)' if irreversible else f'resolves ~{offset:.0f} hrs after cessation'}")

        return ' | '.join(chain)


# Temporal enzyme recovery model (Layer 6)
def compute_enzyme_inhibition_time_course(
    inhibitor_concentration_profile: List[float],  # Cp at each time point
    ki: float,                                      # inhibition constant µM
    kinact: float = 0.03,                           # mechanism-based: inactivation rate 1/hr
    kdeg: float = 0.0193,                           # enzyme degradation rate 1/hr (CYP3A4)
    ksyn: float = None,                             # enzyme synthesis rate
    initial_activity: float = 1.0,
    is_irreversible: bool = False,
    times: List[float] = None,
) -> List[float]:
    """
    Layer 6: Model enzyme activity over time during and after inhibitor exposure.
    Returns enzyme activity fraction at each time point.
    For reversible inhibition: activity = 1 / (1 + [I]/Ki)
    For irreversible (MBI): enzyme recovery tracks resynthesis kinetics.
    """
    if ksyn is None:
        ksyn = kdeg  # at steady state, synthesis = degradation

    if times is None:
        times = list(range(len(inhibitor_concentration_profile)))

    activities = []
    enzyme_level = initial_activity  # relative enzyme amount

    for i, (t, c_inh) in enumerate(zip(times, inhibitor_concentration_profile)):
        if is_irreversible:
            # MBI: enzyme inactivated proportional to [I] and kinact
            dt = (times[i] - times[i-1]) if i > 0 else 1.0
            inactivation = kinact * c_inh / (ki + c_inh) * enzyme_level
            recovery = ksyn - kdeg * enzyme_level
            enzyme_level += (recovery - inactivation) * dt
            enzyme_level = max(enzyme_level, 0.01)
            activities.append(enzyme_level / initial_activity)
        else:
            # Reversible: competitive inhibition — instant equilibrium
            activity = 1.0 / (1.0 + c_inh / max(ki, 0.001))
            activities.append(activity)

    return activities
