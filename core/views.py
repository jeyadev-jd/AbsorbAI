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

JWT_SECRET = getattr(settings, 'SECRET_KEY', 'absorb-fallback-secret-key')
ENGINE_VERSION = getattr(settings, 'ENGINE_VERSION', '1.0.0')
DRUG_DB_VERSION = getattr(settings, 'DRUG_DB_VERSION', '1.0.0')

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
        email = data.get('email', '').lower()
        password = data.get('password', '')
        role = data.get('role', '')

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
        prescriptions = data.get('prescriptions', [])
        dietary_factors = data.get('dietary_factors', [])

        if not prescriptions:
            return JsonResponse({'success': False, 'message': 'No prescriptions provided'}, status=400)

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
        import traceback
        return JsonResponse({'success': False, 'message': str(e), 'traceback': traceback.format_exc()[-800:]}, status=500)


@csrf_exempt
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
@require_http_methods(['POST'])
def api_update_observation(request):
    """Layer 8: Bayesian update. POST: {patient_id, drug_name, observation_type, observed_value, predicted_value}"""
    try:
        from .engine.orchestrator import update_patient_observation
        data = json.loads(request.body)
        result = update_patient_observation(
            patient_id=data.get('patient_id', ''),
            drug_name=data.get('drug_name', ''),
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
@require_http_methods(['POST'])
def api_prescription_suggestions(request):
    """Gemma + KG suggestions. POST: {patient_id, diagnosis, current_drugs, patient_profile}"""
    try:
        from .engine.orchestrator import get_prescription_suggestions
        data = json.loads(request.body)
        suggestions = get_prescription_suggestions(
            patient_id=data.get('patient_id', ''),
            diagnosis=data.get('diagnosis', ''),
            current_drugs=data.get('current_drugs', []),
            patient_profile=data.get('patient_profile', {}),
        )
        return JsonResponse(_dsr({'success': True, 'suggestions': suggestions}))
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(['GET'])
def api_audit_log(request):
    """Layer 10: audit log. Reads DB AuditEntry table."""
    try:
        patient_id = request.GET.get('patient_id', '')
        qs = AuditEntry.objects.filter(patient_id=patient_id).order_by('-created_at')[:20]
        entries = [
            {
                'patient_id': e.patient_id,
                'recommendation_type': e.recommendation_type,
                'engine_version': e.engine_version,
                'input_state': e.input_state,
                'output': e.output,
                'created_at': e.created_at.isoformat(),
            }
            for e in qs
        ]
        # Also pull from in-process GLOBAL_AUDIT_LOG for current session entries
        try:
            from .engine.explainability import GLOBAL_AUDIT_LOG
            mem_entries = GLOBAL_AUDIT_LOG.get_patient_history(patient_id)
            entries = mem_entries[-20:] + entries
        except Exception:
            pass
        return JsonResponse({'success': True, 'entries': entries[-20:]})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(['GET'])
def api_patient_profile(request):
    patient_key = request.GET.get('patient_key', 'ananya')
    profile = _get_patient_profile(patient_key)
    return JsonResponse({'success': True, 'profile': profile})


@csrf_exempt
@require_http_methods(['POST'])
def api_update_patient_profile(request):
    try:
        data = json.loads(request.body)
        patient_key = data.get('patient_key', 'ananya')
        updates = data.get('updates', {})

        patient = _get_or_create_demo_patient(patient_key)
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
@require_http_methods(['POST'])
def api_adherence_log(request):
    """Log dose confirmation. POST: {patient_key, rx_id, drug, scheduled_time, status}"""
    try:
        data = json.loads(request.body)
        patient_key = data.get('patient_key', 'ananya')
        rx_id = data.get('rx_id', '')
        drug = data.get('drug', '').lower()
        scheduled_time = data.get('scheduled_time', '')
        status = data.get('status', 'taken')

        if status not in ('taken', 'skipped', 'late'):
            return JsonResponse({'success': False, 'message': 'Invalid status'}, status=400)
        if not drug:
            return JsonResponse({'success': False, 'message': 'drug required'}, status=400)

        patient = _get_or_create_demo_patient(patient_key)
        event = AdherenceEvent.objects.create(
            patient=patient, rx_id=rx_id, drug=drug,
            scheduled_time=scheduled_time, status=status,
        )

        recent = list(AdherenceEvent.objects.filter(patient=patient).order_by('-taken_at')[:30])
        taken_count = sum(1 for e in recent if e.status == 'taken')
        score = round((taken_count / len(recent)) * 100) if recent else 100

        _django_cache.delete(_cache_key(patient_key, [], []))

        try:
            from .engine.explainability import GLOBAL_AUDIT_LOG
            GLOBAL_AUDIT_LOG.log_recommendation(
                recommendation_type='adherence_event',
                patient_id=patient_key,
                input_state={'drug': drug, 'status': status, 'scheduled': scheduled_time},
                output={'adherence_score': score},
                reasoning_chain=None,
            )
        except Exception:
            pass

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
@require_http_methods(['GET'])
def api_adherence_history(request):
    try:
        patient_key = request.GET.get('patient_key', 'ananya')
        patient = _get_or_create_demo_patient(patient_key)
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
