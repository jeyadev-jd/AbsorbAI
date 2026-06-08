from django.core.management.base import BaseCommand
from core.models import AbsorbUser, Patient


DEMO_USERS = [
    {
        'email': 'patient@demo.com',
        'password': 'patient123',
        'role': 'patient',
        'first_name': 'Ananya',
        'last_name': 'Rao',
        'patient_key': 'ananya',
        'tenant': 'default',
    },
    {
        'email': 'doctor@demo.com',
        'password': 'doctor123',
        'role': 'doctor',
        'first_name': 'Priya',
        'last_name': 'Mehta',
        'patient_key': None,
        'tenant': 'default',
    },
]

DEMO_PATIENT = {
    'patient_key': 'ananya',
    'name': 'Ananya Rao',
    'age': 42, 'weight': 58, 'height': 162, 'sex': 'F',
    'serum_creatinine': 0.9, 'child_pugh_score': 5,
    'body_fat_pct': 24, 'plasma_albumin': 4.1,
    'gut_motility_score': 1.0, 'hydration_score': 1.0,
    'is_sick': False, 'alcohol_last_24h': False,
    'cyp3a4_activity': 1.0, 'cyp2d6_activity': 1.0,
    'cyp2c9_activity': 1.0, 'cyp2c19_activity': 1.0,
    'cyp1a2_activity': 1.0, 'cyp2e1_activity': 1.0,
    'wake_time_hr': 6.5, 'sleep_time_hr': 22.5,
    'meal_times_hr': [7.5, 13.0, 19.5],
}


class Command(BaseCommand):
    help = 'Seed demo users and patient profile'

    def handle(self, *args, **options):
        for u in DEMO_USERS:
            if not AbsorbUser.objects.filter(email=u['email']).exists():
                user = AbsorbUser.objects.create_user(
                    username=u['email'],
                    email=u['email'],
                    password=u['password'],
                    first_name=u['first_name'],
                    last_name=u['last_name'],
                    role=u['role'],
                    patient_key=u['patient_key'],
                    tenant=u['tenant'],
                )
                self.stdout.write(f"Created user: {u['email']} ({u['role']})")
            else:
                self.stdout.write(f"User exists: {u['email']}")

        Patient.objects.get_or_create(patient_key='ananya', defaults=DEMO_PATIENT)
        self.stdout.write('Demo patient seeded.')
        self.stdout.write(self.style.SUCCESS('Seeding complete.'))
