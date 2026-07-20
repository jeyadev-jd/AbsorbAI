from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth import authenticate
from django.utils import timezone
import jwt
import datetime
import json
import hashlib
import functools

from .models import Patient, AdherenceEvent, EngineRun, AuditEntry, AbsorbUser

JWT_SECRET = settings.SECRET_KEY
ENGINE_VERSION = getattr(settings, 'ENGINE_VERSION', '1.0.0')
DRUG_DB_VERSION = getattr(settings, 'DRUG_DB_VERSION', '1.0.0')

import logging
_logger = logging.getLogger(__name__)


def _persist_audit(recommendation_type, patient_id, input_state, output, reasoning_chain=None):
    """Log to both in-memory GLOBAL_AUDIT_LOG and DB AuditEntry."""
    try:
        from .engine.explainability import GLOBAL_AUDIT_LOG
        GLOBAL_AUDIT_LOG.log_recommendation(
            recommendation_type=recommendation_type,
            patient_id=patient_id,
            input_state=input_state,
            output=output,
            reasoning_chain=reasoning_chain,
        )
    except Exception:
        pass
    try:
        chain_data = reasoning_chain.to_dict() if reasoning_chain and hasattr(reasoning_chain, 'to_dict') else reasoning_chain
        AuditEntry.objects.create(
            patient_id=patient_id,
            recommendation_type=recommendation_type,
            engine_version=ENGINE_VERSION,
            drug_db_version=DRUG_DB_VERSION,
            input_state=input_state,
            output=output,
            reasoning_chain=chain_data,
        )
    except Exception as e:
        _logger.warning('AuditEntry write failed: %s', e)

_DISCLAIMER = (
    "FOR DECISION SUPPORT ONLY. This output does not constitute medical advice, "
    "diagnosis, or treatment. All clinical decisions require a licensed healthcare "
    "professional. AbsorbAI accepts no liability for clinical outcomes."
)


def _dsr(data: dict) -> dict:
    data.setdefault('decision_support_only', True)
    data.setdefault('disclaimer', _DISCLAIMER)
    return data


# ── Auth helpers ──────────────────────────────────────────────────────────────

def verify_jwt_cookie(request, required_role=None):
    token = request.COOKIES.get('jwt_token')
    if not token:
        return False
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        if required_role and decoded.get('role') != required_role:
            return False
        return decoded
    except Exception:
        return False


def require_role(*roles):
    """Decorator: reject requests whose JWT role is not in `roles`."""
    def decorator(view_func):
        @functools.wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            token = request.COOKIES.get('jwt_token') or request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '')
            if not token:
                return JsonResponse({'success': False, 'message': 'Authentication required'}, status=401)
            try:
                decoded = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            except Exception:
                return JsonResponse({'success': False, 'message': 'Invalid token'}, status=401)
            if roles and decoded.get('role') not in roles:
                return JsonResponse({'success': False, 'message': 'Insufficient role'}, status=403)
            request.jwt_payload = decoded
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


# ── Patient helpers ───────────────────────────────────────────────────────────

_DEMO_ANANYA = {
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


def _get_or_create_demo_patient(patient_key: str) -> Patient:
    """Get patient from DB; seed demo patient if first run."""
    try:
        return Patient.objects.get(patient_key=patient_key)
    except Patient.DoesNotExist:
        if patient_key == 'ananya':
            p = Patient(patient_key='ananya', **_DEMO_ANANYA)
            p.save()
            return p
        raise


def _get_patient_or_404(patient_key: str):
    """Return (patient, None) or (None, JsonResponse 400/404)."""
    if not patient_key or not patient_key.strip():
        return None, JsonResponse({'success': False, 'message': 'patient_key is required'}, status=400)
    try:
        return Patient.objects.get(patient_key=patient_key), None
    except Patient.DoesNotExist:
        if patient_key == 'ananya':
            p = Patient(patient_key='ananya', **_DEMO_ANANYA)
            p.save()
            return p, None
        return None, JsonResponse({'success': False, 'message': f'Patient not found: {patient_key}'}, status=404)


def _get_patient_profile(patient_key: str) -> dict:
    try:
        return _get_or_create_demo_patient(patient_key).to_profile_dict()
    except Patient.DoesNotExist:
        return _DEMO_ANANYA.copy()


# ── Cache (in-memory, Redis-backed via Django cache framework) ────────────────

from django.core.cache import cache as _django_cache


def _cache_key(patient_id: str, prescriptions: list, dietary: list) -> str:
    payload = json.dumps({'p': patient_id, 'rx': prescriptions, 'd': sorted(dietary)},
                         sort_keys=True, default=str)
    return 'engine:' + hashlib.sha256(payload.encode()).hexdigest()[:24]


# ── Views ─────────────────────────────────────────────────────────────────────

@csrf_exempt
def api_login(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        role = data.get('role', '').strip()

        if not email:
            return JsonResponse({'success': False, 'message': 'email is required'}, status=400)
        if not password:
            return JsonResponse({'success': False, 'message': 'password is required'}, status=400)
        if not role:
            return JsonResponse({'success': False, 'message': 'role is required'}, status=400)

        # Try DB auth first
        user = None
        try:
            db_user = AbsorbUser.objects.get(email=email)
            if db_user.check_password(password) and db_user.role == role:
                user = db_user
        except AbsorbUser.DoesNotExist:
            pass

        if not user:
            return JsonResponse({'success': False, 'message': 'Invalid credentials.'}, status=401)

        payload = {
            'email': user.email,
            'role': user.role,
            'fname': user.first_name,
            'name': user.get_full_name() or user.first_name,
            'patientKey': user.patient_key,
            'tenant': user.tenant,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=2),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
        user_info = {
            'email': user.email, 'role': user.role,
            'fname': user.first_name, 'name': payload['name'],
            'patientKey': user.patient_key,
        }
        response = JsonResponse({'success': True, 'user': user_info})
        response.set_cookie('jwt_token', token, httponly=False, samesite='Lax')
        return response
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


@csrf_exempt
def api_signup(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required'}, status=405)
    try:
        import re
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        role = data.get('role', '').strip()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        registration_number = data.get('registration_number', '').strip()

        if not email or not password or not role or not first_name or not last_name:
            return JsonResponse({'success': False, 'message': 'All fields are required.'}, status=400)

        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            return JsonResponse({'success': False, 'message': 'Please enter a valid email address.'}, status=400)

        if len(password) < 8:
            return JsonResponse({'success': False, 'message': 'Password must be at least 8 characters.'}, status=400)

        if role not in ('patient', 'doctor'):
            return JsonResponse({'success': False, 'message': 'Invalid role.'}, status=400)

        if role == 'doctor' and not registration_number:
            return JsonResponse({'success': False, 'message': 'Medical registration number required.'}, status=400)

        if AbsorbUser.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'message': 'An account with this email already exists.'}, status=409)

        patient_key = first_name.lower() if role == 'patient' else None
        user = AbsorbUser.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            patient_key=patient_key,
        )

        if role == 'patient':
            Patient.objects.get_or_create(
                patient_key=patient_key,
                defaults={'name': f'{first_name} {last_name}', 'tenant': 'default'},
            )

        full_name = (('Dr. ' if role == 'doctor' else '') + first_name + ' ' + last_name).strip()
        payload = {
            'email': user.email,
            'role': user.role,
            'fname': user.first_name,
            'name': full_name,
            'patientKey': user.patient_key,
            'tenant': user.tenant,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=2),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
        user_info = {
            'email': user.email, 'role': user.role,
            'fname': user.first_name, 'name': full_name,
            'patientKey': user.patient_key,
        }
        response = JsonResponse({'success': True, 'user': user_info})
        response.set_cookie('jwt_token', token, httponly=False, samesite='Lax')
        return response
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


@csrf_exempt
def api_logout(request):
    response = JsonResponse({'success': True})
    response.delete_cookie('jwt_token')
    return response


def index(request):
    return render(request, 'index.html', {'initial_page': 'landing'})

def auth_view(request):
    return render(request, 'index.html', {'initial_page': 'auth'})

def patient_view(request):
    decoded = verify_jwt_cookie(request, required_role='patient')
    if not decoded:
        return redirect('/auth/')
    return render(request, 'index.html', {'initial_page': 'patient', 'auth_user': json.dumps(decoded)})

def doctor_view(request):
    decoded = verify_jwt_cookie(request, required_role='doctor')
    if not decoded:
        return redirect('/auth/')
    return render(request, 'index.html', {'initial_page': 'doctor', 'auth_user': json.dumps(decoded)})


# ══════════════════════════════════════════════════════
#  ENGINE API ENDPOINTS
# ══════════════════════════════════════════════════════

@csrf_exempt
@require_role('doctor')
@require_http_methods(['POST'])
def api_analyze_regimen(request):
    """
    Full 10-layer analysis. Enqueues Celery hi-fi run in background.
    POST: {patient_id, patient_profile, prescriptions, dietary_factors, async_hifi}
    """
    try:
        from .engine.orchestrator import analyze_patient_regimen
        data = json.loads(request.body)
        patient_id = data.get('patient_id', 'demo')
        patient_key = data.get('patient_key', patient_id)
        patient_profile = data.get('patient_profile') or _get_patient_profile(patient_key)
        if patient_profile and not isinstance(patient_profile, dict):
            return JsonResponse({'success': False, 'message': 'patient_profile must be a JSON object'}, status=400)
        prescriptions = data.get('prescriptions', [])
        if not isinstance(prescriptions, list):
            return JsonResponse({'success': False, 'message': 'prescriptions must be a list'}, status=400)
        dietary_factors = data.get('dietary_factors', [])
        if not isinstance(dietary_factors, list):
            return JsonResponse({'success': False, 'message': 'dietary_factors must be a list'}, status=400)

        if not prescriptions:
            return JsonResponse({'success': False, 'message': 'No prescriptions provided'}, status=400)

        for i, rx in enumerate(prescriptions):
            drug_name = rx.get('drug_name') or rx.get('drug') or rx.get('name', '')
            if not drug_name:
                return JsonResponse({'success': False, 'message': f'Prescription {i}: drug name is required'}, status=400)
            dose = rx.get('dose_mg', rx.get('dose'))
            if dose is not None:
                try:
                    dose = float(dose)
                except (TypeError, ValueError):
                    return JsonResponse({'success': False, 'message': f'Prescription {i}: dose must be a number'}, status=400)
                if dose <= 0:
                    return JsonResponse({'success': False, 'message': f'Prescription {i}: dose must be positive'}, status=400)

        ck = _cache_key(patient_id, prescriptions, dietary_factors)
        cached = _django_cache.get(ck)
        if cached:
            cached['from_cache'] = True
            return JsonResponse({'success': True, 'data': cached})

        result = analyze_patient_regimen(
            patient_id=patient_id,
            patient_profile=patient_profile,
            prescriptions=prescriptions,
            dietary_factors=dietary_factors,
            n_monte_carlo=100,
        )
        result = _dsr(result)
        _django_cache.set(ck, result, timeout=600)

        # Persist EngineRun record
        try:
            patient_obj = Patient.objects.filter(patient_key=patient_key).first()
            run = EngineRun.objects.create(
                patient=patient_obj,
                patient_id_str=patient_id,
                input_hash=ck,
                n_monte_carlo=100,
                engine_version=ENGINE_VERSION,
                drug_db_version=DRUG_DB_VERSION,
                status='done',
                result_json=result,
                completed_at=timezone.now(),
            )
            result['run_id'] = str(run.id)
        except Exception:
            pass

        # Audit trail — compliance-critical persistence
        _persist_audit(
            recommendation_type='regimen_analysis',
            patient_id=patient_id,
            input_state={'prescriptions': prescriptions, 'dietary_factors': dietary_factors},
            output={'safety_violations': result.get('safety_violations', []),
                    'interaction_count': len(result.get('interaction_chains', [])),
                    'schedule_count': len(result.get('schedule', []))},
            reasoning_chain=result.get('reasoning_chains', [None])[0] if result.get('reasoning_chains') else None,
        )

        # Enqueue hi-fidelity Celery task
        try:
            from .tasks import run_hifi_analysis
            task = run_hifi_analysis.delay(patient_id, patient_key, patient_profile, prescriptions, dietary_factors, ck)
        except Exception:
            import threading
            def _bg():
                try:
                    hi = analyze_patient_regimen(patient_id=patient_id, patient_profile=patient_profile,
                                                  prescriptions=prescriptions, dietary_factors=dietary_factors, n_monte_carlo=500)
                    hi = _dsr(hi)
                    hi['high_fidelity'] = True
                    _django_cache.set(ck, hi, timeout=600)
                except Exception:
                    pass
            threading.Thread(target=_bg, daemon=True).start()

        return JsonResponse({'success': True, 'data': result})
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('analyze_regimen failed')
        msg = str(e) if settings.DEBUG else 'Internal server error'
        return JsonResponse({'success': False, 'message': msg}, status=500)


@csrf_exempt
@require_role('doctor')
@require_http_methods(['GET'])
def api_engine_run_status(request, run_id):
    """GET /api/engine/run/<uuid>/status/ — poll Celery job result."""
    try:
        run = EngineRun.objects.get(id=run_id)
        data = {'run_id': str(run.id), 'status': run.status}
        if run.status == 'done' and run.result_json:
            data['result'] = run.result_json
        elif run.status == 'failed':
            data['error'] = run.error_msg
        return JsonResponse({'success': True, 'data': data})
    except EngineRun.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Run not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_role('doctor')
@require_http_methods(['POST'])
def api_update_observation(request):
    """Layer 8: Bayesian update. POST: {patient_id, drug_name, observation_type, observed_value, predicted_value}"""
    try:
        from .engine.orchestrator import update_patient_observation
        data = json.loads(request.body)
        patient_id = data.get('patient_id', '').strip() if isinstance(data.get('patient_id'), str) else str(data.get('patient_id', ''))
        drug_name = data.get('drug_name', '').strip() if isinstance(data.get('drug_name'), str) else ''
        if not patient_id:
            return JsonResponse({'success': False, 'message': 'patient_id is required'}, status=400)
        if not drug_name:
            return JsonResponse({'success': False, 'message': 'drug_name is required'}, status=400)
        observed_value = data.get('observed_value')
        if observed_value is None:
            return JsonResponse({'success': False, 'message': 'observed_value is required'}, status=400)
        try:
            observed_value = float(observed_value)
        except (TypeError, ValueError):
            return JsonResponse({'success': False, 'message': 'observed_value must be a number'}, status=400)
        result = update_patient_observation(
            patient_id=patient_id,
            drug_name=drug_name,
            observation_type=data.get('observation_type', 'concentration'),
            observed_value=float(data.get('observed_value', 0)),
            predicted_value=float(data.get('predicted_value', 0)) if data.get('predicted_value') else None,
            lab_name=data.get('lab_name'),
            lab_unit=data.get('lab_unit'),
        )
        return JsonResponse({'success': True, 'data': _dsr(result)})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_role('doctor')
@require_http_methods(['POST'])
def api_prescription_suggestions(request):
    """Gemma + KG suggestions. POST: {patient_id, diagnosis, current_drugs, patient_profile}"""
    try:
        from .engine.orchestrator import get_prescription_suggestions
        data = json.loads(request.body)
        diagnosis = data.get('diagnosis', '').strip() if isinstance(data.get('diagnosis'), str) else ''
        if not diagnosis:
            return JsonResponse({'success': False, 'message': 'diagnosis is required'}, status=400)
        suggestions = get_prescription_suggestions(
            patient_id=data.get('patient_id', ''),
            diagnosis=diagnosis,
            current_drugs=data.get('current_drugs', []),
            patient_profile=data.get('patient_profile', {}),
        )
        return JsonResponse(_dsr({'success': True, 'suggestions': suggestions}))
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_role('doctor')
@require_http_methods(['GET'])
def api_audit_log(request):
    """Layer 10: audit log. Reads DB AuditEntry table."""
    try:
        patient_id = request.GET.get('patient_id', '').strip()
        if not patient_id:
            return JsonResponse({'success': False, 'message': 'patient_id is required'}, status=400)
        qs = AuditEntry.objects.filter(patient_id=patient_id).order_by('-created_at')[:50]
        entries = [
            {
                'patient_id': e.patient_id,
                'recommendation_type': e.recommendation_type,
                'engine_version': e.engine_version,
                'drug_db_version': e.drug_db_version,
                'input_state': e.input_state,
                'output': e.output,
                'reasoning_chain': e.reasoning_chain,
                'created_at': e.created_at.isoformat(),
            }
            for e in qs
        ]
        # Also pull from in-process GLOBAL_AUDIT_LOG for current session entries not yet persisted
        try:
            from .engine.explainability import GLOBAL_AUDIT_LOG
            mem_entries = GLOBAL_AUDIT_LOG.get_patient_history(patient_id)
            db_timestamps = {e['created_at'] for e in entries}
            mem_entries = [m for m in mem_entries if m.get('timestamp') not in db_timestamps]
            entries = mem_entries[-20:] + entries
        except Exception:
            pass
        return JsonResponse({'success': True, 'entries': entries[-20:]})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_role('patient', 'doctor')
@require_http_methods(['GET'])
def api_patient_profile(request):
    patient_key = request.GET.get('patient_key', '').strip()
    if not patient_key:
        return JsonResponse({'success': False, 'message': 'patient_key is required'}, status=400)
    patient, err = _get_patient_or_404(patient_key)
    if err:
        return err
    return JsonResponse({'success': True, 'profile': patient.to_profile_dict()})


@csrf_exempt
@require_role('doctor')
@require_http_methods(['POST'])
def api_update_patient_profile(request):
    try:
        data = json.loads(request.body)
        patient_key = data.get('patient_key', '').strip()
        if not patient_key:
            return JsonResponse({'success': False, 'message': 'patient_key is required'}, status=400)
        updates = data.get('updates', {})

        patient, err = _get_patient_or_404(patient_key)
        if err:
            return err
        allowed = {f.name for f in Patient._meta.fields} - {'id', 'patient_key', 'tenant', 'created_at', 'updated_at'}
        for k, v in updates.items():
            if k in allowed:
                setattr(patient, k, v)
        patient.save()

        # Reset Bayesian updaters for this patient
        try:
            from .engine.orchestrator import _PATIENT_UPDATERS
            if patient_key in _PATIENT_UPDATERS:
                del _PATIENT_UPDATERS[patient_key]
        except Exception:
            pass

        return JsonResponse({'success': True, 'profile': patient.to_profile_dict()})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_role('patient', 'doctor')
@require_http_methods(['GET'])
def api_drug_search(request):
    try:
        from .drugdb.drug_data import DRUGS
        query = request.GET.get('q', '').lower().strip()
        limit = min(int(request.GET.get('limit', 20)), 50)
        detail = request.GET.get('detail', 'false').lower() == 'true'

        results = []
        for name, info in DRUGS.items():
            brands = [b.lower() for b in info.get('brand', [])]
            if not query or query in name or any(query in b for b in brands):
                entry = {
                    'name': name, 'brand': info.get('brand', []),
                    'class': info.get('class', ''), 'subclass': info.get('subclass', ''),
                    'narrow_ti': info.get('narrow_ti', False),
                    'primary_enzyme': info.get('primary_enzyme'),
                    'half_life_hr': info.get('half_life_hr'),
                }
                if detail:
                    entry.update({
                        'mechanism': info.get('mechanism', ''),
                        'monitoring': info.get('monitoring', []),
                        'food_effect': info.get('food_effect', ''),
                        'max_daily_dose_mg': info.get('max_daily_dose_mg'),
                        'therapeutic_range': info.get('therapeutic_range', ''),
                        'pregnancy_cat': info.get('pregnancy_cat', ''),
                        'contraindications': info.get('contraindications', []),
                    })
                results.append(entry)
                if len(results) >= limit:
                    break
        return JsonResponse({'success': True, 'count': len(results), 'drugs': results})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_role('patient', 'doctor')
@require_http_methods(['GET'])
def api_drug_interactions(request):
    try:
        from .drugdb.drug_data import DRUG_INTERACTIONS as _H_DDI, FOOD_DRUG_INTERACTIONS as _H_FDI
        try:
            from .drugdb.ddi_database import DRUG_INTERACTIONS as _A_DDI, FOOD_DRUG_INTERACTIONS as _A_FDI
        except ImportError:
            _A_DDI, _A_FDI = [], []
        _hkeys = {tuple(sorted([r['drug_a'], r['drug_b']])) for r in _H_DDI}
        _hfkeys = {(r['drug'], r['food']) for r in _H_FDI}
        DRUG_INTERACTIONS = _H_DDI + [r for r in _A_DDI if tuple(sorted([r['drug_a'], r['drug_b']])) not in _hkeys]
        FOOD_DRUG_INTERACTIONS = _H_FDI + [r for r in _A_FDI if (r['drug'], r['food']) not in _hfkeys]
        drug = request.GET.get('drug', '').lower().strip()
        if not drug:
            return JsonResponse({'success': False, 'message': 'drug parameter required'}, status=400)

        ddi = [r for r in DRUG_INTERACTIONS if r['drug_a'].lower() == drug or r['drug_b'].lower() == drug]
        fdi = [r for r in FOOD_DRUG_INTERACTIONS if r['drug'].lower() == drug]

        def _norm_ddi(r):
            raw_sev = r.get('severity', 0.5)
            sev_label = 'high' if isinstance(raw_sev, float) and raw_sev >= 0.75 else \
                        'moderate' if isinstance(raw_sev, float) and raw_sev >= 0.45 else \
                        str(raw_sev).lower() if not isinstance(raw_sev, float) else 'low'
            partner = r['drug_b'] if r.get('drug_a', '').lower() == drug else r.get('drug_a', '—')
            return {**r, 'with': partner, 'severity': sev_label,
                    'mechanism': r.get('mechanism', ''), 'management': r.get('management', '')}

        def _norm_fdi(r):
            raw_sev = r.get('severity', 'low')
            sev_label = str(raw_sev).lower() if not isinstance(raw_sev, float) else (
                'high' if raw_sev >= 0.75 else 'moderate' if raw_sev >= 0.45 else 'low')
            return {**r, 'with': r.get('food', '—'), 'severity': sev_label,
                    'mechanism': r.get('mechanism', r.get('effect', ''))}

        norm_ddi = [_norm_ddi(r) for r in ddi]
        norm_fdi = [_norm_fdi(r) for r in fdi]
        return JsonResponse({
            'success': True, 'drug': drug,
            'drug_drug_interactions': norm_ddi, 'food_drug_interactions': norm_fdi,
            'ddi': norm_ddi, 'fdi': norm_fdi,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_role('patient', 'doctor')
@require_http_methods(['POST'])
def api_adherence_log(request):
    """Log dose confirmation. POST: {patient_key, rx_id, drug, scheduled_time, status}"""
    try:
        data = json.loads(request.body)
        patient_key = data.get('patient_key', '').strip()
        if not patient_key:
            return JsonResponse({'success': False, 'message': 'patient_key is required'}, status=400)
        rx_id = data.get('rx_id', '')
        drug = data.get('drug', '').lower().strip()
        scheduled_time = data.get('scheduled_time', '')
        status = data.get('status', 'taken')

        if status not in ('taken', 'skipped', 'late'):
            return JsonResponse({'success': False, 'message': 'Invalid status'}, status=400)
        if not drug:
            return JsonResponse({'success': False, 'message': 'drug required'}, status=400)

        patient, err = _get_patient_or_404(patient_key)
        if err:
            return err
        event = AdherenceEvent.objects.create(
            patient=patient, rx_id=rx_id, drug=drug,
            scheduled_time=scheduled_time, status=status,
        )

        recent = list(AdherenceEvent.objects.filter(patient=patient).order_by('-taken_at')[:30])
        taken_count = sum(1 for e in recent if e.status == 'taken')
        score = round((taken_count / len(recent)) * 100) if recent else 100

        _django_cache.delete(_cache_key(patient_key, [], []))

        _persist_audit(
            recommendation_type='adherence_event',
            patient_id=patient_key,
            input_state={'drug': drug, 'status': status, 'scheduled': scheduled_time},
            output={'adherence_score': score},
        )

        return JsonResponse({
            'success': True,
            'entry': {'rx_id': rx_id, 'drug': drug, 'scheduled_time': scheduled_time,
                      'taken_at': event.taken_at.isoformat(), 'status': status},
            'adherence_score': score,
            'total_logged': AdherenceEvent.objects.filter(patient=patient).count(),
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_role('patient', 'doctor')
@require_http_methods(['GET'])
def api_adherence_history(request):
    try:
        patient_key = request.GET.get('patient_key', '').strip()
        if not patient_key:
            return JsonResponse({'success': False, 'message': 'patient_key is required'}, status=400)
        patient, err = _get_patient_or_404(patient_key)
        if err:
            return err
        recent = list(AdherenceEvent.objects.filter(patient=patient).order_by('-taken_at')[:50])

        taken = sum(1 for e in recent if e.status == 'taken')
        skipped = sum(1 for e in recent if e.status == 'skipped')
        late = sum(1 for e in recent if e.status == 'late')
        score = round((taken / len(recent)) * 100) if recent else 100

        by_drug: dict = {}
        for e in recent:
            if e.drug not in by_drug:
                by_drug[e.drug] = {'taken': 0, 'skipped': 0, 'late': 0}
            by_drug[e.drug][e.status] += 1

        recent_list = [
            {'rx_id': e.rx_id, 'drug': e.drug, 'scheduled_time': e.scheduled_time,
             'taken_at': e.taken_at.isoformat(), 'status': e.status}
            for e in recent[:20]
        ]
        return JsonResponse({
            'success': True, 'patient_key': patient_key, 'adherence_score': score,
            'total_logged': AdherenceEvent.objects.filter(patient=patient).count(),
            'summary': {'taken': taken, 'skipped': skipped, 'late': late},
            'by_drug': by_drug, 'recent': recent_list,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
