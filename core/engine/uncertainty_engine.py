"""
Layer 3: Uncertainty Engine
Monte Carlo simulation over PK parameter distributions.
Every output is a risk distribution, not a point estimate.
Bayesian updating from observed outcomes.
"""
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from .biological_twin import PersonalizedPKParams, PatientPhysiology, personalize_pk
from .pk_pd_engine import (
    PKSimResult, DosingEvent, simulate_pk_pd,
    DRUG_PD_PARAMS, DrugPDParams
)


@dataclass
class RiskDistribution:
    """Output: full distribution of a risk metric, not a point estimate"""
    metric_name: str
    samples: np.ndarray         # N Monte Carlo samples
    median: float
    p5: float                   # 5th percentile (best case)
    p25: float
    p75: float
    p95: float                  # 95th percentile (worst case)
    mean: float
    std: float
    probability_above_threshold: float = 0.0
    threshold: float = 0.0

    @classmethod
    def from_samples(cls, name: str, samples: np.ndarray, threshold: float = 0.0):
        s = np.sort(samples)
        n = len(s)
        prob_above = float(np.mean(s > threshold)) if threshold > 0 else 0.0
        return cls(
            metric_name=name,
            samples=s,
            median=float(np.median(s)),
            p5=float(np.percentile(s, 5)),
            p25=float(np.percentile(s, 25)),
            p75=float(np.percentile(s, 75)),
            p95=float(np.percentile(s, 95)),
            mean=float(np.mean(s)),
            std=float(np.std(s)),
            probability_above_threshold=prob_above,
            threshold=threshold,
        )

    def to_dict(self) -> dict:
        return {
            'metric': self.metric_name,
            'median': round(self.median, 4),
            'p5': round(self.p5, 4),
            'p25': round(self.p25, 4),
            'p75': round(self.p75, 4),
            'p95': round(self.p95, 4),
            'mean': round(self.mean, 4),
            'std': round(self.std, 4),
            'prob_above_threshold': round(self.probability_above_threshold, 4),
            'threshold': self.threshold,
        }


@dataclass
class MonteCarloResult:
    drug_name: str
    n_simulations: int
    auc_distribution: RiskDistribution
    cmax_distribution: RiskDistribution
    tmax_distribution: RiskDistribution
    t_therapeutic_distribution: RiskDistribution  # time in therapeutic window
    toxicity_risk: RiskDistribution               # prob of exceeding toxic threshold
    efficacy_probability: float                   # prob of staying above MEC
    concentration_timeline: Dict[str, np.ndarray]  # percentile bands over time
    interaction_risk_distribution: Optional[RiskDistribution] = None


def sample_pk_params(pk: PersonalizedPKParams, rng: np.random.Generator) -> dict:
    """Sample one set of PK parameters from their distributions"""
    vc = max(rng.normal(pk.vd_central_mean, pk.vd_central_std), pk.vd_central_mean * 0.2)
    vp = max(rng.normal(pk.vd_peripheral_mean, pk.vd_peripheral_std), pk.vd_peripheral_mean * 0.2)
    cl = max(rng.normal(pk.cl_mean, pk.cl_std), pk.cl_mean * 0.1)
    q = max(rng.normal(pk.q_mean, pk.q_std), pk.q_mean * 0.2)
    ka = max(rng.normal(pk.ka_mean, pk.ka_std), 0.05)
    f = float(np.clip(rng.normal(pk.f_mean, pk.f_std), 0.05, 1.0))
    return dict(vc=vc, vp=vp, cl=cl, q=q, ka=ka, f=f)


def run_monte_carlo(
    pk: PersonalizedPKParams,
    dosing_events: List[DosingEvent],
    drug_name: str,
    n_sims: int = 1000,
    t_end: float = 72.0,
    dt: float = 0.5,
    toxic_threshold: float = None,
    therapeutic_min: float = None,
    therapeutic_max: float = None,
    seed: int = 42,
) -> MonteCarloResult:
    """Run Monte Carlo over PK parameter uncertainty"""
    rng = np.random.default_rng(seed)
    pd = DRUG_PD_PARAMS.get(drug_name.lower())

    auc_samples = []
    cmax_samples = []
    tmax_samples = []
    t_therapeutic_samples = []
    toxicity_samples = []

    # Common time grid for concentration bands
    t_grid = np.arange(0, t_end + dt, dt)
    c_matrix = []  # shape: (n_sims, len(t_grid))

    for sim_i in range(n_sims):
        sampled = sample_pk_params(pk, rng)

        # Build a temporary PK params object with sampled values
        pk_s = PersonalizedPKParams.__new__(PersonalizedPKParams)
        pk_s.drug_name = pk.drug_name
        pk_s.patient_id = pk.patient_id
        pk_s.vd_central_mean = sampled['vc']
        pk_s.vd_central_std = pk.vd_central_std * 0.1  # tight for inner sim
        pk_s.vd_peripheral_mean = sampled['vp']
        pk_s.vd_peripheral_std = pk.vd_peripheral_std * 0.1
        pk_s.cl_mean = sampled['cl']
        pk_s.cl_std = pk.cl_std * 0.1
        pk_s.q_mean = sampled['q']
        pk_s.q_std = pk.q_std * 0.1
        pk_s.ka_mean = sampled['ka']
        pk_s.ka_std = pk.ka_std * 0.1
        pk_s.f_mean = sampled['f']
        pk_s.f_std = pk.f_std * 0.1
        pk_s.half_life_mean = 0.693 * sampled['vc'] / sampled['cl']
        pk_s.half_life_std = 0.0

        # Resample dosing events with this F
        adjusted_events = [
            DosingEvent(e.time_hr, e.dose_mg, sampled['f'])
            for e in dosing_events
        ]

        # Add residual variability to PD
        pd_s = None
        if pd:
            ec50_noise = float(np.clip(rng.normal(1.0, 0.20), 0.5, 2.0))
            pd_s = DrugPDParams(
                ec50=pd.ec50 * ec50_noise,
                emax=pd.emax,
                gamma=pd.gamma,
                e0=pd.e0,
                ke0=pd.ke0,
                tolerance_rate=pd.tolerance_rate,
                tolerance_recovery=pd.tolerance_recovery,
                irreversible=pd.irreversible,
                synthesis_rate=pd.synthesis_rate,
            )

        try:
            result = simulate_pk_pd(pk_s, pd_s, adjusted_events, t_end=t_end, dt=dt)

            # Interpolate to common grid
            if len(result.times) > 2:
                interp_fn = np.interp(t_grid, result.times, result.c_central,
                                      left=0.0, right=0.0)
                c_matrix.append(interp_fn)
            else:
                c_matrix.append(np.zeros_like(t_grid))

            auc_samples.append(result.auc)
            cmax_samples.append(result.cmax)
            tmax_samples.append(result.tmax)

            # Time in therapeutic window
            if therapeutic_min is not None and therapeutic_max is not None:
                in_window = np.sum(
                    (result.c_central >= therapeutic_min) &
                    (result.c_central <= therapeutic_max)
                ) * dt
                t_therapeutic_samples.append(float(in_window))
            else:
                t_therapeutic_samples.append(float(result.t_above_ec50))

            # Toxicity: fraction above toxic threshold
            if toxic_threshold:
                toxicity_samples.append(float(np.max(result.c_central) > toxic_threshold))
            else:
                toxicity_samples.append(0.0)

        except Exception:
            c_matrix.append(np.zeros_like(t_grid))
            auc_samples.append(0.0)
            cmax_samples.append(0.0)
            tmax_samples.append(0.0)
            t_therapeutic_samples.append(0.0)
            toxicity_samples.append(0.0)

    auc_arr = np.array(auc_samples)
    cmax_arr = np.array(cmax_samples)
    tmax_arr = np.array(tmax_samples)
    t_ther_arr = np.array(t_therapeutic_samples)
    tox_arr = np.array(toxicity_samples)

    c_matrix_arr = np.array(c_matrix) if c_matrix else np.zeros((n_sims, len(t_grid)))

    # Concentration percentile bands
    conc_timeline = {
        't': t_grid.tolist(),
        'p5': np.percentile(c_matrix_arr, 5, axis=0).tolist(),
        'p25': np.percentile(c_matrix_arr, 25, axis=0).tolist(),
        'median': np.percentile(c_matrix_arr, 50, axis=0).tolist(),
        'p75': np.percentile(c_matrix_arr, 75, axis=0).tolist(),
        'p95': np.percentile(c_matrix_arr, 95, axis=0).tolist(),
    }

    # Efficacy probability: median concentration stays above MEC
    if therapeutic_min and np.mean(auc_arr) > 0:
        pd_ref = DRUG_PD_PARAMS.get(drug_name.lower())
        ec50_threshold = pd_ref.ec50 if pd_ref else 0.0
        median_c = np.percentile(c_matrix_arr, 50, axis=0)
        efficacy_prob = float(np.mean(median_c >= ec50_threshold))
    else:
        efficacy_prob = 0.5

    return MonteCarloResult(
        drug_name=drug_name,
        n_simulations=n_sims,
        auc_distribution=RiskDistribution.from_samples('AUC', auc_arr),
        cmax_distribution=RiskDistribution.from_samples('Cmax', cmax_arr,
                                                         threshold=toxic_threshold or 0),
        tmax_distribution=RiskDistribution.from_samples('Tmax', tmax_arr),
        t_therapeutic_distribution=RiskDistribution.from_samples(
            'Time_in_Therapeutic_Window', t_ther_arr, threshold=t_end * 0.5),
        toxicity_risk=RiskDistribution.from_samples(
            'Toxicity_Probability', tox_arr, threshold=0.5),
        efficacy_probability=efficacy_prob,
        concentration_timeline=conc_timeline,
    )


class BayesianParameterUpdater:
    """
    Layer 8 partially: Bayesian updating of personal PK parameters
    from observed outcomes (side effects, lab values, adherence).
    Uses conjugate normal-normal updates for computational efficiency.
    """

    def __init__(self, pk: PersonalizedPKParams):
        self.pk = pk
        # Store prior as (mean, variance) for each parameter
        self.priors = {
            'cl': (pk.cl_mean, pk.cl_std ** 2),
            'vd': (pk.vd_central_mean, pk.vd_central_std ** 2),
            'ka': (pk.ka_mean, pk.ka_std ** 2),
            'f': (pk.f_mean, pk.f_std ** 2),
        }
        self.posteriors = dict(self.priors)
        self.observations = []

    def update_from_concentration(self, observed_c: float, predicted_c: float,
                                   prediction_uncertainty: float, param: str = 'cl'):
        """
        Bayesian update: observed concentration adjusts clearance estimate.
        If observed > predicted, clearance is likely lower than estimated.
        """
        ratio = predicted_c / max(observed_c, 0.01)  # clearance adjustment factor
        mu_prior, var_prior = self.posteriors[param]

        # Likelihood variance from prediction uncertainty
        var_likelihood = (prediction_uncertainty / predicted_c) ** 2 * mu_prior ** 2

        # Conjugate normal-normal update
        var_posterior = 1.0 / (1.0 / var_prior + 1.0 / var_likelihood)
        mu_posterior = var_posterior * (mu_prior / var_prior + mu_prior * ratio / var_likelihood)

        self.posteriors[param] = (mu_posterior, var_posterior)
        self.observations.append({
            'type': 'concentration',
            'observed': observed_c,
            'predicted': predicted_c,
            'param': param,
        })

    def update_from_side_effect(self, drug_name: str, effect_level: float,
                                 expected_concentration: float):
        """
        If patient reports side effect at lower-than-expected concentration,
        their sensitivity (EC50) is higher than population average.
        """
        sensitivity_adjustment = expected_concentration / max(effect_level, 0.1)
        self.observations.append({
            'type': 'side_effect',
            'drug': drug_name,
            'sensitivity_adj': sensitivity_adjustment,
        })

    def update_from_lab(self, lab_name: str, value: float, unit: str):
        """Update from lab results (creatinine → CrCl → clearance)"""
        if lab_name.lower() in ('creatinine', 'scr'):
            # Creatinine directly constrains renal clearance
            self.observations.append({
                'type': 'lab',
                'lab': lab_name,
                'value': value,
                'unit': unit,
            })

    def get_updated_pk(self) -> PersonalizedPKParams:
        """Return new PK params with Bayesian-updated estimates"""
        updated = PersonalizedPKParams(
            drug_name=self.pk.drug_name,
            patient_id=self.pk.patient_id,
            vd_central_mean=self.posteriors['vd'][0],
            vd_central_std=float(np.sqrt(self.posteriors['vd'][1])),
            vd_peripheral_mean=self.pk.vd_peripheral_mean,
            vd_peripheral_std=self.pk.vd_peripheral_std,
            cl_mean=self.posteriors['cl'][0],
            cl_std=float(np.sqrt(self.posteriors['cl'][1])),
            q_mean=self.pk.q_mean,
            q_std=self.pk.q_std,
            ka_mean=self.posteriors['ka'][0],
            ka_std=float(np.sqrt(self.posteriors['ka'][1])),
            f_mean=float(np.clip(self.posteriors['f'][0], 0.05, 1.0)),
            f_std=float(np.sqrt(self.posteriors['f'][1])),
        )
        return updated

    def uncertainty_reduction_pct(self) -> Dict[str, float]:
        """How much has uncertainty reduced vs prior"""
        reductions = {}
        for param, (prior_m, prior_v) in self.priors.items():
            post_m, post_v = self.posteriors[param]
            if prior_v > 0:
                reductions[param] = round((1 - post_v / prior_v) * 100, 1)
            else:
                reductions[param] = 0.0
        return reductions
