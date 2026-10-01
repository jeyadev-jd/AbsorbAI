"""
Seed realistic demo data on top of seed_demo_users: extra patients,
adherence history, and audit trail entries so the doctor/patient
dashboards render populated instead of empty on a fresh DB.

Run after seed_demo_users:
    python manage.py seed_demo_users
    python manage.py seed_demo_data
"""
import random
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Patient, AdherenceEvent, AuditEntry

EXTRA_PATIENTS = [
    {
        'patient_key': 'ravi_kumar',
        'name': 'Ravi Kumar',
        'age': 67, 'weight': 74, 'height': 171, 'sex': 'M',
        'serum_creatinine': 1.6, 'child_pugh_score': 6,
        'body_fat_pct': 27, 'plasma_albumin': 3.6,
        'gut_motility_score': 0.85, 'hydration_score': 0.9,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 0.8, 'cyp2d6_activity': 1.0,
        'cyp2c9_activity': 0.6, 'cyp2c19_activity': 1.0,
        'cyp1a2_activity': 0.9, 'cyp2e1_activity': 1.0,
        'wake_time_hr': 6.0, 'sleep_time_hr': 21.5,
        'meal_times_hr': [7.0, 12.5, 19.0],
    },
    {
        'patient_key': 'meera_iyer',
        'name': 'Meera Iyer',
        'age': 34, 'weight': 61, 'height': 158, 'sex': 'F',
        'serum_creatinine': 0.7, 'child_pugh_score': 5,
        'body_fat_pct': 22, 'plasma_albumin': 4.4,
        'gut_motility_score': 1.1, 'hydration_score': 1.0,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 1.1, 'cyp2d6_activity': 0.5,
        'cyp2c9_activity': 1.0, 'cyp2c19_activity': 1.0,
        'cyp1a2_activity': 1.2, 'cyp2e1_activity': 1.0,
        'wake_time_hr': 7.0, 'sleep_time_hr': 23.0,
        'meal_times_hr': [8.0, 13.5, 20.0],
    },
    {
        'patient_key': 'suresh_pillai',
        'name': 'Suresh Pillai',
        'age': 58, 'weight': 82, 'height': 175, 'sex': 'M',
        'serum_creatinine': 1.1, 'child_pugh_score': 8,
        'body_fat_pct': 30, 'plasma_albumin': 3.2,
        'gut_motility_score': 0.9, 'hydration_score': 0.95,
        'is_sick': False, 'alcohol_last_24h': True,
        'cyp3a4_activity': 0.65, 'cyp2d6_activity': 1.0,
        'cyp2c9_activity': 0.75, 'cyp2c19_activity': 0.8,
        'cyp1a2_activity': 0.7, 'cyp2e1_activity': 1.3,
        'wake_time_hr': 6.5, 'sleep_time_hr': 22.0,
        'meal_times_hr': [7.5, 13.0, 20.5],
    },
    {
        'patient_key': 'lakshmi_nair',
        'name': 'Lakshmi Nair',
        'age': 71, 'weight': 55, 'height': 152, 'sex': 'F',
        'serum_creatinine': 1.3, 'child_pugh_score': 5,
        'body_fat_pct': 32, 'plasma_albumin': 3.8,
        'gut_motility_score': 0.8, 'hydration_score': 0.85,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 0.75, 'cyp2d6_activity': 0.9,
        'cyp2c9_activity': 0.7, 'cyp2c19_activity': 0.9,
        'cyp1a2_activity': 0.8, 'cyp2e1_activity': 0.95,
        'wake_time_hr': 6.0, 'sleep_time_hr': 21.0,
        'meal_times_hr': [7.0, 12.0, 19.0],
    },
    {
        'patient_key': 'arjun_menon',
        'name': 'Arjun Menon',
        'age': 29, 'weight': 78, 'height': 178, 'sex': 'M',
        'serum_creatinine': 0.9, 'child_pugh_score': 5,
        'body_fat_pct': 18, 'plasma_albumin': 4.5,
        'gut_motility_score': 1.2, 'hydration_score': 1.05,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 1.15, 'cyp2d6_activity': 1.0,
        'cyp2c9_activity': 1.05, 'cyp2c19_activity': 1.0,
        'cyp1a2_activity': 1.3, 'cyp2e1_activity': 1.0,
        'wake_time_hr': 6.5, 'sleep_time_hr': 23.5,
        'meal_times_hr': [7.5, 13.0, 20.0],
    },
    {
        'patient_key': 'fatima_sheikh',
        'name': 'Fatima Sheikh',
        'age': 46, 'weight': 68, 'height': 160, 'sex': 'F',
        'serum_creatinine': 0.8, 'child_pugh_score': 5,
        'body_fat_pct': 26, 'plasma_albumin': 4.2,
        'gut_motility_score': 1.0, 'hydration_score': 1.0,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 1.0, 'cyp2d6_activity': 1.0,
        'cyp2c9_activity': 1.0, 'cyp2c19_activity': 1.0,
        'cyp1a2_activity': 1.0, 'cyp2e1_activity': 1.0,
        'wake_time_hr': 6.5, 'sleep_time_hr': 22.5,
        'meal_times_hr': [7.5, 13.0, 19.5],
    },
    {
        'patient_key': 'george_thomas',
        'name': 'George Thomas',
        'age': 63, 'weight': 90, 'height': 173, 'sex': 'M',
        'serum_creatinine': 1.4, 'child_pugh_score': 6,
        'body_fat_pct': 29, 'plasma_albumin': 3.7,
        'gut_motility_score': 0.9, 'hydration_score': 0.9,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 0.85, 'cyp2d6_activity': 1.0,
        'cyp2c9_activity': 0.8, 'cyp2c19_activity': 0.9,
        'cyp1a2_activity': 0.9, 'cyp2e1_activity': 1.1,
        'wake_time_hr': 6.0, 'sleep_time_hr': 22.0,
        'meal_times_hr': [7.0, 13.0, 19.5],
    },
    {
        'patient_key': 'priyanka_das',
        'name': 'Priyanka Das',
        'age': 38, 'weight': 64, 'height': 163, 'sex': 'F',
        'serum_creatinine': 0.75, 'child_pugh_score': 5,
        'body_fat_pct': 25, 'plasma_albumin': 4.3,
        'gut_motility_score': 1.05, 'hydration_score': 1.0,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 1.0, 'cyp2d6_activity': 1.0,
        'cyp2c9_activity': 1.0, 'cyp2c19_activity': 1.0,
        'cyp1a2_activity': 1.0, 'cyp2e1_activity': 1.0,
        'wake_time_hr': 7.0, 'sleep_time_hr': 23.0,
        'meal_times_hr': [8.0, 13.5, 20.0],
    },
    {
        'patient_key': 'vikram_reddy',
        'name': 'Vikram Reddy',
        'age': 55, 'weight': 88, 'height': 176, 'sex': 'M',
        'serum_creatinine': 1.2, 'child_pugh_score': 5,
        'body_fat_pct': 28, 'plasma_albumin': 4.0,
        'gut_motility_score': 0.95, 'hydration_score': 0.95,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 0.9, 'cyp2d6_activity': 1.0,
        'cyp2c9_activity': 0.85, 'cyp2c19_activity': 1.0,
        'cyp1a2_activity': 0.95, 'cyp2e1_activity': 1.0,
        'wake_time_hr': 6.5, 'sleep_time_hr': 22.0,
        'meal_times_hr': [7.5, 13.0, 20.0],
    },
    {
        'patient_key': 'nisha_kapoor',
        'name': 'Nisha Kapoor',
        'age': 26, 'weight': 57, 'height': 165, 'sex': 'F',
        'serum_creatinine': 0.7, 'child_pugh_score': 5,
        'body_fat_pct': 21, 'plasma_albumin': 4.5,
        'gut_motility_score': 1.15, 'hydration_score': 1.05,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 1.1, 'cyp2d6_activity': 1.0,
        'cyp2c9_activity': 1.05, 'cyp2c19_activity': 1.0,
        'cyp1a2_activity': 1.2, 'cyp2e1_activity': 1.0,
        'wake_time_hr': 7.5, 'sleep_time_hr': 23.5,
        'meal_times_hr': [8.5, 14.0, 20.5],
    },
    {
        'patient_key': 'anand_joshi',
        'name': 'Anand Joshi',
        'age': 74, 'weight': 70, 'height': 169, 'sex': 'M',
        'serum_creatinine': 1.7, 'child_pugh_score': 7,
        'body_fat_pct': 24, 'plasma_albumin': 3.4,
        'gut_motility_score': 0.75, 'hydration_score': 0.8,
        'is_sick': False, 'alcohol_last_24h': False,
        'cyp3a4_activity': 0.7, 'cyp2d6_activity': 0.85,
        'cyp2c9_activity': 0.65, 'cyp2c19_activity': 0.8,
        'cyp1a2_activity': 0.75, 'cyp2e1_activity': 1.0,
        'wake_time_hr': 5.5, 'sleep_time_hr': 21.0,
        'meal_times_hr': [6.5, 12.0, 18.5],
    },
]

# (patient_key, drug, scheduled_time) — one row per daily dose slot,
# adherence history is generated across the past 7 days for each.
ADHERENCE_SCHEDULE = [
    ('ananya', 'warfarin', '08:00'),
    ('ananya', 'metformin', '08:00'),
    ('ananya', 'metformin', '20:00'),
    ('ravi_kumar', 'amlodipine', '08:00'),
    ('ravi_kumar', 'atorvastatin', '21:00'),
    ('meera_iyer', 'sertraline', '09:00'),
    ('suresh_pillai', 'lisinopril', '08:00'),
    ('suresh_pillai', 'metformin', '08:00'),
    ('suresh_pillai', 'metformin', '20:00'),
    ('lakshmi_nair', 'levothyroxine', '06:30'),
    ('lakshmi_nair', 'alendronate', '07:00'),
    ('arjun_menon', 'sertraline', '09:00'),
    ('fatima_sheikh', 'omeprazole', '07:30'),
    ('fatima_sheikh', 'montelukast', '21:00'),
    ('george_thomas', 'metoprolol', '08:00'),
    ('george_thomas', 'metoprolol', '20:00'),
    ('priyanka_das', 'sitagliptin', '08:00'),
    ('vikram_reddy', 'atorvastatin', '21:00'),
    ('vikram_reddy', 'amlodipine', '08:00'),
    ('nisha_kapoor', 'alprazolam', '22:00'),
    ('anand_joshi', 'digoxin', '08:00'),
    ('anand_joshi', 'furosemide', '08:00'),
]

AUDIT_SEED = [
    {
        'patient_id': 'ananya',
        'recommendation_type': 'regimen_analysis',
        'input_state': {
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 5, 'frequency_per_day': 1}],
            'dietary_factors': ['vitamin_k'],
        },
        'output': {
            'safety_violations': [
                {'severity': 'high', 'drug': 'warfarin', 'with': 'vitamin_k',
                 'mechanism': 'Vitamin K antagonises VKORC1 inhibition, reducing anticoagulant effect'},
            ],
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'suresh_pillai',
        'recommendation_type': 'regimen_analysis',
        'input_state': {
            'prescriptions': [
                {'drug_name': 'lisinopril', 'dose_mg': 10, 'frequency_per_day': 1},
                {'drug_name': 'metformin', 'dose_mg': 500, 'frequency_per_day': 2},
            ],
            'dietary_factors': [],
        },
        'output': {
            'safety_violations': [
                {'severity': 'moderate', 'drug': 'metformin', 'with': 'alcohol',
                 'mechanism': 'Alcohol potentiates lactic acidosis risk with metformin in hepatic impairment'},
            ],
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'ravi_kumar',
        'recommendation_type': 'prescription_suggestion',
        'input_state': {'diagnosis': 'hypertension, elderly, reduced renal function'},
        'output': {
            'suggestions': [{'drug': 'Amlodipine', 'dose_mg': 5, 'frequency_per_day': 1}],
            'is_consult_fallback': False,
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'lakshmi_nair',
        'recommendation_type': 'regimen_analysis',
        'input_state': {
            'prescriptions': [
                {'drug_name': 'levothyroxine', 'dose_mg': 0.075, 'frequency_per_day': 1},
                {'drug_name': 'alendronate', 'dose_mg': 70, 'frequency_per_day': 1},
            ],
            'dietary_factors': ['calcium'],
        },
        'output': {
            'safety_violations': [
                {'severity': 'moderate', 'drug': 'levothyroxine', 'with': 'calcium_carbonate',
                 'mechanism': 'Calcium reduces levothyroxine absorption if taken within 4 hours'},
            ],
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'anand_joshi',
        'recommendation_type': 'regimen_analysis',
        'input_state': {
            'prescriptions': [
                {'drug_name': 'digoxin', 'dose_mg': 0.125, 'frequency_per_day': 1},
                {'drug_name': 'furosemide', 'dose_mg': 40, 'frequency_per_day': 1},
            ],
            'dietary_factors': [],
        },
        'output': {
            'safety_violations': [
                {'severity': 'high', 'drug': 'digoxin', 'with': 'furosemide',
                 'mechanism': 'Furosemide-induced hypokalaemia increases digoxin toxicity risk in narrow-TI elderly patient'},
            ],
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'fatima_sheikh',
        'recommendation_type': 'regimen_analysis',
        'input_state': {
            'prescriptions': [
                {'drug_name': 'omeprazole', 'dose_mg': 20, 'frequency_per_day': 1},
                {'drug_name': 'montelukast', 'dose_mg': 10, 'frequency_per_day': 1},
            ],
            'dietary_factors': [],
        },
        'output': {'safety_violations': [], 'decision_support_only': True},
    },
    {
        'patient_id': 'vikram_reddy',
        'recommendation_type': 'regimen_analysis',
        'input_state': {
            'prescriptions': [
                {'drug_name': 'atorvastatin', 'dose_mg': 20, 'frequency_per_day': 1},
                {'drug_name': 'amlodipine', 'dose_mg': 5, 'frequency_per_day': 1},
            ],
            'dietary_factors': ['grapefruit'],
        },
        'output': {
            'safety_violations': [
                {'severity': 'moderate', 'drug': 'atorvastatin', 'with': 'grapefruit',
                 'mechanism': 'Grapefruit inhibits CYP3A4, raising atorvastatin plasma levels'},
            ],
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'george_thomas',
        'recommendation_type': 'prescription_suggestion',
        'input_state': {'diagnosis': 'arrhythmia, palpitations'},
        'output': {
            'suggestions': [{'drug': 'Bisoprolol', 'dose_mg': 5, 'frequency_per_day': 1}],
            'is_consult_fallback': False,
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'priyanka_das',
        'recommendation_type': 'prescription_suggestion',
        'input_state': {'diagnosis': 'diabetes, t2dm'},
        'output': {
            'suggestions': [{'drug': 'Sitagliptin', 'dose_mg': 100, 'frequency_per_day': 1}],
            'is_consult_fallback': False,
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'nisha_kapoor',
        'recommendation_type': 'regimen_analysis',
        'input_state': {
            'prescriptions': [{'drug_name': 'alprazolam', 'dose_mg': 0.25, 'frequency_per_day': 1}],
            'dietary_factors': ['alcohol'],
        },
        'output': {
            'safety_violations': [
                {'severity': 'high', 'drug': 'alprazolam', 'with': 'alcohol',
                 'mechanism': 'CNS depressant synergy — additive sedation and respiratory depression risk'},
            ],
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'arjun_menon',
        'recommendation_type': 'prescription_suggestion',
        'input_state': {'diagnosis': 'depression, mdd'},
        'output': {
            'suggestions': [{'drug': 'Sertraline', 'dose_mg': 50, 'frequency_per_day': 1}],
            'is_consult_fallback': False,
            'decision_support_only': True,
        },
    },
    {
        'patient_id': 'meera_iyer',
        'recommendation_type': 'regimen_analysis',
        'input_state': {
            'prescriptions': [{'drug_name': 'sertraline', 'dose_mg': 50, 'frequency_per_day': 1}],
            'dietary_factors': [],
        },
        'output': {'safety_violations': [], 'decision_support_only': True},
    },
    {
        'patient_id': 'ananya',
        'recommendation_type': 'prescription_suggestion',
        'input_state': {'diagnosis': 'high cholesterol, statin'},
        'output': {
            'suggestions': [{'drug': 'Atorvastatin', 'dose_mg': 20, 'frequency_per_day': 1}],
            'is_consult_fallback': False,
            'decision_support_only': True,
        },
    },
]


class Command(BaseCommand):
    help = 'Seed extra demo patients, adherence history, and audit trail entries'

    def handle(self, *args, **options):
        # ── Extra patients ──────────────────────────────────────────
        for p in EXTRA_PATIENTS:
            _, created = Patient.objects.get_or_create(patient_key=p['patient_key'], defaults=p)
            self.stdout.write(
                f"{'Created' if created else 'Exists'}: patient {p['patient_key']} ({p['name']})"
            )

        # ── Adherence history — past 7 days per scheduled dose ─────
        now = timezone.now()
        created_count = 0
        for patient_key, drug, sched_time in ADHERENCE_SCHEDULE:
            patient = Patient.objects.filter(patient_key=patient_key).first()
            if not patient:
                continue
            for day_offset in range(7, 0, -1):
                target_date = (now - timedelta(days=day_offset)).date()
                if AdherenceEvent.objects.filter(
                    patient=patient, drug=drug, scheduled_time=sched_time,
                    taken_at__date=target_date,
                ).exists():
                    continue
                # Weighted realistic adherence: mostly taken, occasional late/skipped
                status = random.choices(
                    ['taken', 'late', 'skipped'], weights=[0.78, 0.15, 0.07], k=1
                )[0]
                event = AdherenceEvent.objects.create(
                    patient=patient,
                    drug=drug,
                    scheduled_time=sched_time,
                    rx_id=f'rx_{drug}_{sched_time.replace(":", "")}',
                    status=status,
                )
                # taken_at is auto_now_add — backdate it after creation so the
                # 7-day history actually spans distinct days, not "today" x7.
                hh, mm = (int(x) for x in sched_time.split(':'))
                backdated = (now - timedelta(days=day_offset)).replace(
                    hour=hh, minute=mm, second=0, microsecond=0
                )
                AdherenceEvent.objects.filter(pk=event.pk).update(taken_at=backdated)
                created_count += 1
        self.stdout.write(f'Created {created_count} adherence events.')

        # ── Audit trail entries ─────────────────────────────────────
        audit_created = 0
        for entry in AUDIT_SEED:
            exists = AuditEntry.objects.filter(
                patient_id=entry['patient_id'],
                recommendation_type=entry['recommendation_type'],
            ).exists()
            if not exists:
                AuditEntry.objects.create(
                    patient_id=entry['patient_id'],
                    recommendation_type=entry['recommendation_type'],
                    engine_version='1.0.0',
                    drug_db_version='1.0.0',
                    input_state=entry['input_state'],
                    output=entry['output'],
                    reasoning_chain=None,
                )
                audit_created += 1
        self.stdout.write(f'Created {audit_created} audit entries.')

        self.stdout.write(self.style.SUCCESS('Demo data seeding complete.'))
