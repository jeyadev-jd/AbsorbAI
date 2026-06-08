# AbsorbAI

Clinical pharmacokinetic decision-support platform. Simulates personalised drug behaviour using a 10-layer PK/PD engine, Monte Carlo uncertainty quantification, and a pharmacological knowledge graph. For healthcare professionals only — all outputs are decision support, not medical advice.

---

## Quick Start

```bash
pip install django
cd "Absorb AI"
python manage.py runserver
# visit http://127.0.0.1:8000
```

**Demo credentials**

| Role    | Email                | Password   |
|---------|----------------------|------------|
| Doctor  | doctor@demo.com      | doctor123  |
| Patient | patient@demo.com     | patient123 |

---

## Project Structure

```
Absorb AI/
├── absorbai_project/          # Django project config
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── core/
│   ├── views.py               # All API endpoints (24 functions)
│   ├── urls.py                # URL routing (11 API routes)
│   ├── templates/
│   │   └── index.html         # Single-page app (~2300 lines, vanilla JS)
│   │
│   ├── drugdb/
│   │   ├── drug_data.py       # Hand-curated: ~45 drugs, 57 DDI, 25 FDI
│   │   └── ddi_database.py    # Auto-generated from OpenFDA: 113 DDI, 20 FDI
│   │
│   └── engine/                # 10-layer clinical engine
│       ├── orchestrator.py    # Entry point — coordinates all layers
│       ├── input_validator.py # Layer 0 — data quality & confidence scoring
│       ├── biological_twin.py # Layer 1 — patient physiology personalisation
│       ├── pk_pd_engine.py    # Layer 2 — two-compartment PK + PD simulation
│       ├── knowledge_graph.py # Layer 3 — pharmacological causal graph (NetworkX)
│       ├── uncertainty_engine.py  # Layer 4 — Monte Carlo uncertainty
│       ├── optimizer.py       # Layer 5 — Pareto-optimal schedule optimisation
│       ├── adversarial_engine.py  # Layer 6 — stress testing & counterfactuals
│       ├── explainability.py  # Layer 7 — reasoning chains & audit log
│       └── gemma_engine.py    # Layer 8 — evidence-based prescription suggestions
│
├── build_ddi_database.py      # Pipeline: OpenFDA → ddi_database.py
└── manage.py
```

---

## Architecture — 10-Layer Engine

Data flows through layers sequentially inside `orchestrator.analyze_patient_regimen()`.

```
Patient Profile + Prescriptions
        │
        ▼
[Layer 0] Input Validator          input_validator.py
  • Clamps physiological values to plausible ranges
  • Computes data_confidence score (0–1)
  • Scales Monte Carlo sample count via mc_multiplier
  • Blocks simulation if confidence < 0.15 or mandatory fields missing
        │
        ▼
[Layer 1] Biological Twin          biological_twin.py
  • Personalises PK parameters from age, weight, sex, CrCl, Child-Pugh
  • CYP enzyme activity adjustments (3A4, 2C9, 2D6, 2C19, 1A2, 2E1)
  • Renal (Cockcroft-Gault) + hepatic function scaling
        │
        ▼
[Layer 2] PK/PD Engine             pk_pd_engine.py
  • Two-compartment model: central + peripheral volumes
  • Monte Carlo: 100 samples real-time, 500 background thread
  • Outputs: AUC, Cmax, Tmax, concentration timeline, EC50 comparison
  • Bliss independence + Loewe additivity for multi-drug combinations
        │
        ▼
[Layer 3] Knowledge Graph          knowledge_graph.py
  • NetworkX DiGraph of causal pharmacological relationships
  • Nodes: drugs, enzymes, transporters, dietary factors
  • Edges: inhibition, induction, absorption, synergy, antagonism
  • Merges hand-coded + auto-generated DDI/FDI at load time
        │
        ▼
[Layer 4] Uncertainty Engine       uncertainty_engine.py
  • PK std deviations widened proportional to data confidence
  • Credible intervals on AUC/Cmax
        │
        ▼
[Layer 5] Optimizer                optimizer.py
  • Pareto-optimal dosing schedules (minimise peak, maximise trough)
  • Returns up to 10 candidate regimens with trade-off scores
        │
        ▼
[Layer 6] Adversarial Engine       adversarial_engine.py
  • Stress tests: renal impairment, hepatic impairment, elderly
  • Counterfactual "what if" scenarios
        │
        ▼
[Layer 7] Explainability           explainability.py
  • Human-readable reasoning chains per interaction edge
  • Immutable GLOBAL_AUDIT_LOG keyed by patient_id
  • Narrow-TI monitoring flags, safety violation detection
        │
        ▼
[Layer 8] Gemma / Suggestions      gemma_engine.py
  • Evidence-based prescription suggestions (13 condition families)
  • Grounded in local drug DB + KG — no hallucination
  • Optional Gemma 1.5B via Ollama for NL enhancement
        │
        ▼
[Layer 9] Bayesian Update          orchestrator.update_patient_observation()
  • Updates PK priors from real lab values (INR, drug levels)
  • Posterior stored in-memory per (patient_id, drug)
        │
        ▼
Result JSON: decision_support_only, disclaimer, data_quality,
             pk_results, safety_violations, pareto_solutions, audit_entry_id
```

---

## API Reference

Base URL: `http://localhost:8000`

All engine responses include:
```json
{ "decision_support_only": true, "disclaimer": "FOR DECISION SUPPORT ONLY..." }
```

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/login/` | JWT login → sets `absorb_jwt` cookie |
| POST | `/api/logout/` | Clears cookie |

```json
// POST /api/login/ body
{ "email": "doctor@demo.com", "password": "doctor123", "role": "doctor" }
```

### Engine

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/engine/analyze/` | Full 10-layer PK/PD regimen analysis |
| POST | `/api/engine/observation/` | Bayesian update from lab observation |
| POST | `/api/engine/suggestions/` | Evidence-based prescription suggestions |
| GET  | `/api/engine/audit/` | `?patient_id=` — last 20 audit entries |

**Analyze request body:**
```json
{
  "patient_id": "ananya",
  "patient_profile": {
    "age": 42, "weight": 68, "height": 165, "sex": "F",
    "serum_creatinine": 0.9, "child_pugh_score": 5,
    "cyp3a4_activity": 1.0, "cyp2c9_activity": 0.6
  },
  "prescriptions": [
    { "drug_name": "warfarin", "dose_mg": 5, "frequency_per_day": 1,
      "start_time_hr": 8, "bioavailability": 0.93 }
  ],
  "dietary_factors": ["grapefruit", "vitamin_k"]
}
```

**Observation request body:**
```json
{
  "patient_id": "ananya",
  "drug_name": "warfarin",
  "observation_type": "concentration",
  "observed_value": 2.5
}
```

### Patient

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/patient/profile/` | `?patient_key=` — biological twin profile |
| POST | `/api/patient/profile/update/` | Update physiological parameters |

### Drugs

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/drugs/search/` | `?q=&detail=true` — autocomplete + full clinical metadata |
| GET | `/api/drugs/interactions/` | `?drug=` — merged DDI + FDI |

**Interactions response keys:** `ddi[]` · `fdi[]`  
Each item has: `with`, `severity` (high/moderate/low), `mechanism`, `management`

### Adherence

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/adherence/log/` | Log dose event |
| GET  | `/api/adherence/history/` | `?patient_key=` — score + breakdown |

```json
// POST /api/adherence/log/ body
{
  "patient_key": "ananya",
  "rx_id": "rx_warfarin_08:00",
  "drug": "warfarin",
  "scheduled_time": "08:00",
  "status": "taken",
  "taken_at": "2026-05-31T08:05:00Z"
}
// status: "taken" | "skipped" | "late"
```

---

## Drug Database

### Hand-curated (`core/drugdb/drug_data.py`)

~45 drugs. Each entry contains:

```python
"warfarin": {
    "mechanism": "Inhibits VKORC1...",
    "food_effect": "Vitamin K antagonises effect...",
    "monitoring": ["INR weekly until stable", "Signs of bleeding"],
    "therapeutic_range": "INR 2.0-3.0",
    "contraindications": ["active bleeding", "pregnancy"],
    "primary_enzyme": "CYP2C9",
    "narrow_ti": True,
}
```

Drug classes: anticoagulants, antihypertensives, antidiabetics, thyroid, antiepileptics, antibiotics, statins, antidepressants, antiarrhythmics, immunosuppressants, cardiac glycosides, oncology

### Auto-generated (`core/drugdb/ddi_database.py`)

Built by `build_ddi_database.py`:

| Source | Method | Pairs |
|--------|--------|-------|
| OpenFDA Drug Labels | NLP regex on `drug_interactions_text` | 102 |
| OpenFDA FAERS | Co-occurrence on 23 high-risk pairs | 11 |
| RxNorm (NLM) | Structured RxCUI lookup | 0 (DNS blocked in dev) |

Total: **113 DDI + 20 FDI** — deduplicated; hand-coded takes priority on conflict.

**Rebuild:**
```bash
python build_ddi_database.py
# requires openfda_labels.json in project root
# writes core/drugdb/ddi_database.py
```

---

## AI Suggestions

`gemma_engine.generate_doctor_prescription_suggestions()` maps free-text diagnosis to evidence-based drugs via keyword alias matching across 13 condition families:

| Input keywords | Suggested drugs |
|----------------|-----------------|
| hypertension, htn, blood pressure | Amlodipine, Lisinopril |
| diabetes, t2dm, hyperglycemia | Metformin, Empagliflozin |
| afib, atrial fibrillation, warfarin | Warfarin, Apixaban |
| dry cough, ace inhibitor cough | Amlodipine, Losartan |
| arrhythmia, palpitations | Bisoprolol, Amiodarone |
| depression, mdd | Sertraline |
| high cholesterol, statin, ldl | Atorvastatin |
| gerd, acid reflux, heartburn | Omeprazole |
| nausea | Ondansetron, Metoclopramide |
| osteoporosis | Alendronate |
| anemia, iron deficiency | Ferrous Sulfate |
| migraine | Sumatriptan |
| asthma | Salbutamol |
| copd | Tiotropium |

Each suggestion: evidence-based dose/frequency, DDI check against current regimen, `is_consult_fallback` flag (blocks Prescribe button when no guideline match).

---

## Safety Architecture

### Input validation confidence score

```
confidence = (mandatory_present / 4) × 0.75
           + (optional_present / 8) × 0.25
           - suspicion_penalties

mc_multiplier = 1.0 + (1.0 - confidence) × 2.0
unc_scale     = 1.0 + (1.0 - confidence) × 1.5
```

Low confidence → more Monte Carlo samples + wider PK distributions (honest uncertainty, not false precision).

### Disclaimer enforcement — 3 layers

1. **Engine layer** — every `analyze_patient_regimen()` result contains `decision_support_only: true` + full disclaimer text
2. **API layer** — `_dsr()` helper injects disclaimer into every JSON response
3. **UI layer** — session-gated modal before dashboard; `sessionStorage` gate; checkbox required

### Result cache

- In-process `dict`, SHA256 key from `(patient_id, prescriptions, dietary_factors)`, 10-min TTL
- Evicts oldest entries when >200 keys
- Cache invalidated on adherence log event (state changed)

---

## Frontend

Single-page app, vanilla JS, no framework. All pages in `core/templates/index.html`.

**Patient panels:** Overview widgets · Medication schedule · Medication list · Risk summary · Dietary profile · Reminders

**Doctor panels:** New prescription · AI suggestions · Interaction matrix · Audit log · PK analysis

### Key JS functions

| Function | File location (approx. line) | Purpose |
|----------|------------------------------|---------|
| `runEngineAnalysis()` | ~1680 | Calls `/api/engine/analyze/`, renders results |
| `buildPatientTimeline()` | ~1610 | Medication + dynamic meal rows in schedule |
| `buildDynamicMealRows()` | ~1579 | Meal rows from dietary profile + drug food effects |
| `autoFillRxFields()` | ~2026 | Fills Instructions + Clinical Notes from drug API |
| `loadDrugInteractions()` | ~2003 | Fetches DDI/FDI, opens severity-coloured panel |
| `logDose()` | ~1650 | POSTs adherence event, updates score widget |
| `renderAISuggestions()` | ~2160 | Suggestion cards; blocks Prescribe on fallback |
| `showDisclaimerIfNeeded()` | ~1210 | Session-gated disclaimer modal |

---

## Local LLM (Optional)

Gemma 1.5B via Ollama enhances patient explanations. Falls back to deterministic templates — clinical accuracy identical either way.

```bash
ollama pull gemma3:1b
ollama serve
# engine auto-detects at http://localhost:11434
```

---

## Known Limitations

- **In-memory only** — Bayesian posteriors, adherence logs, and cache reset on server restart. No persistent DB for engine state.
- **Demo auth** — JWT secret is hardcoded in `views.py`. Not production-safe.
- **RxNorm DNS** — Structured DDI lookup fails in some network environments; OpenFDA fallback used.
- **Adult PK params** — Paediatric use is flagged and uncertainty widened but population params are adult-derived.
- **No EHR integration** — Patient profiles are demo data; no HL7/FHIR connector.
- **No HTTPS** — Dev server only. Production requires WSGI + TLS.
