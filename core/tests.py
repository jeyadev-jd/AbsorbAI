"""
AbsorbAI Test Suite — API, engine, and validation tests.
Run: python manage.py test core
"""
import json
from django.test import TestCase, Client
from .models import AbsorbUser, Patient, AdherenceEvent, AuditEntry, EngineRun


def _make_user(email, password, role, patient_key=None):
    return AbsorbUser.objects.create_user(
        username=email, email=email, password=password,
        role=role, first_name='Test', last_name='User',
        patient_key=patient_key,
    )


def _login(client, email, password, role):
    return client.post('/api/login/', json.dumps({
        'email': email, 'password': password, 'role': role,
    }), content_type='application/json')


class AuthTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.doc = _make_user('doc@test.com', 'pass1234', 'doctor')
        self.pat = _make_user('pat@test.com', 'pass1234', 'patient', patient_key='testpat')

    def test_login_success_doctor(self):
        r = _login(self.c, 'doc@test.com', 'pass1234', 'doctor')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        self.assertIn('jwt_token', r.cookies)

    def test_login_success_patient(self):
        r = _login(self.c, 'pat@test.com', 'pass1234', 'patient')
        self.assertEqual(r.status_code, 200)

    def test_login_wrong_password(self):
        r = _login(self.c, 'doc@test.com', 'wrong', 'doctor')
        self.assertEqual(r.status_code, 401)

    def test_login_wrong_role(self):
        r = _login(self.c, 'doc@test.com', 'pass1234', 'patient')
        self.assertEqual(r.status_code, 401)

    def test_login_missing_email(self):
        r = self.c.post('/api/login/', json.dumps({'password': 'x', 'role': 'doctor'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_login_missing_password(self):
        r = self.c.post('/api/login/', json.dumps({'email': 'x@x.com', 'role': 'doctor'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_login_missing_role(self):
        r = self.c.post('/api/login/', json.dumps({'email': 'x@x.com', 'password': 'x'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_login_empty_email(self):
        r = self.c.post('/api/login/', json.dumps({'email': '', 'password': 'x', 'role': 'doctor'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_logout(self):
        _login(self.c, 'doc@test.com', 'pass1234', 'doctor')
        r = self.c.post('/api/logout/')
        self.assertEqual(r.status_code, 200)

    def test_login_nonexistent_user(self):
        r = _login(self.c, 'nobody@test.com', 'pass', 'doctor')
        self.assertEqual(r.status_code, 401)


class JWTProtectionTests(TestCase):
    def setUp(self):
        self.c = Client()

    def test_analyze_requires_auth(self):
        r = self.c.post('/api/engine/analyze/', '{}', content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_observation_requires_auth(self):
        r = self.c.post('/api/engine/observation/', '{}', content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_suggestions_requires_auth(self):
        r = self.c.post('/api/engine/suggestions/', '{}', content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_audit_requires_auth(self):
        r = self.c.get('/api/engine/audit/?patient_id=x')
        self.assertEqual(r.status_code, 401)

    def test_profile_requires_auth(self):
        r = self.c.get('/api/patient/profile/?patient_key=x')
        self.assertEqual(r.status_code, 401)

    def test_profile_update_requires_auth(self):
        r = self.c.post('/api/patient/profile/update/', '{}', content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_drug_search_requires_auth(self):
        r = self.c.get('/api/drugs/search/?q=war')
        self.assertEqual(r.status_code, 401)

    def test_drug_interactions_requires_auth(self):
        r = self.c.get('/api/drugs/interactions/?drug=warfarin')
        self.assertEqual(r.status_code, 401)

    def test_adherence_log_requires_auth(self):
        r = self.c.post('/api/adherence/log/', '{}', content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_adherence_history_requires_auth(self):
        r = self.c.get('/api/adherence/history/?patient_key=x')
        self.assertEqual(r.status_code, 401)


class _AuthMixin:
    def setUp(self):
        self.c = Client()
        self.doc = _make_user('doc@test.com', 'docpass12', 'doctor')
        self.pat_user = _make_user('pat@test.com', 'patpass12', 'patient', patient_key='eleanor')
        self.patient = Patient.objects.create(
            patient_key='eleanor', name='Eleanor Test',
            age=65, weight=60, height=165, sex='F',
            serum_creatinine=1.0, child_pugh_score=5,
        )
        _login(self.c, 'doc@test.com', 'docpass12', 'doctor')


class ValidationTests(_AuthMixin, TestCase):
    def test_analyze_no_prescriptions(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor', 'prescriptions': [],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_analyze_missing_drug_name(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor',
            'prescriptions': [{'dose_mg': 5}],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_analyze_negative_dose(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor',
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': -5}],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_analyze_zero_dose(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor',
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 0}],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_analyze_bad_profile_type(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor',
            'patient_profile': 'not a dict',
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 5}],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_analyze_bad_prescriptions_type(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor', 'prescriptions': 'not a list',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_analyze_string_dose(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor',
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 'abc'}],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_patient_profile_missing_key(self):
        r = self.c.get('/api/patient/profile/')
        self.assertEqual(r.status_code, 400)

    def test_patient_profile_empty_key(self):
        r = self.c.get('/api/patient/profile/?patient_key=')
        self.assertEqual(r.status_code, 400)

    def test_patient_profile_not_found(self):
        r = self.c.get('/api/patient/profile/?patient_key=nonexistent_xyz')
        self.assertEqual(r.status_code, 404)

    def test_adherence_missing_patient_key(self):
        r = self.c.post('/api/adherence/log/', json.dumps({
            'drug': 'warfarin', 'status': 'taken',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_adherence_missing_drug(self):
        r = self.c.post('/api/adherence/log/', json.dumps({
            'patient_key': 'eleanor', 'status': 'taken',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_adherence_invalid_status(self):
        r = self.c.post('/api/adherence/log/', json.dumps({
            'patient_key': 'eleanor', 'drug': 'warfarin', 'status': 'invalid',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_adherence_unknown_patient(self):
        r = self.c.post('/api/adherence/log/', json.dumps({
            'patient_key': 'nonexistent_xyz', 'drug': 'warfarin', 'status': 'taken',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 404)

    def test_audit_missing_patient_id(self):
        r = self.c.get('/api/engine/audit/')
        self.assertEqual(r.status_code, 400)

    def test_observation_missing_patient(self):
        r = self.c.post('/api/engine/observation/', json.dumps({
            'drug_name': 'warfarin', 'observed_value': 1.5,
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_observation_missing_drug(self):
        r = self.c.post('/api/engine/observation/', json.dumps({
            'patient_id': 'eleanor', 'observed_value': 1.5,
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_observation_missing_value(self):
        r = self.c.post('/api/engine/observation/', json.dumps({
            'patient_id': 'eleanor', 'drug_name': 'warfarin',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_observation_non_numeric_value(self):
        r = self.c.post('/api/engine/observation/', json.dumps({
            'patient_id': 'eleanor', 'drug_name': 'warfarin', 'observed_value': 'abc',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_suggestions_missing_diagnosis(self):
        r = self.c.post('/api/engine/suggestions/', json.dumps({
            'patient_id': 'eleanor',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_drug_interactions_missing_drug(self):
        r = self.c.get('/api/drugs/interactions/')
        self.assertEqual(r.status_code, 400)


class EngineTests(_AuthMixin, TestCase):
    def test_single_drug_analysis(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor', 'patient_key': 'eleanor',
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 5, 'frequency': 'daily'}],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['success'])
        self.assertIn('data', data)

    def test_analysis_creates_audit_entry(self):
        self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor', 'patient_key': 'eleanor',
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 5, 'frequency': 'daily'}],
        }), content_type='application/json')
        self.assertTrue(AuditEntry.objects.filter(patient_id='eleanor').exists())

    def test_analysis_returns_run_id(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor', 'patient_key': 'eleanor',
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 5, 'frequency': 'daily'}],
        }), content_type='application/json')
        data = r.json()
        self.assertTrue(data['success'])
        if 'run_id' in data.get('data', {}):
            self.assertTrue(EngineRun.objects.filter(id=data['data']['run_id']).exists())


class DrugSearchTests(_AuthMixin, TestCase):
    def test_search_all(self):
        r = self.c.get('/api/drugs/search/')
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()['count'], 0)

    def test_search_specific(self):
        r = self.c.get('/api/drugs/search/?q=warfarin')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any('warfarin' in d['name'].lower() for d in r.json()['drugs']))

    def test_interactions(self):
        r = self.c.get('/api/drugs/interactions/?drug=warfarin')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])


class SuggestionTests(_AuthMixin, TestCase):
    def test_hypertension(self):
        r = self.c.post('/api/engine/suggestions/', json.dumps({
            'diagnosis': 'hypertension', 'current_drugs': [],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        drugs = [s['drug'].lower() for s in r.json()['suggestions']]
        self.assertTrue(any('amlodipine' in d or 'lisinopril' in d for d in drugs))

    def test_diabetes(self):
        r = self.c.post('/api/engine/suggestions/', json.dumps({
            'diagnosis': 'type 2 diabetes', 'current_drugs': [],
        }), content_type='application/json')
        drugs = [s['drug'].lower() for s in r.json()['suggestions']]
        self.assertTrue(any('metformin' in d for d in drugs))

    def test_unknown_diagnosis_fallback(self):
        r = self.c.post('/api/engine/suggestions/', json.dumps({
            'diagnosis': 'rare tropical disease xyz', 'current_drugs': [],
        }), content_type='application/json')
        self.assertTrue(any(s.get('is_consult_fallback') for s in r.json()['suggestions']))

    def test_alias_htn(self):
        r = self.c.post('/api/engine/suggestions/', json.dumps({
            'diagnosis': 'htn', 'current_drugs': [],
        }), content_type='application/json')
        self.assertFalse(any(s.get('is_consult_fallback') for s in r.json()['suggestions']))

    def test_alias_high_blood_pressure(self):
        r = self.c.post('/api/engine/suggestions/', json.dumps({
            'diagnosis': 'high blood pressure', 'current_drugs': [],
        }), content_type='application/json')
        self.assertFalse(any(s.get('is_consult_fallback') for s in r.json()['suggestions']))


class AdherenceTests(_AuthMixin, TestCase):
    def test_log_adherence(self):
        r = self.c.post('/api/adherence/log/', json.dumps({
            'patient_key': 'eleanor', 'drug': 'warfarin',
            'scheduled_time': '08:00', 'status': 'taken',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])

    def test_log_creates_audit(self):
        self.c.post('/api/adherence/log/', json.dumps({
            'patient_key': 'eleanor', 'drug': 'warfarin',
            'scheduled_time': '08:00', 'status': 'taken',
        }), content_type='application/json')
        self.assertTrue(AuditEntry.objects.filter(
            patient_id='eleanor', recommendation_type='adherence_event',
        ).exists())

    def test_adherence_history(self):
        self.c.post('/api/adherence/log/', json.dumps({
            'patient_key': 'eleanor', 'drug': 'warfarin',
            'scheduled_time': '08:00', 'status': 'taken',
        }), content_type='application/json')
        r = self.c.get('/api/adherence/history/?patient_key=eleanor')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['adherence_score'], 100)


class AuditTests(_AuthMixin, TestCase):
    def test_audit_log_responds(self):
        r = self.c.get('/api/engine/audit/?patient_id=eleanor')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])

    def test_audit_persists_after_analysis(self):
        self.c.post('/api/engine/analyze/', json.dumps({
            'patient_id': 'eleanor', 'patient_key': 'eleanor',
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 5}],
        }), content_type='application/json')
        self.assertTrue(AuditEntry.objects.filter(
            patient_id='eleanor', recommendation_type='regimen_analysis',
        ).exists())


class RoleProtectionTests(TestCase):
    def setUp(self):
        self.c = Client()
        _make_user('pat@test.com', 'patpass12', 'patient', patient_key='testpat')
        _login(self.c, 'pat@test.com', 'patpass12', 'patient')

    def test_patient_cannot_analyze(self):
        r = self.c.post('/api/engine/analyze/', json.dumps({
            'prescriptions': [{'drug_name': 'warfarin', 'dose_mg': 5}],
        }), content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_patient_cannot_view_audit(self):
        r = self.c.get('/api/engine/audit/?patient_id=x')
        self.assertEqual(r.status_code, 403)

    def test_patient_can_search_drugs(self):
        r = self.c.get('/api/drugs/search/?q=war')
        self.assertEqual(r.status_code, 200)

    def test_patient_can_log_adherence(self):
        Patient.objects.create(patient_key='testpat', name='Test Pat')
        r = self.c.post('/api/adherence/log/', json.dumps({
            'patient_key': 'testpat', 'drug': 'warfarin',
            'scheduled_time': '08:00', 'status': 'taken',
        }), content_type='application/json')
        self.assertEqual(r.status_code, 200)
