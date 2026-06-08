"""
Layer 1: Biological Twin Engine
Personalized pharmacokinetic parameter calculation from patient physiology.
All parameters are distributions, not point estimates.
"""
import math
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

try:
    from ..drugdb.drug_data import EXTENDED_POPULATION_PK as _EXT_PK
except ImportError:
    _EXT_PK = {}


@dataclass
class PatientPhysiology:
    age: float           # years
    weight: float        # kg
    height: float        # cm
    sex: str             # 'M' or 'F'
    serum_creatinine: float = 1.0    # mg/dL
    child_pugh_score: int = 5        # 5-6=A, 7-9=B, 10-15=C
    body_fat_pct: float = 20.0       # percent
    plasma_albumin: float = 4.0      # g/dL (normal 3.5-5.0)
    gut_motility_score: float = 1.0  # 0.5=slow, 1.0=normal, 1.5=fast
    hydration_score: float = 1.0     # 0.7=dehydrated, 1.0=normal, 1.1=overhydrated
    is_sick: bool = False
    alcohol_last_24h: bool = False
    # CYP450 genotype multipliers (1.0=normal, 0.5=PM, 1.5=UM)
    cyp3a4_activity: float = 1.0
    cyp2d6_activity: float = 1.0
    cyp2c9_activity: float = 1.0
    cyp2c19_activity: float = 1.0
    cyp1a2_activity: float = 1.0
    cyp2e1_activity: float = 1.0

    def bmi(self) -> float:
        h_m = self.height / 100.0
        return self.weight / (h_m ** 2)

    def bsa(self) -> float:
        """Mosteller BSA formula"""
        return math.sqrt((self.height * self.weight) / 3600.0)

    def ibw(self) -> float:
        """Ideal body weight (Devine formula)"""
        h_over_5ft = (self.height / 2.54) - 60
        if self.sex == 'M':
            return 50 + 2.3 * h_over_5ft
        return 45.5 + 2.3 * h_over_5ft

    def lean_body_weight(self) -> float:
        """James formula LBW"""
        if self.sex == 'M':
            return 1.1 * self.weight - 128 * (self.weight / self.height) ** 2
        return 1.07 * self.weight - 148 * (self.weight / self.height) ** 2

    def creatinine_clearance(self) -> float:
        """Cockcroft-Gault CrCl in mL/min"""
        base = ((140 - self.age) * self.weight) / (72 * self.serum_creatinine)
        if self.sex == 'F':
            base *= 0.85
        # Sickness reduces renal clearance ~20%
        if self.is_sick:
            base *= 0.80
        # Dehydration reduces renal clearance
        base *= self.hydration_score
        return max(base, 10.0)  # floor at 10 mL/min

    def hepatic_function_factor(self) -> float:
        """0.0=severe impairment, 1.0=normal (from Child-Pugh)"""
        if self.child_pugh_score <= 6:
            return 1.0
        elif self.child_pugh_score <= 9:
            return 0.65
        return 0.35

    def free_drug_fraction_modifier(self) -> float:
        """Albumin affects protein binding; low albumin = more free drug"""
        normal_albumin = 4.0
        return normal_albumin / max(self.plasma_albumin, 1.5)

    def effective_cyp3a4(self) -> float:
        factor = self.cyp3a4_activity
        if self.alcohol_last_24h:
            factor *= 0.85  # acute alcohol mildly inhibits CYP3A4
        if self.is_sick:
            factor *= 0.90
        return factor

    def effective_cyp2e1(self) -> float:
        factor = self.cyp2e1_activity
        if self.alcohol_last_24h:
            factor *= 0.5  # acute alcohol strongly inhibits CYP2E1
        return factor


@dataclass
class PersonalizedPKParams:
    """Personalized PK parameters as (mean, std) tuples — distributions, not point estimates"""
    drug_name: str
    patient_id: str

    # Volume of distribution L (central)
    vd_central_mean: float = 20.0
    vd_central_std: float = 4.0
    # Peripheral compartment
    vd_peripheral_mean: float = 40.0
    vd_peripheral_std: float = 10.0
    # Clearance L/hr
    cl_mean: float = 5.0
    cl_std: float = 1.5
    # Inter-compartmental clearance
    q_mean: float = 2.0
    q_std: float = 0.5
    # Absorption rate constant 1/hr
    ka_mean: float = 1.0
    ka_std: float = 0.3
    # Bioavailability fraction
    f_mean: float = 0.85
    f_std: float = 0.08
    # Derived
    half_life_mean: float = field(init=False)
    half_life_std: float = field(init=False)

    def __post_init__(self):
        self.half_life_mean = 0.693 * self.vd_central_mean / self.cl_mean
        self.half_life_std = self.half_life_mean * math.sqrt(
            (self.vd_central_std / self.vd_central_mean) ** 2 +
            (self.cl_std / self.cl_mean) ** 2
        )


# Population PK base parameters per drug (two-compartment model)
# Values from published popPK literature
POPULATION_PK = {
    'warfarin': {
        'vd_central': (4.3, 0.8),    # L/kg → scaled by weight
        'vd_peripheral': (9.0, 2.0),
        'cl_base': (0.048, 0.012),   # L/hr/kg
        'q': (0.6, 0.15),
        'ka': (0.9, 0.25),
        'f': (0.93, 0.05),
        'primary_enzyme': 'cyp2c9',
        'renal_fraction': 0.02,
        'protein_binding': 0.99,
    },
    'levothyroxine': {
        'vd_central': (5.5, 1.2),
        'vd_peripheral': (14.0, 3.5),
        'cl_base': (0.006, 0.002),
        'q': (0.3, 0.08),
        'ka': (0.4, 0.12),
        'f': (0.75, 0.12),
        'primary_enzyme': None,
        'renal_fraction': 0.0,
        'protein_binding': 0.999,
    },
    'amlodipine': {
        'vd_central': (12.0, 3.0),
        'vd_peripheral': (60.0, 15.0),
        'cl_base': (0.10, 0.03),
        'q': (1.8, 0.5),
        'ka': (0.35, 0.10),
        'f': (0.64, 0.10),
        'primary_enzyme': 'cyp3a4',
        'renal_fraction': 0.03,
        'protein_binding': 0.97,
    },
    'metformin': {
        'vd_central': (3.0, 0.8),
        'vd_peripheral': (8.0, 2.5),
        'cl_base': (0.21, 0.06),
        'q': (1.2, 0.4),
        'ka': (0.55, 0.18),
        'f': (0.55, 0.10),
        'primary_enzyme': None,
        'renal_fraction': 0.90,
        'protein_binding': 0.0,
    },
    'digoxin': {
        'vd_central': (3.5, 1.0),
        'vd_peripheral': (30.0, 8.0),
        'cl_base': (0.088, 0.020),
        'q': (1.5, 0.4),
        'ka': (0.6, 0.18),
        'f': (0.70, 0.10),
        'primary_enzyme': None,
        'renal_fraction': 0.70,
        'protein_binding': 0.25,
    },
    'atorvastatin': {
        'vd_central': (8.0, 2.5),
        'vd_peripheral': (25.0, 8.0),
        'cl_base': (0.15, 0.05),
        'q': (1.2, 0.4),
        'ka': (0.7, 0.2),
        'f': (0.12, 0.04),
        'primary_enzyme': 'cyp3a4',
        'renal_fraction': 0.02,
        'protein_binding': 0.98,
    },
    'omeprazole': {
        'vd_central': (3.0, 0.8),
        'vd_peripheral': (6.5, 2.0),
        'cl_base': (0.30, 0.10),
        'q': (0.8, 0.25),
        'ka': (1.2, 0.35),
        'f': (0.53, 0.12),
        'primary_enzyme': 'cyp2c19',
        'renal_fraction': 0.01,
        'protein_binding': 0.97,
    },
    'lisinopril': {
        'vd_central': (5.0, 1.5),
        'vd_peripheral': (12.0, 3.5),
        'cl_base': (0.15, 0.04),
        'q': (0.9, 0.3),
        'ka': (0.4, 0.12),
        'f': (0.25, 0.08),
        'primary_enzyme': None,
        'renal_fraction': 0.90,
        'protein_binding': 0.0,
    },
}

# Merge extended PK params from drug database (non-destructive — base dict takes priority)
POPULATION_PK.update({k: v for k, v in _EXT_PK.items() if k not in POPULATION_PK})


def personalize_pk(drug_name: str, patient: PatientPhysiology, patient_id: str,
                   concurrent_inhibitors: dict = None) -> PersonalizedPKParams:
    """
    Compute personalized PK parameters from patient physiology.
    concurrent_inhibitors: {enzyme: inhibition_fraction} e.g. {'cyp3a4': 0.6}
    """
    drug_key = drug_name.lower()
    pop = POPULATION_PK.get(drug_key)
    if not pop:
        # Generic defaults with wide uncertainty
        pop = {
            'vd_central': (5.0, 2.0),
            'vd_peripheral': (15.0, 6.0),
            'cl_base': (0.10, 0.04),
            'q': (1.0, 0.4),
            'ka': (0.7, 0.25),
            'f': (0.70, 0.15),
            'primary_enzyme': None,
            'renal_fraction': 0.30,
            'protein_binding': 0.50,
        }

    w = patient.weight
    crcl = patient.creatinine_clearance()
    hep = patient.hepatic_function_factor()
    alb_mod = patient.free_drug_fraction_modifier()
    fat_fraction = patient.body_fat_pct / 100.0

    # Scale Vd by weight and body composition
    # Lipophilic drugs partition into fat; hydrophilic use lean weight
    vd_c_mean, vd_c_std = pop['vd_central']
    vd_p_mean, vd_p_std = pop['vd_peripheral']

    # Adipose partitioning scales peripheral Vd
    fat_scale = 1.0 + (fat_fraction - 0.20) * 0.8  # ±40% per 50% fat change
    vd_central = vd_c_mean * w * (1.0 + alb_mod * pop['protein_binding'] * 0.05)
    vd_central_std = vd_c_std * w
    vd_peripheral = vd_p_mean * w * fat_scale
    vd_peripheral_std = vd_p_std * w * fat_scale

    # Clearance: metabolic + renal components
    cl_base_mean, cl_base_std = pop['cl_base']
    renal_frac = pop['renal_fraction']
    enzyme = pop.get('primary_enzyme')

    # Enzyme activity factor
    enz_activity = 1.0
    if enzyme == 'cyp3a4':
        enz_activity = patient.effective_cyp3a4()
    elif enzyme == 'cyp2d6':
        enz_activity = patient.cyp2d6_activity
    elif enzyme == 'cyp2c9':
        enz_activity = patient.cyp2c9_activity
    elif enzyme == 'cyp2c19':
        enz_activity = patient.cyp2c19_activity
    elif enzyme == 'cyp1a2':
        enz_activity = patient.cyp1a2_activity
    elif enzyme == 'cyp2e1':
        enz_activity = patient.effective_cyp2e1()

    # Apply concurrent drug inhibition
    if concurrent_inhibitors and enzyme:
        inhibition = concurrent_inhibitors.get(enzyme, 0.0)
        enz_activity *= (1.0 - inhibition)

    # Hepatic clearance component
    cl_hepatic = cl_base_mean * w * (1 - renal_frac) * hep * enz_activity
    # Renal clearance component — scales with CrCl (normal ~100 mL/min)
    cl_renal = cl_base_mean * w * renal_frac * (crcl / 100.0) * patient.hydration_score
    cl_mean = cl_hepatic + cl_renal
    cl_std = cl_base_std * w * math.sqrt(
        ((1 - renal_frac) * hep * enz_activity) ** 2 +
        (renal_frac * crcl / 100.0) ** 2
    ) * 1.5  # extra IIV uncertainty

    # Bioavailability: gut motility affects absorption extent
    f_mean, f_std = pop['f']
    f_personalized = f_mean * patient.gut_motility_score * hep
    f_personalized = min(max(f_personalized, 0.05), 1.0)
    f_std_pers = max(f_std * 1.2, 0.04)

    # ka: gut motility affects absorption rate
    ka_mean, ka_std = pop['ka']
    ka_pers = ka_mean * patient.gut_motility_score
    if patient.is_sick:
        ka_pers *= 0.75
        f_personalized *= 0.90

    q_mean, q_std = pop['q']
    q_pers = q_mean * (w / 70.0) ** 0.75  # allometric scaling

    params = PersonalizedPKParams(
        drug_name=drug_name,
        patient_id=patient_id,
        vd_central_mean=max(vd_central, 0.5),
        vd_central_std=max(vd_central_std, 0.1),
        vd_peripheral_mean=max(vd_peripheral, 1.0),
        vd_peripheral_std=max(vd_peripheral_std, 0.2),
        cl_mean=max(cl_mean, 0.01),
        cl_std=max(cl_std, 0.005),
        q_mean=max(q_pers, 0.05),
        q_std=max(q_std, 0.01),
        ka_mean=max(ka_pers, 0.05),
        ka_std=max(ka_std, 0.01),
        f_mean=f_personalized,
        f_std=f_std_pers,
    )
    return params
