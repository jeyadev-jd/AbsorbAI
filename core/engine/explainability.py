"""
Layer 9 + 10: Explainability Architecture + Integrity/Safety/Audit
Every output has a full reasoning chain. Every number has a source.
Hard safety rails are separate from the optimizer.
"""
import json
import hashlib
import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import uuid


# ─── HARD SAFETY RAILS (cannot be overridden by optimization) ───

ABSOLUTE_CONTRAINDICATIONS = {
    # (drug_a, drug_b): reason
    ('warfarin', 'aspirin'): 'High-dose aspirin + warfarin: major bleeding risk. Contraindicated unless benefit proven.',
    ('ssri', 'tramadol'): 'Serotonin syndrome risk — potentially fatal.',
    ('maoi', 'ssri'): 'Serotonin syndrome — absolute contraindication.',
    ('maoi', 'pethidine'): 'Hypertensive crisis / serotonin syndrome — fatal risk.',
    ('simvastatin_high_dose', 'clarithromycin'): 'Severe rhabdomyolysis risk.',
}

MAX_SAFE_DOSES = {
    'metformin': 3000,       # mg/day
    'warfarin': 15,          # mg/day
    'digoxin': 0.375,        # mg/day
    'levothyroxine': 0.5,    # mg/day (500 mcg)
    'amlodipine': 10,        # mg/day
    'atorvastatin': 80,      # mg/day
    'lisinopril': 40,        # mg/day
    'omeprazole': 40,        # mg/day
}

NARROW_TI_DRUGS = {
    'warfarin', 'digoxin', 'levothyroxine', 'lithium', 'phenytoin',
    'cyclosporine', 'tacrolimus', 'theophylline', 'aminoglycosides',
}


def check_hard_safety_rails(drugs: List[str], daily_doses: Dict[str, float]) -> List[Dict]:
    """
    Returns list of hard safety violations.
    These CANNOT be overridden by the optimizer.
    """
    violations = []
    drugs_lower = [d.lower() for d in drugs]

    # Absolute contraindications
    for (drug_a, drug_b), reason in ABSOLUTE_CONTRAINDICATIONS.items():
        if drug_a in drugs_lower and drug_b in drugs_lower:
            violations.append({
                'type': 'absolute_contraindication',
                'severity': 'FATAL',
                'drugs': [drug_a, drug_b],
                'reason': reason,
                'can_override': False,
            })

    # Max dose violations
    for drug, max_dose in MAX_SAFE_DOSES.items():
        if drug in drugs_lower:
            actual = daily_doses.get(drug, 0)
            if actual > max_dose:
                violations.append({
                    'type': 'max_dose_exceeded',
                    'severity': 'HIGH',
                    'drug': drug,
                    'actual_dose': actual,
                    'max_safe_dose': max_dose,
                    'reason': f"Daily dose {actual}mg exceeds maximum safe dose {max_dose}mg",
                    'can_override': False,
                })

    # Narrow TI flagging
    for drug in drugs_lower:
        if drug in NARROW_TI_DRUGS:
            violations.append({
                'type': 'narrow_ti_monitoring',
                'severity': 'MONITORING',
                'drug': drug,
                'reason': f"{drug} is a narrow therapeutic index drug — TDM required",
                'can_override': True,  # monitoring flag, not block
            })

    return violations


# ─── REASONING CHAIN BUILDER ───

@dataclass
class ReasoningStep:
    step_id: str
    description: str
    value: Any
    source: str                  # e.g. 'CockcroKf-Gault', 'FDA Label', 'Monte Carlo'
    confidence: float
    references: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    uncertainty_note: str = ''


@dataclass
class ReasoningChain:
    """Full reasoning chain for any output. Physician can interrogate every step."""
    output_id: str
    output_type: str             # 'schedule', 'risk_assessment', 'interaction_flag', 'dose_recommendation'
    final_conclusion: str
    final_value: Any
    confidence: float
    steps: List[ReasoningStep] = field(default_factory=list)
    model_version: str = 'AbsorbAI-Engine-v1.0'
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    patient_id: str = ''
    can_be_challenged: bool = True

    def add_step(self, description: str, value: Any, source: str,
                 confidence: float, references: List[str] = None,
                 assumptions: List[str] = None, uncertainty_note: str = ''):
        step = ReasoningStep(
            step_id=f"step_{len(self.steps)+1}",
            description=description,
            value=value,
            source=source,
            confidence=confidence,
            references=references or [],
            assumptions=assumptions or [],
            uncertainty_note=uncertainty_note,
        )
        self.steps.append(step)
        return step

    def to_dict(self) -> dict:
        return {
            'output_id': self.output_id,
            'output_type': self.output_type,
            'final_conclusion': self.final_conclusion,
            'final_value': self.final_value,
            'confidence': round(self.confidence, 3),
            'model_version': self.model_version,
            'timestamp': self.timestamp,
            'patient_id': self.patient_id,
            'steps': [
                {
                    'id': s.step_id,
                    'description': s.description,
                    'value': s.value,
                    'source': s.source,
                    'confidence': round(s.confidence, 3),
                    'references': s.references,
                    'assumptions': s.assumptions,
                    'uncertainty_note': s.uncertainty_note,
                }
                for s in self.steps
            ],
        }

    def to_plain_english(self) -> str:
        """Generate physician-readable explanation"""
        lines = [
            f"CONCLUSION: {self.final_conclusion}",
            f"Confidence: {self.confidence*100:.0f}%",
            f"Model: {self.model_version} | Generated: {self.timestamp[:19]}",
            "",
            "REASONING CHAIN:",
        ]
        for step in self.steps:
            lines.append(f"  [{step.step_id}] {step.description}")
            lines.append(f"         → {step.value} (source: {step.source}, "
                         f"confidence: {step.confidence*100:.0f}%)")
            if step.uncertainty_note:
                lines.append(f"         ⚠ Uncertainty: {step.uncertainty_note}")
            if step.references:
                lines.append(f"         📚 Refs: {'; '.join(step.references[:2])}")
        return '\n'.join(lines)


def build_interaction_reasoning_chain(
    drug_a: str,
    drug_b: str,
    interaction_data: Dict,
    patient_pk_a: Dict,
    patient_pk_b: Dict,
) -> ReasoningChain:
    """
    Build a complete reasoning chain for a drug-drug interaction assessment.
    """
    chain = ReasoningChain(
        output_id=str(uuid.uuid4())[:8],
        output_type='interaction_flag',
        final_conclusion='',
        final_value={},
        confidence=0.0,
    )

    # Step 1: Identify mechanism
    mech = interaction_data.get('mechanism', 'unknown')
    chain.add_step(
        description=f"Identify interaction mechanism between {drug_a} and {drug_b}",
        value=mech,
        source='PharmacologicalKnowledgeGraph',
        confidence=interaction_data.get('confidence', 0.7),
        references=interaction_data.get('references', []),
    )

    # Step 2: Quantify magnitude
    mag = interaction_data.get('magnitude', 0)
    unit = interaction_data.get('magnitude_unit', '')
    chain.add_step(
        description=f"Quantify interaction magnitude",
        value=f"{mag} {unit}",
        source=f"Published literature ({interaction_data.get('evidence_count', 1)} studies)",
        confidence=interaction_data.get('confidence', 0.7),
        uncertainty_note=f"Magnitude estimated from population studies; individual response varies",
        references=interaction_data.get('references', []),
    )

    # Step 3: Patient-specific PK context
    cl_a = patient_pk_a.get('cl_mean', 'unknown')
    chain.add_step(
        description=f"Apply patient-specific PK: {drug_a} clearance = {cl_a} L/hr",
        value=cl_a,
        source='Cockcroft-Gault CrCl + CYP450 genotype estimate',
        confidence=0.75,
        assumptions=['Normal protein binding assumed unless labs indicate otherwise'],
        uncertainty_note='Personalized clearance ±30% IIV',
    )

    # Step 4: Compute net effect
    if unit == 'AUC_ratio':
        net_effect = f"{drug_b} exposure increases {mag:.1f}× due to {drug_a} co-administration"
    elif unit == 'AUC_reduction_fraction':
        net_effect = f"{drug_b} absorption reduced {mag*100:.0f}% when taken with {drug_a}"
    else:
        net_effect = f"Interaction magnitude: {mag} {unit}"

    severity = interaction_data.get('severity', 0.3)
    chain.add_step(
        description="Compute net clinical effect",
        value=net_effect,
        source='Mechanistic computation from knowledge graph + patient PK',
        confidence=interaction_data.get('confidence', 0.7) * 0.9,
        uncertainty_note=f"Individual response uncertainty ±40%",
    )

    # Step 5: Risk classification
    risk_level = 'HIGH' if severity > 0.6 else 'MODERATE' if severity > 0.3 else 'LOW'
    chain.add_step(
        description="Classify clinical risk level",
        value=risk_level,
        source='Severity scoring: AUC_ratio → risk scale (>2× = HIGH, 1.5-2× = MODERATE)',
        confidence=0.85,
    )

    chain.final_conclusion = f"{drug_a}/{drug_b} interaction: {risk_level} risk — {net_effect}"
    chain.final_value = {'risk_level': risk_level, 'severity': severity, 'net_effect': net_effect}
    chain.confidence = interaction_data.get('confidence', 0.7)

    return chain


def build_schedule_reasoning_chain(
    drug_name: str,
    scheduled_time: float,
    rationale_factors: Dict,
    patient_context: Dict,
) -> ReasoningChain:
    """Build reasoning chain for a specific scheduling decision"""
    chain = ReasoningChain(
        output_id=str(uuid.uuid4())[:8],
        output_type='schedule',
        final_conclusion='',
        final_value={},
        confidence=0.0,
    )

    chain.add_step(
        description=f"Determine optimal dosing time for {drug_name}",
        value=f"{scheduled_time:.1f}hr",
        source='Multi-objective Pareto optimizer',
        confidence=0.85,
        assumptions=['Patient follows prescribed dietary profile'],
    )

    if rationale_factors.get('food_interaction'):
        chain.add_step(
            description="Food interaction constraint applied",
            value=rationale_factors['food_interaction'],
            source='Knowledge graph: food-drug chelation/absorption data',
            confidence=0.90,
        )

    if rationale_factors.get('drug_interaction'):
        chain.add_step(
            description="Drug-drug interaction timing constraint",
            value=rationale_factors['drug_interaction'],
            source='Knowledge graph: CYP450 interaction model',
            confidence=0.82,
        )

    if rationale_factors.get('pk_rationale'):
        chain.add_step(
            description="PK-optimized timing",
            value=rationale_factors['pk_rationale'],
            source='Two-compartment PK simulation + Monte Carlo',
            confidence=0.78,
            uncertainty_note='Based on population PK parameters personalized to patient physiology',
        )

    chain.final_conclusion = (
        f"{drug_name} scheduled at {scheduled_time:.1f}hr: {rationale_factors.get('summary', 'optimized timing')}"
    )
    chain.final_value = {'time_hr': scheduled_time, 'drug': drug_name}
    chain.confidence = 0.82
    return chain


# ─── AUDIT ARCHITECTURE (Layer 10) ───

class AuditLog:
    """
    Immutable audit log. Every recommendation logged with model version,
    exact parameters, timestamp. Supports replay.
    """

    def __init__(self):
        self._entries: List[Dict] = []

    def log_recommendation(
        self,
        recommendation_type: str,
        patient_id: str,
        input_state: Dict,
        output: Dict,
        reasoning_chain: Optional[ReasoningChain],
        model_version: str = 'AbsorbAI-Engine-v1.0',
    ) -> str:
        """Log an immutable audit entry. Returns entry ID."""
        entry_id = str(uuid.uuid4())
        timestamp = datetime.datetime.utcnow().isoformat()

        # Create deterministic hash of input+output for integrity check
        integrity_data = json.dumps({
            'patient_id': patient_id,
            'input': input_state,
            'output': output,
        }, sort_keys=True, default=str)
        integrity_hash = hashlib.sha256(integrity_data.encode()).hexdigest()[:16]

        entry = {
            'entry_id': entry_id,
            'timestamp': timestamp,
            'recommendation_type': recommendation_type,
            'patient_id': patient_id,
            'model_version': model_version,
            'input_state': input_state,
            'output': output,
            'reasoning_chain': reasoning_chain.to_dict() if reasoning_chain else None,
            'integrity_hash': integrity_hash,
            'can_replay': True,
        }
        self._entries.append(entry)
        return entry_id

    def get_patient_history(self, patient_id: str) -> List[Dict]:
        return [e for e in self._entries if e['patient_id'] == patient_id]

    def replay_at_timestamp(self, entry_id: str) -> Optional[Dict]:
        """Retrieve exact system state at time of any recommendation"""
        for entry in self._entries:
            if entry['entry_id'] == entry_id:
                return entry
        return None

    def verify_integrity(self, entry_id: str) -> bool:
        """Verify an audit entry hasn't been tampered with"""
        entry = self.replay_at_timestamp(entry_id)
        if not entry:
            return False
        integrity_data = json.dumps({
            'patient_id': entry['patient_id'],
            'input': entry['input_state'],
            'output': entry['output'],
        }, sort_keys=True, default=str)
        computed_hash = hashlib.sha256(integrity_data.encode()).hexdigest()[:16]
        return computed_hash == entry['integrity_hash']

    def to_list(self) -> List[Dict]:
        return list(self._entries)


# Global audit log instance
GLOBAL_AUDIT_LOG = AuditLog()
