"""
Layer 4: Multi-Objective Schedule Optimizer
Solves constrained multi-objective optimization over a 72-hour horizon.
Produces Pareto frontier — not one schedule, but the tradeoff surface.
"""
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
import itertools
import math


@dataclass
class MedicationConstraint:
    drug_name: str
    dose_mg: float
    frequency_per_day: int          # 1, 2, 3, 4
    min_interval_hrs: float         # min time between doses
    max_daily_dose_mg: float
    must_take_with_food: bool = False
    must_take_empty_stomach: bool = False
    avoid_bedtime: bool = False
    max_time_of_day_hr: Optional[float] = None   # e.g. 9.0 = must take before 9am
    absolute_contraindication_drugs: List[str] = field(default_factory=list)


@dataclass
class PatientPreferences:
    wake_time_hr: float = 7.0
    sleep_time_hr: float = 23.0
    meal_times_hr: List[float] = field(default_factory=lambda: [7.5, 13.0, 19.5])
    work_meeting_blocks: List[Tuple[float, float]] = field(default_factory=list)  # (start_hr, end_hr)
    prefer_morning_doses: bool = True
    max_doses_morning: int = 4
    # Day-of-week adherence probabilities (0=Mon, 6=Sun)
    adherence_by_hour: Dict[int, float] = field(default_factory=lambda: {h: 0.9 for h in range(24)})


@dataclass
class ScheduledDose:
    drug_name: str
    dose_mg: float
    time_hr: float         # hours from midnight
    day: int               # 0, 1, 2 (in 72hr window)
    with_food: bool = False
    rationale: str = ''


@dataclass
class ScheduleSolution:
    """One point on the Pareto frontier"""
    doses: List[ScheduledDose]
    objectives: Dict[str, float]   # objective name → value
    is_feasible: bool
    violated_constraints: List[str] = field(default_factory=list)
    label: str = ''                # e.g. 'Maximum Efficacy', 'Minimum Disruption'


def _hours_in_window(time_hr: float, window_start: float, window_end: float,
                     window_duration: float) -> bool:
    """Check if time_hr is within a food/fasting window"""
    return window_start <= (time_hr % 24) <= window_end


def _compute_objectives(
    schedule: List[ScheduledDose],
    medication_constraints: List[MedicationConstraint],
    patient_prefs: PatientPreferences,
    interaction_matrix: Dict[Tuple[str, str], float],  # (drug_a, drug_b) → risk_at_time
    pk_summaries: Dict[str, Dict],  # drug → {therapeutic_coverage: float, peak_risk: float}
) -> Tuple[Dict[str, float], List[str]]:
    """
    Compute all objectives for a given schedule.
    Returns (objectives_dict, violated_constraints_list)
    """
    violations = []
    objectives = {}

    # O1: Therapeutic coverage — maximize time in therapeutic window
    total_coverage = 0.0
    for med_name, pk_data in pk_summaries.items():
        total_coverage += pk_data.get('therapeutic_coverage', 0.7)
    objectives['therapeutic_coverage'] = total_coverage / max(len(pk_summaries), 1)

    # O2: Peak toxicity risk — minimize Cmax exceedances
    peak_risk = max((pk_data.get('peak_risk', 0.0) for pk_data in pk_summaries.values()), default=0.0)
    objectives['peak_toxicity_risk'] = peak_risk

    # O3: Interaction risk at scheduled times
    interaction_risk = 0.0
    for dose_a in schedule:
        for dose_b in schedule:
            if dose_a.drug_name >= dose_b.drug_name:
                continue
            if abs(dose_a.time_hr - dose_b.time_hr) < 4.0 and dose_a.day == dose_b.day:
                pair_risk = interaction_matrix.get(
                    (dose_a.drug_name.lower(), dose_b.drug_name.lower()), 0.0)
                interaction_risk += pair_risk
    objectives['interaction_risk'] = interaction_risk

    # O4: Convenience — deviation from natural rhythms
    inconvenience = 0.0
    wake = patient_prefs.wake_time_hr
    sleep = patient_prefs.sleep_time_hr
    for dose in schedule:
        hour = dose.time_hr % 24
        # Penalty for dosing outside wake hours
        if hour < wake or hour > sleep:
            inconvenience += 2.0  # heavy penalty for waking at night
        # Penalty for dosing during work meetings
        for (meet_s, meet_e) in patient_prefs.work_meeting_blocks:
            if meet_s <= hour <= meet_e:
                inconvenience += 0.5
    objectives['inconvenience'] = inconvenience / max(len(schedule), 1)

    # O5: Adherence probability — weight by historical adherence
    adherence_prob = 1.0
    for dose in schedule:
        hour = int(dose.time_hr % 24)
        adh = patient_prefs.adherence_by_hour.get(hour, 0.85)
        adherence_prob *= adh
    objectives['expected_adherence'] = adherence_prob ** (1.0 / max(len(schedule), 1))

    # O6: Dose count simplicity (minimize number of different timing windows)
    unique_times = len(set(round(d.time_hr % 24, 0) for d in schedule))
    objectives['dose_complexity'] = unique_times / max(len(schedule), 1)

    # ─── Constraint checking ───
    for mc in medication_constraints:
        drug_doses = [d for d in schedule if d.drug_name.lower() == mc.drug_name.lower()]

        # Hard: minimum interval
        drug_doses_sorted = sorted(drug_doses, key=lambda d: d.day * 24 + d.time_hr)
        for i in range(1, len(drug_doses_sorted)):
            dt = (drug_doses_sorted[i].day * 24 + drug_doses_sorted[i].time_hr) - \
                 (drug_doses_sorted[i-1].day * 24 + drug_doses_sorted[i-1].time_hr)
            if dt < mc.min_interval_hrs:
                violations.append(f"{mc.drug_name}: doses {dt:.1f}hr apart < min {mc.min_interval_hrs}hr")

        # Hard: food requirements
        for dose in drug_doses:
            hour = dose.time_hr % 24
            meal_times = patient_prefs.meal_times_hr
            near_meal = any(abs(hour - mt) <= 0.5 for mt in meal_times)
            if mc.must_take_with_food and not near_meal and not dose.with_food:
                violations.append(f"{mc.drug_name}: must take with food — none nearby at {hour:.1f}hr")
            if mc.must_take_empty_stomach and near_meal:
                violations.append(f"{mc.drug_name}: must take on empty stomach — meal at {hour:.1f}hr")

        # Hard: max daily dose
        for day in range(3):
            day_doses = [d for d in drug_doses if d.day == day]
            daily_total = sum(d.dose_mg for d in day_doses)
            if daily_total > mc.max_daily_dose_mg:
                violations.append(f"{mc.drug_name}: day {day} dose {daily_total}mg > max {mc.max_daily_dose_mg}mg")

    return objectives, violations


def _dominates(obj_a: Dict, obj_b: Dict,
               maximize: Set[str], minimize: Set[str]) -> bool:
    """Returns True if solution A dominates solution B (Pareto dominance)"""
    at_least_one_better = False
    for k in maximize:
        if obj_a.get(k, 0) < obj_b.get(k, 0):
            return False
        if obj_a.get(k, 0) > obj_b.get(k, 0):
            at_least_one_better = True
    for k in minimize:
        if obj_a.get(k, 0) > obj_b.get(k, 0):
            return False
        if obj_a.get(k, 0) < obj_b.get(k, 0):
            at_least_one_better = True
    return at_least_one_better


def compute_pareto_frontier(
    medication_constraints: List[MedicationConstraint],
    patient_prefs: PatientPreferences,
    interaction_matrix: Dict = None,
    pk_summaries: Dict = None,
    n_candidate_schedules: int = 200,
    seed: int = 42,
) -> List[ScheduleSolution]:
    """
    Generate candidate schedules and compute the Pareto frontier.
    Returns list of non-dominated solutions (the tradeoff surface).
    """
    if interaction_matrix is None:
        interaction_matrix = {}
    if pk_summaries is None:
        pk_summaries = {mc.drug_name: {'therapeutic_coverage': 0.75, 'peak_risk': 0.1}
                        for mc in medication_constraints}

    rng = np.random.default_rng(seed)

    MAXIMIZE = {'therapeutic_coverage', 'expected_adherence'}
    MINIMIZE = {'peak_toxicity_risk', 'interaction_risk', 'inconvenience', 'dose_complexity'}

    # Generate candidate schedules via structured sampling
    candidates = []

    wake = patient_prefs.wake_time_hr
    sleep = patient_prefs.sleep_time_hr
    meal_times = patient_prefs.meal_times_hr

    # Anchor times: morning, noon, evening, bedtime
    anchor_sets = [
        {'early_morning': wake, 'noon': 13.0, 'evening': 18.0, 'bedtime': sleep - 1},
        {'early_morning': wake + 1, 'noon': 12.0, 'evening': 19.0, 'bedtime': sleep - 2},
        {'early_morning': wake + 2, 'noon': 13.5, 'evening': 20.0, 'bedtime': sleep - 0.5},
    ]
    anchor_sets += [
        {k: v + rng.uniform(-1, 1) for k, v in anchor_sets[0].items()}
        for _ in range(n_candidate_schedules - len(anchor_sets))
    ]

    for anchors in anchor_sets:
        schedule = []
        for mc in medication_constraints:
            freq = mc.frequency_per_day
            # Assign times based on frequency
            if freq == 1:
                time_slots = [anchors['early_morning']]
                if mc.must_take_with_food:
                    time_slots = [meal_times[0] + 0.1]
                elif mc.must_take_empty_stomach:
                    time_slots = [wake - 0.5 if wake > 0.5 else wake]
            elif freq == 2:
                time_slots = [anchors['early_morning'], anchors['evening']]
            elif freq == 3:
                time_slots = [anchors['early_morning'], anchors['noon'], anchors['evening']]
            elif freq == 4:
                time_slots = [anchors['early_morning'], anchors['noon'],
                              anchors['evening'], anchors['bedtime']]
            else:
                time_slots = [anchors['early_morning']]

            for day in range(3):
                for t in time_slots:
                    near_meal = any(abs((t % 24) - mt) <= 0.75 for mt in meal_times)
                    schedule.append(ScheduledDose(
                        drug_name=mc.drug_name,
                        dose_mg=mc.dose_mg,
                        time_hr=t % 24,
                        day=day,
                        with_food=near_meal or mc.must_take_with_food,
                        rationale=f"Scheduled at {t%24:.1f}hr based on {freq}×/day frequency",
                    ))

        objs, viols = _compute_objectives(
            schedule, medication_constraints, patient_prefs, interaction_matrix, pk_summaries
        )
        is_feasible = len(viols) == 0
        candidates.append(ScheduleSolution(
            doses=schedule,
            objectives=objs,
            is_feasible=is_feasible,
            violated_constraints=viols,
        ))

    # Pareto filtering — keep only non-dominated feasible solutions
    feasible = [c for c in candidates if c.is_feasible]
    if not feasible:
        feasible = candidates  # relax feasibility if all infeasible

    pareto = []
    for i, sol_a in enumerate(feasible):
        dominated = False
        for j, sol_b in enumerate(feasible):
            if i == j:
                continue
            if _dominates(sol_b.objectives, sol_a.objectives, MAXIMIZE, MINIMIZE):
                dominated = True
                break
        if not dominated:
            pareto.append(sol_a)

    # Label extreme points on Pareto front
    if pareto:
        # Max efficacy
        best_eff = max(pareto, key=lambda s: s.objectives.get('therapeutic_coverage', 0))
        best_eff.label = 'Maximum Efficacy'
        # Min disruption
        min_disr = min(pareto, key=lambda s: s.objectives.get('inconvenience', 999))
        min_disr.label = 'Minimum Disruption'
        # Min risk
        min_risk = min(pareto, key=lambda s: s.objectives.get('interaction_risk', 999))
        min_risk.label = 'Minimum Risk'
        # Best adherence
        best_adh = max(pareto, key=lambda s: s.objectives.get('expected_adherence', 0))
        best_adh.label = 'Best Adherence'

    return pareto[:10]  # return up to 10 non-dominated solutions


def reoptimize_after_missed_dose(
    current_schedule: List[ScheduledDose],
    missed_drug: str,
    missed_time_hr: float,
    current_time_hr: float,
    medication_constraints: List[MedicationConstraint],
) -> List[ScheduledDose]:
    """
    Instantly reoptimize the remaining schedule after a missed dose.
    Returns updated remaining doses for the 72hr window.
    """
    mc = next((m for m in medication_constraints
               if m.drug_name.lower() == missed_drug.lower()), None)
    if not mc:
        return current_schedule

    # Determine if catch-up dose is safe
    time_since_prev = current_time_hr - missed_time_hr
    next_dose_due = missed_time_hr + (24.0 / mc.frequency_per_day)
    time_to_next = next_dose_due - current_time_hr

    updated = []
    for dose in current_schedule:
        if dose.drug_name.lower() != missed_drug.lower():
            updated.append(dose)
            continue
        # Reschedule missed dose doses
        new_time = current_time_hr + 0.5 if time_since_prev < mc.min_interval_hrs else missed_time_hr
        new_dose = ScheduledDose(
            drug_name=dose.drug_name,
            dose_mg=dose.dose_mg,
            time_hr=new_time % 24,
            day=dose.day,
            with_food=dose.with_food,
            rationale=f"Rescheduled: missed dose at {missed_time_hr:.1f}hr, reoptimized",
        )
        updated.append(new_dose)

    return sorted(updated, key=lambda d: d.day * 24 + d.time_hr)
