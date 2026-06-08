"""
Layer 2: Full PK/PD Engine
Two-compartment PK with oral absorption, sigmoid Emax PD, tolerance, hysteresis.
Solves ODEs numerically using scipy.
"""
import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import interp1d
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from .biological_twin import PersonalizedPKParams


@dataclass
class DrugPDParams:
    """Pharmacodynamic parameters"""
    ec50: float          # concentration at 50% max effect (mg/L or ng/mL)
    emax: float          # maximum effect (0-1 normalized or effect units)
    gamma: float = 1.5   # Hill coefficient (steepness)
    e0: float = 0.0      # baseline effect
    # Effect compartment params (hysteresis)
    ke0: float = 0.0     # effect compartment equilibration rate (1/hr), 0=no effect compartment
    # Tolerance params
    tolerance_rate: float = 0.0     # rate of receptor downregulation (1/hr)
    tolerance_recovery: float = 0.0 # rate of receptor recovery (1/hr)
    # Irreversible inhibition (e.g. PPIs, aspirin)
    irreversible: bool = False
    synthesis_rate: float = 0.0     # enzyme/receptor synthesis rate (1/hr)


# PD parameters database
DRUG_PD_PARAMS = {
    'warfarin': DrugPDParams(
        ec50=1.5,    # mg/L plasma concentration
        emax=1.0,
        gamma=1.2,
        e0=0.0,
        ke0=0.0,
        tolerance_rate=0.0,
    ),
    'amlodipine': DrugPDParams(
        ec50=6.0,    # ng/mL
        emax=1.0,
        gamma=1.8,
        e0=0.0,
        ke0=0.08,   # slow equilibration — effect lags concentration
        tolerance_rate=0.002,
        tolerance_recovery=0.001,
    ),
    'levothyroxine': DrugPDParams(
        ec50=12.0,
        emax=1.0,
        gamma=1.0,
        e0=0.2,
        ke0=0.005,  # very slow effect compartment
        tolerance_rate=0.0,
    ),
    'metformin': DrugPDParams(
        ec50=800.0,  # ng/mL
        emax=0.6,
        gamma=1.3,
        e0=0.0,
        ke0=0.15,
    ),
    'digoxin': DrugPDParams(
        ec50=1.2,   # ng/mL
        emax=1.0,
        gamma=2.0,
        e0=0.0,
        ke0=0.0,
        tolerance_rate=0.001,
    ),
    'atorvastatin': DrugPDParams(
        ec50=3.5,
        emax=0.85,
        gamma=1.6,
        e0=0.0,
        ke0=0.12,
        irreversible=False,
        tolerance_rate=0.001,
        tolerance_recovery=0.0005,
    ),
    'omeprazole': DrugPDParams(
        ec50=0.08,
        emax=1.0,
        gamma=2.2,
        e0=0.0,
        irreversible=True,
        synthesis_rate=0.03,  # proton pump resynthesis
    ),
}


def _sigmoid_emax(c: float, ec50: float, emax: float, gamma: float, e0: float,
                  tolerance_factor: float = 1.0) -> float:
    """Sigmoid Emax (Hill equation) with tolerance modifier"""
    if c <= 0:
        return e0
    effective_ec50 = ec50 / max(tolerance_factor, 0.1)
    return e0 + emax * (c ** gamma) / (effective_ec50 ** gamma + c ** gamma)


@dataclass
class DosingEvent:
    time_hr: float    # hours from simulation start
    dose_mg: float
    bioavailability: float = 0.85  # personalized


@dataclass
class PKSimResult:
    times: np.ndarray           # hours
    c_central: np.ndarray       # central compartment concentration (mg/L or appropriate unit)
    c_peripheral: np.ndarray    # peripheral compartment concentration
    c_effect: np.ndarray        # effect compartment concentration
    effect: np.ndarray          # pharmacodynamic effect (0-1 or units)
    tolerance_factor: np.ndarray  # receptor occupancy/tolerance over time
    auc: float                  # total AUC (mg·hr/L)
    cmax: float
    tmax: float                 # hr
    t_above_ec50: float         # hours above EC50
    t_above_mic: float = 0.0    # for antibiotics


def simulate_pk_pd(
    pk: PersonalizedPKParams,
    pd: Optional[DrugPDParams],
    dosing_events: List[DosingEvent],
    t_end: float = 72.0,
    dt: float = 0.25,
    therapeutic_min: float = None,
    therapeutic_max: float = None,
) -> PKSimResult:
    """
    Simulate two-compartment PK + effect compartment PD over t_end hours.
    State: [A_gut, C_central*Vc, C_periph*Vp, C_effect, tolerance_receptor]
    """
    pk_params = pk
    vc = pk_params.vd_central_mean
    vp = pk_params.vd_peripheral_mean
    cl = pk_params.cl_mean
    q = pk_params.q_mean
    ka = pk_params.ka_mean
    f = pk_params.f_mean

    use_pd = pd is not None
    ke0 = pd.ke0 if use_pd else 0.0
    tol_rate = pd.tolerance_rate if use_pd else 0.0
    tol_rec = pd.tolerance_recovery if use_pd else 0.0

    # Precompute dose input function
    events_sorted = sorted(dosing_events, key=lambda e: e.time_hr)

    def dose_input(t):
        """Amount absorbed into gut at time t"""
        # Instantaneous bolus to gut compartment at dose times
        return 0.0  # handled as initial conditions per segment

    # ODE system: [A_gut, A_central, A_peripheral, C_effect, tolerance]
    # A_central = C_central * Vc, A_peripheral = C_peripheral * Vp
    def odes(t, y):
        a_gut, a_c, a_p, c_eff, tol = y
        c_c = a_c / vc  # central concentration
        c_p = a_p / vp  # peripheral concentration

        da_gut = -ka * a_gut
        da_c = ka * a_gut - (cl / vc) * a_c - (q / vc) * a_c + (q / vp) * a_p
        da_p = (q / vc) * a_c - (q / vp) * a_p
        dc_eff = ke0 * (c_c - c_eff) if ke0 > 0 else 0.0

        # Tolerance: receptor downregulation proportional to effect
        if use_pd:
            effect_now = _sigmoid_emax(c_eff if ke0 > 0 else c_c,
                                       pd.ec50, pd.emax, pd.gamma, pd.e0, tol)
            dtol = tol_rate * effect_now * tol - tol_rec * (1.0 - tol)
        else:
            dtol = 0.0

        return [da_gut, da_c, da_p, dc_eff, dtol]

    # Simulate piecewise (reset gut at each dose event)
    t_eval = np.arange(0, t_end + dt, dt)
    y0 = [0.0, 0.0, 0.0, 0.0, 1.0]  # gut=0, central=0, periph=0, effect=0, tol=1.0

    # Track results across segments
    all_t = []
    all_y = []

    # Split timeline at dose events
    dose_times = [e.time_hr for e in events_sorted]
    breakpoints = sorted(set([0.0] + dose_times + [t_end]))
    if breakpoints[-1] < t_end:
        breakpoints.append(t_end)

    current_y = np.array(y0, dtype=float)

    for i in range(len(breakpoints) - 1):
        t_start_seg = breakpoints[i]
        t_end_seg = breakpoints[i + 1]

        # Add dose at start of segment if applicable
        if t_start_seg in dose_times:
            ev_idx = dose_times.index(t_start_seg)
            ev = events_sorted[ev_idx]
            current_y[0] += ev.dose_mg * ev.bioavailability  # add to gut

        if t_end_seg <= t_start_seg:
            continue

        t_seg = np.linspace(t_start_seg, t_end_seg,
                            max(int((t_end_seg - t_start_seg) / dt) + 2, 3))

        try:
            sol = solve_ivp(
                odes,
                [t_start_seg, t_end_seg],
                current_y.tolist(),
                t_eval=t_seg,
                method='RK45',
                rtol=1e-4,
                atol=1e-6,
                dense_output=False,
            )
            if sol.success and len(sol.t) > 1:
                all_t.extend(sol.t[1:].tolist())
                all_y.extend(sol.y[:, 1:].T.tolist())
                current_y = sol.y[:, -1]
            else:
                # Fallback: keep current state
                all_t.append(t_end_seg)
                all_y.append(current_y.tolist())
        except Exception:
            all_t.append(t_end_seg)
            all_y.append(current_y.tolist())

    if not all_t:
        t_arr = t_eval
        c_central = np.zeros_like(t_eval)
        c_peripheral = np.zeros_like(t_eval)
        c_effect = np.zeros_like(t_eval)
        effect = np.zeros_like(t_eval)
        tolerance = np.ones_like(t_eval)
    else:
        t_arr = np.array([0.0] + all_t)
        y_arr = np.array([[0.0, 0.0, 0.0, 0.0, 1.0]] + all_y)
        c_central = np.maximum(y_arr[:, 1] / vc, 0.0)
        c_peripheral = np.maximum(y_arr[:, 2] / vp, 0.0)
        c_effect = np.maximum(y_arr[:, 3], 0.0)
        tolerance = np.clip(y_arr[:, 4], 0.1, 2.0)

        if use_pd:
            c_for_pd = c_effect if ke0 > 0 else c_central
            effect = np.array([
                _sigmoid_emax(c, pd.ec50, pd.emax, pd.gamma, pd.e0, tol)
                for c, tol in zip(c_for_pd, tolerance)
            ])
        else:
            effect = np.zeros_like(c_central)

    # Compute summary statistics
    if len(t_arr) > 1:
        auc = float(np.trapezoid(c_central, t_arr))
        cmax = float(np.max(c_central))
        tmax_idx = int(np.argmax(c_central))
        tmax = float(t_arr[tmax_idx])
    else:
        auc = 0.0
        cmax = 0.0
        tmax = 0.0

    ec50_val = pd.ec50 if use_pd else 0.0
    if use_pd and ec50_val > 0:
        t_above_ec50 = float(np.sum(c_central >= ec50_val) * dt)
    else:
        t_above_ec50 = 0.0

    return PKSimResult(
        times=t_arr,
        c_central=c_central,
        c_peripheral=c_peripheral,
        c_effect=c_effect if use_pd else c_central * 0,
        effect=effect,
        tolerance_factor=tolerance,
        auc=auc,
        cmax=cmax,
        tmax=tmax,
        t_above_ec50=t_above_ec50,
    )


def compute_drug_interaction_pk(
    victim_pk: PersonalizedPKParams,
    perpetrator_pk: PersonalizedPKParams,
    perpetrator_concentration: float,
    interaction_ki: float,
    inhibition_type: str = 'competitive',  # competitive, uncompetitive, mechanism_based
) -> float:
    """
    Compute fold-increase in victim drug AUC due to CYP inhibition by perpetrator.
    Returns AUC ratio (inhibited / uninhibited).
    """
    if inhibition_type == 'competitive':
        # R = 1 + [I]/Ki where [I] is unbound inhibitor concentration
        r = 1.0 + perpetrator_concentration / interaction_ki
        return r
    elif inhibition_type == 'mechanism_based':
        # Irreversible inhibitor — depends on kinact and [I]
        kinact = 0.03  # typical 1/hr
        kdeg = 0.0193  # CYP3A4 degradation rate 1/hr
        r = 1.0 + (kinact * perpetrator_concentration) / ((interaction_ki + perpetrator_concentration) * kdeg)
        return r
    return 1.0


def bliss_independence(effect_a: float, effect_b: float) -> float:
    """Bliss independence: combined effect for independent drugs on same endpoint"""
    return effect_a + effect_b - effect_a * effect_b


def loewe_additivity_combined(
    c_a: float, c_b: float,
    ec50_a: float, ec50_b: float,
    emax: float, gamma: float
) -> float:
    """
    Loewe additivity: treats combination as single drug.
    c_eq = c_a + c_b * (ec50_a / ec50_b)  [equipotent units]
    """
    c_eq = c_a + c_b * (ec50_a / max(ec50_b, 1e-9))
    return _sigmoid_emax(c_eq, ec50_a, emax, gamma, 0.0)
