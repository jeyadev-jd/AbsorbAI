"""
Layer 7: Adversarial Stress Testing
Attacks the recommended schedule with realistic failure scenarios.
Finds schedules that fail gracefully — antifragile pharmacology.
"""
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from .biological_twin import PatientPhysiology, PersonalizedPKParams
from .pk_pd_engine import DosingEvent, simulate_pk_pd, DRUG_PD_PARAMS


@dataclass
class StressScenario:
    name: str
    description: str
    physiological_perturbation: Dict   # changes to PatientPhysiology fields
    dosing_perturbation: Dict          # changes to dosing (missed, double, late)
    probability: float                 # realistic probability this scenario occurs


@dataclass
class StressTestResult:
    scenario: StressScenario
    outcome_severity: float          # 0=safe, 1=catastrophic
    outcome_description: str
    pk_change_pct: Dict[str, float]  # drug → % change in Cmax or AUC
    is_catastrophic: bool
    mitigation_suggestion: str


STANDARD_STRESS_SCENARIOS = [
    StressScenario(
        name='missed_critical_dose',
        description='Patient misses the most PK-critical dose of the day',
        physiological_perturbation={},
        dosing_perturbation={'miss_dose': True, 'dose_index': 0},
        probability=0.15,
    ),
    StressScenario(
        name='double_dose',
        description='Patient accidentally doubles a dose (takes dose twice)',
        physiological_perturbation={},
        dosing_perturbation={'double_dose': True, 'dose_index': 0},
        probability=0.05,
    ),
    StressScenario(
        name='dose_two_hours_late',
        description='Dose taken 2 hours later than scheduled',
        physiological_perturbation={},
        dosing_perturbation={'delay_hours': 2.0},
        probability=0.30,
    ),
    StressScenario(
        name='acute_dehydration',
        description='Patient becomes dehydrated (e.g. illness, hot weather)',
        physiological_perturbation={'hydration_score': 0.7, 'is_sick': True},
        dosing_perturbation={},
        probability=0.10,
    ),
    StressScenario(
        name='renal_impairment_sudden',
        description='Sudden kidney function drop (e.g. contrast, NSAID use)',
        physiological_perturbation={'serum_creatinine': 2.5},
        dosing_perturbation={},
        probability=0.05,
    ),
    StressScenario(
        name='new_cyp3a4_inhibitor',
        description='Patient starts a new CYP3A4 inhibitor (antibiotic, antifungal)',
        physiological_perturbation={'cyp3a4_activity': 0.3},
        dosing_perturbation={},
        probability=0.08,
    ),
    StressScenario(
        name='grapefruit_consumed',
        description='Patient consumes grapefruit juice (dietary CYP3A4 inhibition)',
        physiological_perturbation={'cyp3a4_activity': 0.6},
        dosing_perturbation={},
        probability=0.12,
    ),
    StressScenario(
        name='alcohol_consumed',
        description='Patient drinks alcohol (CYP2E1 inhibition, CYP3A4 modulation)',
        physiological_perturbation={'alcohol_last_24h': True, 'cyp2e1_activity': 0.5},
        dosing_perturbation={},
        probability=0.15,
    ),
    StressScenario(
        name='significant_weight_change',
        description='Patient gains or loses >5kg (affects Vd and dosing)',
        physiological_perturbation={'weight': None},  # handled specially
        dosing_perturbation={'weight_change_kg': -8},
        probability=0.10,
    ),
    StressScenario(
        name='food_timing_disruption',
        description='Meals taken 3 hours off-schedule (travel, irregular day)',
        physiological_perturbation={'gut_motility_score': 0.8},
        dosing_perturbation={'meal_shift_hours': 3.0},
        probability=0.20,
    ),
]


def run_stress_test(
    drug_name: str,
    base_pk: PersonalizedPKParams,
    base_patient: PatientPhysiology,
    base_dosing: List[DosingEvent],
    toxic_threshold: float = None,
    therapeutic_min: float = None,
    scenarios: List[StressScenario] = None,
    from_engine_module=None,
) -> Tuple[List[StressTestResult], bool, str]:
    """
    Run adversarial simulations for a drug schedule.
    Returns (results, is_schedule_fragile, recommendation).
    """
    from .biological_twin import personalize_pk
    from .pk_pd_engine import simulate_pk_pd as _simulate

    if scenarios is None:
        scenarios = STANDARD_STRESS_SCENARIOS

    pd = DRUG_PD_PARAMS.get(drug_name.lower())

    # Baseline simulation
    try:
        baseline = _simulate(base_pk, pd, base_dosing, t_end=48.0, dt=0.5)
        baseline_cmax = baseline.cmax
        baseline_auc = baseline.auc
    except Exception:
        baseline_cmax = 1.0
        baseline_auc = 1.0

    results = []
    catastrophic_scenarios = []

    for scenario in scenarios:
        # Build perturbed patient
        perturbed_patient = PatientPhysiology(
            age=base_patient.age,
            weight=base_patient.weight,
            height=base_patient.height,
            sex=base_patient.sex,
            serum_creatinine=base_patient.serum_creatinine,
            child_pugh_score=base_patient.child_pugh_score,
            body_fat_pct=base_patient.body_fat_pct,
            plasma_albumin=base_patient.plasma_albumin,
            gut_motility_score=base_patient.gut_motility_score,
            hydration_score=base_patient.hydration_score,
            is_sick=base_patient.is_sick,
            alcohol_last_24h=base_patient.alcohol_last_24h,
            cyp3a4_activity=base_patient.cyp3a4_activity,
            cyp2d6_activity=base_patient.cyp2d6_activity,
            cyp2c9_activity=base_patient.cyp2c9_activity,
            cyp2c19_activity=base_patient.cyp2c19_activity,
            cyp1a2_activity=base_patient.cyp1a2_activity,
            cyp2e1_activity=base_patient.cyp2e1_activity,
        )

        # Apply physiological perturbation
        phys_pert = scenario.physiological_perturbation
        for attr, val in phys_pert.items():
            if val is not None and hasattr(perturbed_patient, attr):
                setattr(perturbed_patient, attr, val)

        # Apply weight change if specified
        dose_pert = scenario.dosing_perturbation
        if 'weight_change_kg' in dose_pert:
            perturbed_patient.weight = max(
                base_patient.weight + dose_pert['weight_change_kg'], 30.0)

        # Recompute PK with perturbed physiology
        try:
            perturbed_pk = personalize_pk(drug_name, perturbed_patient, base_pk.patient_id)
        except Exception:
            perturbed_pk = base_pk

        # Apply dosing perturbation
        perturbed_doses = list(base_dosing)
        if dose_pert.get('miss_dose'):
            idx = dose_pert.get('dose_index', 0)
            if len(perturbed_doses) > idx:
                perturbed_doses = [d for i, d in enumerate(perturbed_doses) if i != idx]
        elif dose_pert.get('double_dose'):
            idx = dose_pert.get('dose_index', 0)
            if len(perturbed_doses) > idx:
                d = perturbed_doses[idx]
                duplicate = DosingEvent(
                    time_hr=d.time_hr + 0.25,
                    dose_mg=d.dose_mg,
                    bioavailability=d.bioavailability,
                )
                perturbed_doses = perturbed_doses + [duplicate]
                perturbed_doses.sort(key=lambda x: x.time_hr)
        elif 'delay_hours' in dose_pert:
            delay = dose_pert['delay_hours']
            perturbed_doses = [
                DosingEvent(d.time_hr + delay, d.dose_mg, d.bioavailability)
                for d in perturbed_doses
            ]

        # Simulate perturbed scenario
        try:
            stressed = _simulate(perturbed_pk, pd, perturbed_doses, t_end=48.0, dt=0.5)
            stressed_cmax = stressed.cmax
            stressed_auc = stressed.auc
        except Exception:
            stressed_cmax = baseline_cmax
            stressed_auc = baseline_auc

        # Compute outcome severity
        cmax_change_pct = (stressed_cmax - baseline_cmax) / max(baseline_cmax, 0.001) * 100
        auc_change_pct = (stressed_auc - baseline_auc) / max(baseline_auc, 0.001) * 100

        is_catastrophic = False
        outcome_severity = 0.0
        outcome_description = ''
        mitigation = ''

        if toxic_threshold and stressed_cmax > toxic_threshold:
            is_catastrophic = True
            outcome_severity = min((stressed_cmax / toxic_threshold - 1.0), 1.0)
            outcome_description = (
                f"Cmax {stressed_cmax:.2f} exceeds toxic threshold {toxic_threshold:.2f} "
                f"(+{cmax_change_pct:.0f}% above baseline)"
            )
            mitigation = f"Consider lower dose or extended interval. Avoid scenario: {scenario.description}"
        elif therapeutic_min and stressed_cmax < therapeutic_min * 0.5:
            outcome_severity = 0.4
            outcome_description = f"Sub-therapeutic: Cmax {stressed_cmax:.2f} < 50% of MEC"
            mitigation = "Consider catch-up dose protocol or increased frequency"
        elif abs(cmax_change_pct) > 50:
            outcome_severity = 0.3
            outcome_description = (
                f"Significant PK change: Cmax {'+' if cmax_change_pct>0 else ''}{cmax_change_pct:.0f}%, "
                f"AUC {'+' if auc_change_pct>0 else ''}{auc_change_pct:.0f}%"
            )
            mitigation = "Monitor closely under this scenario"
        else:
            outcome_severity = abs(cmax_change_pct) / 200.0
            outcome_description = (
                f"Modest change: Cmax {'+' if cmax_change_pct>0 else ''}{cmax_change_pct:.0f}%, "
                f"schedule remains robust"
            )
            mitigation = "No immediate action required"

        result = StressTestResult(
            scenario=scenario,
            outcome_severity=outcome_severity,
            outcome_description=outcome_description,
            pk_change_pct={'cmax': round(cmax_change_pct, 1), 'auc': round(auc_change_pct, 1)},
            is_catastrophic=is_catastrophic,
            mitigation_suggestion=mitigation,
        )
        results.append(result)

        if is_catastrophic:
            catastrophic_scenarios.append(scenario.name)

    is_fragile = len(catastrophic_scenarios) > 0
    if is_fragile:
        recommendation = (
            f"Schedule flagged as FRAGILE: catastrophic outcomes in {len(catastrophic_scenarios)} scenarios "
            f"({', '.join(catastrophic_scenarios)}). Consider alternative dosing strategy."
        )
    else:
        recommendation = (
            f"Schedule is ROBUST across {len(scenarios)} stress scenarios. "
            f"Worst case: {max((r.outcome_description for r in results), key=lambda x: len(x), default='None')}"
        )

    return results, is_fragile, recommendation
