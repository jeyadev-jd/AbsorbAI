import uuid
import json
from django.db import models
from django.contrib.auth.models import AbstractUser


class AbsorbUser(AbstractUser):
    ROLE_CHOICES = [
        ('patient', 'Patient'),
        ('doctor', 'Doctor'),
        ('pharmacist', 'Pharmacist'),
        ('admin', 'Admin'),
        ('system', 'System'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='patient')
    tenant = models.CharField(max_length=100, default='default')
    patient_key = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = 'absorb_user'


class Patient(models.Model):
    patient_key = models.CharField(max_length=100, unique=True)
    tenant = models.CharField(max_length=100, default='default', db_index=True)
    name = models.CharField(max_length=200)
    age = models.FloatField(default=45)
    weight = models.FloatField(default=70)
    height = models.FloatField(default=170)
    sex = models.CharField(max_length=1, default='M')
    serum_creatinine = models.FloatField(default=1.0)
    child_pugh_score = models.IntegerField(default=5)
    body_fat_pct = models.FloatField(default=20.0)
    plasma_albumin = models.FloatField(default=4.0)
    gut_motility_score = models.FloatField(default=1.0)
    hydration_score = models.FloatField(default=1.0)
    is_sick = models.BooleanField(default=False)
    alcohol_last_24h = models.BooleanField(default=False)
    cyp3a4_activity = models.FloatField(default=1.0)
    cyp2d6_activity = models.FloatField(default=1.0)
    cyp2c9_activity = models.FloatField(default=1.0)
    cyp2c19_activity = models.FloatField(default=1.0)
    cyp1a2_activity = models.FloatField(default=1.0)
    cyp2e1_activity = models.FloatField(default=1.0)
    wake_time_hr = models.FloatField(default=6.5)
    sleep_time_hr = models.FloatField(default=22.5)
    meal_times_hr = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'absorb_patient'

    def to_profile_dict(self):
        return {
            'name': self.name,
            'age': self.age,
            'weight': self.weight,
            'height': self.height,
            'sex': self.sex,
            'serum_creatinine': self.serum_creatinine,
            'child_pugh_score': self.child_pugh_score,
            'body_fat_pct': self.body_fat_pct,
            'plasma_albumin': self.plasma_albumin,
            'gut_motility_score': self.gut_motility_score,
            'hydration_score': self.hydration_score,
            'is_sick': self.is_sick,
            'alcohol_last_24h': self.alcohol_last_24h,
            'cyp3a4_activity': self.cyp3a4_activity,
            'cyp2d6_activity': self.cyp2d6_activity,
            'cyp2c9_activity': self.cyp2c9_activity,
            'cyp2c19_activity': self.cyp2c19_activity,
            'cyp1a2_activity': self.cyp1a2_activity,
            'cyp2e1_activity': self.cyp2e1_activity,
            'wake_time_hr': self.wake_time_hr,
            'sleep_time_hr': self.sleep_time_hr,
            'meal_times_hr': self.meal_times_hr,
        }


class PKPrior(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='pk_priors')
    drug_name = models.CharField(max_length=100, db_index=True)
    posterior_json = models.JSONField(default=dict)
    n_observations = models.IntegerField(default=0)
    engine_version = models.CharField(max_length=50, default='1.0.0')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'absorb_pk_prior'
        unique_together = ('patient', 'drug_name')


class AdherenceEvent(models.Model):
    STATUS_CHOICES = [('taken', 'Taken'), ('skipped', 'Skipped'), ('late', 'Late')]
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='adherence_events')
    rx_id = models.CharField(max_length=100, blank=True)
    drug = models.CharField(max_length=100, db_index=True)
    scheduled_time = models.CharField(max_length=50, blank=True)
    taken_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='taken')

    class Meta:
        db_table = 'absorb_adherence_event'
        ordering = ['-taken_at']


class EngineRun(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, related_name='engine_runs')
    patient_id_str = models.CharField(max_length=100, db_index=True)
    tenant = models.CharField(max_length=100, default='default', db_index=True)
    input_hash = models.CharField(max_length=64)
    n_monte_carlo = models.IntegerField(default=100)
    engine_version = models.CharField(max_length=50, default='1.0.0')
    drug_db_version = models.CharField(max_length=50, default='1.0.0')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    result_json = models.JSONField(null=True, blank=True)
    error_msg = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'absorb_engine_run'
        ordering = ['-created_at']


class AuditEntry(models.Model):
    patient_id = models.CharField(max_length=100, db_index=True)
    tenant = models.CharField(max_length=100, default='default', db_index=True)
    recommendation_type = models.CharField(max_length=100)
    engine_version = models.CharField(max_length=50, default='1.0.0')
    drug_db_version = models.CharField(max_length=50, default='1.0.0')
    input_state = models.JSONField(default=dict)
    output = models.JSONField(default=dict)
    reasoning_chain = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'absorb_audit_entry'
        ordering = ['-created_at']
