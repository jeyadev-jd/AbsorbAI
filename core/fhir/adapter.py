"""
FHIR R4 adapter for AbsorbAI.

FHIRAdapter   — FHIR resources → AbsorbAI internal format
FHIRMapper    — AbsorbAI result  → FHIR resources
"""
import uuid
import datetime
from typing import Dict, List, Any, Optional


# ── FHIRAdapter: FHIR → AbsorbAI ─────────────────────────────────────────────

class FHIRAdapter:
    """
    Parse FHIR R4 resources into AbsorbAI patient_profile + prescriptions dicts.
    Accepts a FHIR Bundle or individual resources.
    """

    def parse_bundle(self, bundle: Dict) -> Dict:
        """
        Parse a FHIR Bundle containing Patient, MedicationRequest, Observation,
        AllergyIntolerance resources.
        Returns: {'patient_id', 'patient_profile', 'prescriptions', 'dietary_factors'}
        """
        entries = bundle.get('entry', [])
        resources = [e.get('resource', {}) for e in entries if e.get('resource')]

        patient_resource = next((r for r in resources if r.get('resourceType') == 'Patient'), None)
        med_requests = [r for r in resources if r.get('resourceType') == 'MedicationRequest']
        observations = [r for r in resources if r.get('resourceType') == 'Observation']
        allergies = [r for r in resources if r.get('resourceType') == 'AllergyIntolerance']

        patient_profile = self.parse_patient(patient_resource, observations) if patient_resource else {}
        patient_id = patient_resource.get('id', 'fhir-patient') if patient_resource else 'fhir-patient'

        prescriptions = [self.parse_medication_request(mr) for mr in med_requests]
        prescriptions = [p for p in prescriptions if p]  # drop None

        dietary_factors = self._extract_dietary_factors(observations, allergies)

        return {
            'patient_id': patient_id,
            'patient_profile': patient_profile,
            'prescriptions': prescriptions,
            'dietary_factors': dietary_factors,
        }

    def parse_patient(self, patient: Dict, observations: List[Dict] = None) -> Dict:
        """Extract AbsorbAI patient_profile from FHIR Patient + Observations."""
        profile: Dict[str, Any] = {}

        # Demographics
        name = patient.get('name', [{}])[0]
        given = ' '.join(name.get('given', []))
        family = name.get('family', '')
        profile['name'] = f"{given} {family}".strip() or 'Unknown'

        # Birth date → age
        birth_date = patient.get('birthDate', '')
        if birth_date:
            try:
                born = datetime.date.fromisoformat(birth_date)
                profile['age'] = (datetime.date.today() - born).days // 365
            except Exception:
                profile['age'] = 45
        else:
            profile['age'] = 45

        # Sex
        gender = patient.get('gender', 'unknown').lower()
        profile['sex'] = 'F' if gender in ('female', 'f') else 'M'

        # Extensions: weight, height
        for ext in patient.get('extension', []):
            url = ext.get('url', '')
            val = ext.get('valueQuantity', {})
            if 'bodyWeight' in url or 'body-weight' in url:
                profile['weight'] = float(val.get('value', 70))
            elif 'bodyHeight' in url or 'body-height' in url:
                profile['height'] = float(val.get('value', 170))

        # Observations: lab values → PK parameters
        if observations:
            for obs in observations:
                code_text = _obs_code_text(obs)
                value = _obs_value(obs)
                if value is None:
                    continue
                cl = code_text.lower()
                if 'creatinine' in cl and 'serum' in cl:
                    profile['serum_creatinine'] = float(value)
                elif 'albumin' in cl:
                    profile['plasma_albumin'] = float(value)
                elif 'bilirubin' in cl or 'child-pugh' in cl:
                    profile['child_pugh_score'] = int(value)
                elif 'body fat' in cl or 'body_fat' in cl:
                    profile['body_fat_pct'] = float(value)

        # Defaults for missing fields
        defaults = {
            'weight': 70, 'height': 170, 'serum_creatinine': 1.0,
            'child_pugh_score': 5, 'body_fat_pct': 20.0, 'plasma_albumin': 4.0,
            'gut_motility_score': 1.0, 'hydration_score': 1.0,
            'is_sick': False, 'alcohol_last_24h': False,
            'cyp3a4_activity': 1.0, 'cyp2d6_activity': 1.0,
            'cyp2c9_activity': 1.0, 'cyp2c19_activity': 1.0,
            'cyp1a2_activity': 1.0, 'cyp2e1_activity': 1.0,
            'wake_time_hr': 6.5, 'sleep_time_hr': 22.5,
            'meal_times_hr': [7.5, 13.0, 19.5],
        }
        for k, v in defaults.items():
            profile.setdefault(k, v)

        return profile

    def parse_medication_request(self, mr: Dict) -> Optional[Dict]:
        """Convert FHIR MedicationRequest → AbsorbAI prescription dict."""
        # Drug name
        med = mr.get('medicationCodeableConcept', {})
        drug_name = (med.get('text') or
                     (med.get('coding', [{}])[0].get('display', '')) or '').strip().lower()
        if not drug_name:
            return None

        dosage = (mr.get('dosageInstruction') or [{}])[0]

        # Dose
        dose_qty = (dosage.get('doseAndRate') or [{}])[0].get('doseQuantity', {})
        dose_mg = float(dose_qty.get('value', 100))

        # Frequency
        timing = dosage.get('timing', {}).get('repeat', {})
        freq = int(timing.get('frequency', 1))
        period = float(timing.get('period', 1))
        period_unit = timing.get('periodUnit', 'd')
        if period_unit == 'd':
            freq_per_day = int(freq / period)
        else:
            freq_per_day = freq
        freq_per_day = max(1, freq_per_day)

        # Food instructions
        with_food = False
        empty_stomach = False
        instructions_text = (dosage.get('text') or '').lower()
        for code in (dosage.get('additionalInstruction') or []):
            ct = (code.get('text') or '').lower()
            instructions_text += ' ' + ct
        if 'with food' in instructions_text or 'with meal' in instructions_text:
            with_food = True
        if 'empty stomach' in instructions_text or 'fasting' in instructions_text:
            empty_stomach = True

        return {
            'drug_name': drug_name,
            'dose_mg': dose_mg,
            'frequency_per_day': freq_per_day,
            'start_time_hr': 8.0,
            'bioavailability': 0.8,
            'with_food': with_food,
            'empty_stomach': empty_stomach,
        }

    def _extract_dietary_factors(self, observations: List[Dict], allergies: List[Dict]) -> List[str]:
        factors = []
        dietary_keywords = ['grapefruit', 'alcohol', 'dairy', 'caffeine', 'vitamin k', 'tyramine']
        for obs in observations:
            text = _obs_code_text(obs).lower()
            for kw in dietary_keywords:
                if kw in text:
                    factors.append(kw)
        for allergy in allergies:
            sub = allergy.get('code', {}).get('text', '').lower()
            for kw in dietary_keywords:
                if kw in sub:
                    factors.append(kw)
        return list(set(factors))


# ── FHIRMapper: AbsorbAI → FHIR ──────────────────────────────────────────────

class FHIRMapper:
    """
    Map AbsorbAI engine result → FHIR R4 resources:
    - DetectedIssue  per safety violation / interaction
    - RiskAssessment per drug (PK/PD summary)
    - GuidanceResponse for the overall optimizer recommendation
    """

    def result_to_bundle(self, result: Dict, patient_id: str) -> Dict:
        """Wrap all mapped resources in a FHIR Bundle."""
        entries = []

        # DetectedIssue per safety violation
        for v in result.get('safety_violations', []):
            entries.append({'resource': self._safety_violation_to_detected_issue(v, patient_id)})

        # DetectedIssue per drug-drug / drug-food interaction
        for chain in result.get('interaction_chains', []):
            entries.append({'resource': self._interaction_to_detected_issue(chain, patient_id)})

        # RiskAssessment per drug
        for drug, pk_data in result.get('pk_results', {}).items():
            entries.append({'resource': self._pk_to_risk_assessment(drug, pk_data, patient_id)})

        # GuidanceResponse for best Pareto schedule
        schedules = result.get('pareto_schedules', [])
        if schedules:
            entries.append({'resource': self._schedule_to_guidance_response(schedules[0], patient_id)})

        return {
            'resourceType': 'Bundle',
            'id': str(uuid.uuid4()),
            'type': 'collection',
            'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
            'entry': entries,
        }

    def _safety_violation_to_detected_issue(self, violation: Dict, patient_id: str) -> Dict:
        sev = violation.get('severity', 'MODERATE').upper()
        fhir_sev = 'high' if sev == 'FATAL' else 'moderate' if sev in ('HIGH', 'MODERATE') else 'low'
        return {
            'resourceType': 'DetectedIssue',
            'id': str(uuid.uuid4()),
            'status': 'final',
            'severity': fhir_sev,
            'code': {
                'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode',
                             'code': 'DRG', 'display': 'Drug Interaction'}],
                'text': violation.get('message', 'Safety violation'),
            },
            'subject': {'reference': f'Patient/{patient_id}'},
            'detail': violation.get('recommendation', ''),
            'implicated': [
                {'display': violation.get('drug', '')}
            ],
        }

    def _interaction_to_detected_issue(self, chain: Dict, patient_id: str) -> Dict:
        sev_score = float(chain.get('severity', 0))
        fhir_sev = 'high' if sev_score >= 0.7 else 'moderate' if sev_score >= 0.4 else 'low'
        return {
            'resourceType': 'DetectedIssue',
            'id': str(uuid.uuid4()),
            'status': 'final',
            'severity': fhir_sev,
            'code': {
                'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode',
                             'code': 'DRG', 'display': 'Drug Interaction'}],
                'text': f"{chain.get('entity_a', '')} ↔ {chain.get('entity_b', '')}",
            },
            'subject': {'reference': f'Patient/{patient_id}'},
            'detail': chain.get('reasoning_chain', chain.get('mechanism', '')),
            'implicated': [
                {'display': chain.get('entity_a', '')},
                {'display': chain.get('entity_b', '')},
            ],
            'extension': [
                {
                    'url': 'https://absorbai.io/fhir/ext/interaction-severity-score',
                    'valueDecimal': round(sev_score, 3),
                },
                {
                    'url': 'https://absorbai.io/fhir/ext/interaction-mechanism',
                    'valueString': chain.get('mechanism', ''),
                },
            ],
        }

    def _pk_to_risk_assessment(self, drug: str, pk_data: Dict, patient_id: str) -> Dict:
        sim = pk_data.get('simulation', {})
        mc = pk_data.get('uncertainty', {})
        auc = sim.get('auc')
        cmax = sim.get('cmax')
        efficacy = pk_data.get('efficacy_probability')

        predictions = []
        if efficacy is not None:
            predictions.append({
                'outcome': {'text': 'Therapeutic efficacy probability'},
                'probabilityDecimal': round(float(efficacy), 3),
                'rationale': f'Monte Carlo PK/PD simulation over 72h',
            })
        if cmax is not None:
            predictions.append({
                'outcome': {'text': f'Cmax (peak concentration)'},
                'qualitativeRisk': {'text': f'{round(float(cmax), 4)} mg/L'},
            })

        return {
            'resourceType': 'RiskAssessment',
            'id': str(uuid.uuid4()),
            'status': 'final',
            'subject': {'reference': f'Patient/{patient_id}'},
            'basis': [{'display': f'AbsorbAI PK/PD engine v{pk_data.get("engine_version", "1.0.0")}'}],
            'prediction': predictions,
            'note': [{'text': f'Drug: {drug} | AUC: {auc} | Half-life: {pk_data.get("pk_params", {}).get("half_life_mean")} h'}],
            'extension': [
                {
                    'url': 'https://absorbai.io/fhir/ext/drug-name',
                    'valueString': drug,
                },
                {
                    'url': 'https://absorbai.io/fhir/ext/pk-params',
                    'valueString': str(pk_data.get('pk_params', {})),
                },
            ],
        }

    def _schedule_to_guidance_response(self, schedule: Dict, patient_id: str) -> Dict:
        doses_text = '; '.join(
            f"{d.get('drug')} {d.get('dose_mg')}mg at {d.get('time_hr')}h"
            for d in schedule.get('doses', [])[:10]
        )
        return {
            'resourceType': 'GuidanceResponse',
            'id': str(uuid.uuid4()),
            'requestIdentifier': {'value': str(uuid.uuid4())},
            'moduleUri': 'https://absorbai.io/fhir/modules/pkpd-optimizer',
            'status': 'success',
            'subject': {'reference': f'Patient/{patient_id}'},
            'result': {'display': f"Optimal schedule: {doses_text}"},
            'note': [
                {'text': schedule.get('label', 'Pareto-optimal medication schedule')},
                {'text': f"Feasible: {schedule.get('is_feasible', True)}"},
            ],
            'extension': [
                {
                    'url': 'https://absorbai.io/fhir/ext/schedule-objectives',
                    'valueString': str(schedule.get('objectives', {})),
                }
            ],
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _obs_code_text(obs: Dict) -> str:
    code = obs.get('code', {})
    return (code.get('text') or
            (code.get('coding', [{}])[0].get('display', '')) or '')


def _obs_value(obs: Dict):
    if 'valueQuantity' in obs:
        return obs['valueQuantity'].get('value')
    if 'valueString' in obs:
        return obs['valueString']
    if 'valueInteger' in obs:
        return obs['valueInteger']
    return None
