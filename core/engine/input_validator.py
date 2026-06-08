"""
Input Validation & Data Quality Layer for AbsorbAI.

Clamps physiological values to medically plausible ranges,
computes a data_confidence_score (0–1), and scales Monte Carlo
variance proportionally to input uncertainty.

A score of 1.0 = all values present and plausible.
A score of 0.0 = critically implausible / missing inputs → engine
should refuse or widen uncertainty dramatically.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Any, Optional

# ── Physiological plausibility bounds ────────────────────────────────────────
# (hard_min, soft_min, soft_max, hard_max)
# hard = clamp; soft = flag as suspicious (lowers confidence)
PHYSIO_BOUNDS = {
    'age':                (0,    1,    110,  130),
    'weight':             (1,    3,    250,  500),     # kg
    'height':             (40,   50,   220,  260),     # cm
    'serum_creatinine':   (0.1,  0.3,  15.0, 20.0),   # mg/dL
    'child_pugh_score':   (5,    5,    15,   15),
    'body_fat_pct':       (2,    4,    60,   70),      # %
    'plasma_albumin':     (0.5,  2.0,  5.5,  6.0),    # g/dL
    'gut_motility_score': (0.1,  0.3,  2.0,  3.0),
    'hydration_score':    (0.3,  0.5,  1.3,  1.5),
    'cyp3a4_activity':    (0.05, 0.1,  3.0,  4.0),
    'cyp2d6_activity':    (0.05, 0.1,  3.0,  4.0),
    'cyp2c9_activity':    (0.05, 0.1,  3.0,  4.0),
    'cyp2c19_activity':   (0.05, 0.1,  3.0,  4.0),
    'cyp1a2_activity':    (0.05, 0.1,  3.0,  4.0),
    'cyp2e1_activity':    (0.05, 0.1,  3.0,  4.0),
}

DOSE_BOUNDS = {
    # drug_key: (hard_min_mg, hard_max_single_dose_mg)
    # hard_max per single dose — not daily dose
    'warfarin':         (0.5,    15.0),
    'digoxin':          (0.0625,  0.5),
    'levothyroxine':    (12.5,  300.0),
    'lithium':          (150,  1200.0),
    'phenytoin':        (25,    500.0),
    'methotrexate':     (2.5,   100.0),
    'amiodarone':       (50,    400.0),
    'cyclosporine':     (10,    500.0),
    '_default':         (0.1,  5000.0),
}

# Fields considered mandatory for reliable simulation
MANDATORY_FIELDS = {'age', 'weight', 'height', 'sex'}
# Fields that improve confidence but aren't mandatory
OPTIONAL_FIELDS  = {
    'serum_creatinine', 'child_pugh_score', 'body_fat_pct',
    'plasma_albumin', 'cyp3a4_activity', 'cyp2d6_activity',
    'cyp2c9_activity', 'cyp2c19_activity',
}


@dataclass
class ValidationResult:
    """Result of input validation."""
    cleaned_profile: Dict[str, Any]
    cleaned_prescriptions: List[Dict]
    data_confidence: float          # 0.0–1.0
    mc_multiplier: float            # multiply n_monte_carlo by this
    warnings: List[Dict]            # [{field, issue, severity}]
    errors: List[Dict]              # hard blockers
    is_safe_to_simulate: bool

    def to_dict(self) -> Dict:
        return {
            'data_confidence': round(self.data_confidence, 3),
            'mc_multiplier':   round(self.mc_multiplier, 2),
            'warnings':        self.warnings,
            'errors':          self.errors,
            'is_safe_to_simulate': self.is_safe_to_simulate,
        }


def _clamp(value: float, hard_min: float, hard_max: float) -> float:
    return max(hard_min, min(hard_max, value))


def validate_and_sanitize(
    patient_profile: Dict,
    prescriptions: List[Dict],
) -> ValidationResult:
    """
    Main entry point.  Mutates nothing — returns cleaned copies.
    """
    warnings: List[Dict] = []
    errors:   List[Dict] = []
    profile   = dict(patient_profile)
    rxs       = [dict(r) for r in prescriptions]

    # ── 1. Mandatory field presence ───────────────────────────────────────────
    missing_mandatory = [f for f in MANDATORY_FIELDS if f not in profile or profile[f] is None]
    if missing_mandatory:
        errors.append({
            'field':    ', '.join(missing_mandatory),
            'issue':    'Missing mandatory physiological fields',
            'severity': 'error',
        })

    # ── 2. Sex normalisation ──────────────────────────────────────────────────
    sex = str(profile.get('sex', 'M')).upper().strip()
    if sex not in ('M', 'F'):
        sex = 'M'
        warnings.append({'field': 'sex', 'issue': 'Unrecognised sex value; defaulted to M', 'severity': 'warn'})
    profile['sex'] = sex

    # ── 3. Numeric clamping + suspicion scoring ───────────────────────────────
    suspicion_penalties = 0.0
    total_checks = len(PHYSIO_BOUNDS)

    for field_name, (hard_min, soft_min, soft_max, hard_max) in PHYSIO_BOUNDS.items():
        raw = profile.get(field_name)
        if raw is None:
            # Missing optional field — small confidence penalty
            if field_name in OPTIONAL_FIELDS:
                suspicion_penalties += 0.05
            continue

        try:
            val = float(raw)
        except (TypeError, ValueError):
            warnings.append({
                'field':    field_name,
                'issue':    f'Non-numeric value {repr(raw)}; using default',
                'severity': 'warn',
            })
            profile.pop(field_name, None)
            suspicion_penalties += 0.08
            continue

        # Hard clamp
        clamped = _clamp(val, hard_min, hard_max)
        if clamped != val:
            warnings.append({
                'field':    field_name,
                'issue':    f'Value {val} outside hard bounds [{hard_min}, {hard_max}]; clamped',
                'severity': 'warn',
            })
            suspicion_penalties += 0.12

        # Soft suspicion (value in hard range but unusual)
        elif val < soft_min or val > soft_max:
            warnings.append({
                'field':    field_name,
                'issue':    f'Value {val} is physiologically unusual (expected {soft_min}–{soft_max})',
                'severity': 'info',
            })
            suspicion_penalties += 0.06

        profile[field_name] = clamped

    # ── 4. Logical cross-checks ───────────────────────────────────────────────
    age    = float(profile.get('age',    45))
    weight = float(profile.get('weight', 70))
    height = float(profile.get('height', 170))

    bmi = weight / (height / 100) ** 2
    if bmi < 10 or bmi > 70:
        warnings.append({
            'field':    'weight/height',
            'issue':    f'Implausible BMI {bmi:.1f} from weight={weight}kg height={height}cm',
            'severity': 'warn',
        })
        suspicion_penalties += 0.15

    # Paediatric flag (affects PK significantly — widen uncertainty)
    if age < 18:
        warnings.append({
            'field':    'age',
            'issue':    f'Patient is paediatric (age={age}); population PK params are adult-derived — uncertainty widened',
            'severity': 'warn',
        })
        suspicion_penalties += 0.20

    # Elderly flag
    if age > 75:
        warnings.append({
            'field':    'age',
            'issue':    f'Elderly patient (age={age}); increased PK variability expected',
            'severity': 'info',
        })
        suspicion_penalties += 0.08

    # ── 5. Prescription validation ────────────────────────────────────────────
    for i, rx in enumerate(rxs):
        drug = str(rx.get('drug_name', '')).strip().lower()
        if not drug:
            errors.append({'field': f'rx[{i}].drug_name', 'issue': 'Empty drug name', 'severity': 'error'})
            continue

        # Dose bounds
        raw_dose = rx.get('dose_mg')
        if raw_dose is None or raw_dose == '':
            warnings.append({'field': f'{drug}.dose_mg', 'issue': 'Missing dose; using 100mg default', 'severity': 'warn'})
            rx['dose_mg'] = 100.0
            suspicion_penalties += 0.10
        else:
            try:
                dose = float(raw_dose)
            except (TypeError, ValueError):
                errors.append({'field': f'{drug}.dose_mg', 'issue': f'Non-numeric dose {repr(raw_dose)}', 'severity': 'error'})
                continue

            bounds = DOSE_BOUNDS.get(drug, DOSE_BOUNDS['_default'])
            hard_min_d, hard_max_d = bounds
            clamped_dose = _clamp(dose, hard_min_d, hard_max_d)
            if clamped_dose != dose:
                warnings.append({
                    'field':    f'{drug}.dose_mg',
                    'issue':    f'Dose {dose}mg clamped to [{hard_min_d}, {hard_max_d}]mg',
                    'severity': 'warn',
                })
                suspicion_penalties += 0.12
            rx['dose_mg'] = clamped_dose

        # Frequency bounds
        freq = rx.get('frequency_per_day', 1)
        try:
            freq = int(freq)
        except (TypeError, ValueError):
            freq = 1
        rx['frequency_per_day'] = _clamp(freq, 1, 8)

        # Timing bounds (0–24 hr)
        t = rx.get('start_time_hr', 8.0)
        try:
            rx['start_time_hr'] = float(t) % 24.0
        except (TypeError, ValueError):
            rx['start_time_hr'] = 8.0

        # Bioavailability
        f = rx.get('bioavailability', 0.8)
        try:
            rx['bioavailability'] = _clamp(float(f), 0.01, 1.0)
        except (TypeError, ValueError):
            rx['bioavailability'] = 0.8

        rx['drug_name'] = drug  # normalise to lowercase

    # ── 6. Data confidence score ──────────────────────────────────────────────
    # Base confidence from mandatory field presence
    mandatory_present = len(MANDATORY_FIELDS) - len(missing_mandatory)
    base_confidence   = mandatory_present / len(MANDATORY_FIELDS)

    # Optional field bonus
    optional_present = sum(1 for f in OPTIONAL_FIELDS if f in profile and profile[f] is not None)
    optional_bonus   = (optional_present / len(OPTIONAL_FIELDS)) * 0.25  # max +0.25

    # Penalty from suspicion events
    penalty = min(suspicion_penalties, 0.80)

    confidence = max(0.0, min(1.0, base_confidence * 0.75 + optional_bonus - penalty))

    # ── 7. MC multiplier — widen simulation when data is uncertain ────────────
    # confidence=1.0 → multiplier=1.0 (use requested n)
    # confidence=0.5 → multiplier=1.5 (50% more samples to capture wider dist)
    # confidence=0.2 → multiplier=2.5
    mc_multiplier = 1.0 + (1.0 - confidence) * 2.0

    # ── 8. Safe-to-simulate gate ──────────────────────────────────────────────
    is_safe = len(errors) == 0 and len(rxs) > 0 and confidence > 0.15

    return ValidationResult(
        cleaned_profile=profile,
        cleaned_prescriptions=rxs,
        data_confidence=confidence,
        mc_multiplier=mc_multiplier,
        warnings=warnings,
        errors=errors,
        is_safe_to_simulate=is_safe,
    )


def confidence_to_uncertainty_scale(confidence: float) -> float:
    """
    Returns a multiplier for PK std deviations.
    Low confidence → wider parameter distributions in Monte Carlo.
    confidence=1.0 → scale=1.0 (no extra widening)
    confidence=0.5 → scale=1.4
    confidence=0.2 → scale=2.0
    """
    return 1.0 + (1.0 - confidence) * 1.5
