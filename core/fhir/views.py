"""
FHIR R4 endpoints for AbsorbAI.

POST /fhir/analyze/         — full analysis from FHIR Bundle, returns FHIR Bundle
POST /fhir/analyze/async/   — enqueue async job, returns run_id
GET  /fhir/patient/<id>/    — FHIR Patient resource from AbsorbAI DB
POST /fhir/observation/     — FHIR Observation → Bayesian update
"""
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .adapter import FHIRAdapter, FHIRMapper

_adapter = FHIRAdapter()
_mapper = FHIRMapper()

_FHIR_CONTENT_TYPE = 'application/fhir+json'

_DISCLAIMER = (
    "FOR DECISION SUPPORT ONLY. Not medical advice. "
    "All clinical decisions require a licensed healthcare professional."
)


def _fhir_response(data: dict, status: int = 200):
    resp = JsonResponse(data, status=status)
    resp['Content-Type'] = _FHIR_CONTENT_TYPE
    return resp


def _fhir_error(message: str, status: int = 400) -> dict:
    return {
        'resourceType': 'OperationOutcome',
        'issue': [{'severity': 'error', 'code': 'processing', 'diagnostics': message}],
    }


@csrf_exempt
@require_http_methods(['POST'])
def fhir_analyze(request):
    """
    Accepts FHIR Bundle (Patient + MedicationRequest + Observation).
    Runs AbsorbAI 10-layer analysis.
    Returns FHIR Bundle (DetectedIssue + RiskAssessment + GuidanceResponse).
    """
    try:
        body = json.loads(request.body)

        # Accept both bare Bundle and {bundle: ...} wrapper
        if body.get('resourceType') == 'Bundle':
            bundle = body
        elif 'bundle' in body:
            bundle = body['bundle']
        else:
            return _fhir_response(_fhir_error('Expected FHIR Bundle'), 400)

        parsed = _adapter.parse_bundle(bundle)
        if not parsed['prescriptions']:
            return _fhir_response(
                _fhir_error('No MedicationRequest resources found in Bundle'), 400)

        from core.engine.orchestrator import analyze_patient_regimen
        result = analyze_patient_regimen(
            patient_id=parsed['patient_id'],
            patient_profile=parsed['patient_profile'],
            prescriptions=parsed['prescriptions'],
            dietary_factors=parsed['dietary_factors'],
            n_monte_carlo=100,
        )

        fhir_bundle = _mapper.result_to_bundle(result, parsed['patient_id'])

        # Inject disclaimer as Bundle.meta.tag
        fhir_bundle.setdefault('meta', {})
        fhir_bundle['meta'].setdefault('tag', [])
        fhir_bundle['meta']['tag'].append({
            'system': 'https://absorbai.io/fhir/tags',
            'code': 'decision-support-only',
            'display': _DISCLAIMER,
        })

        # Background hi-fi Celery run
        try:
            import hashlib
            ck = 'engine:' + hashlib.sha256(
                json.dumps({'p': parsed['patient_id'], 'rx': parsed['prescriptions'],
                            'd': sorted(parsed['dietary_factors'])},
                           sort_keys=True, default=str).encode()
            ).hexdigest()[:24]
            from core.tasks import run_hifi_analysis
            run_hifi_analysis.delay(
                parsed['patient_id'], parsed['patient_id'],
                parsed['patient_profile'], parsed['prescriptions'],
                parsed['dietary_factors'], ck,
            )
        except Exception:
            pass

        return _fhir_response(fhir_bundle)

    except json.JSONDecodeError:
        return _fhir_response(_fhir_error('Invalid JSON'), 400)
    except Exception as e:
        import traceback
        return _fhir_response(
            _fhir_error(f'Internal error: {str(e)}\n{traceback.format_exc()[-400:]}'), 500)


@csrf_exempt
@require_http_methods(['POST'])
def fhir_analyze_async(request):
    """
    Enqueue full analysis as async Celery job.
    Returns {run_id} — poll /api/engine/run/<id>/status/.
    """
    try:
        body = json.loads(request.body)
        bundle = body if body.get('resourceType') == 'Bundle' else body.get('bundle', body)
        parsed = _adapter.parse_bundle(bundle)

        if not parsed['prescriptions']:
            return _fhir_response(_fhir_error('No MedicationRequest resources found'), 400)

        from core.tasks import run_full_analysis_async
        task = run_full_analysis_async.delay(
            parsed['patient_id'], parsed['patient_id'],
            parsed['patient_profile'], parsed['prescriptions'],
            parsed['dietary_factors'], 500,
        )

        return _fhir_response({
            'resourceType': 'Parameters',
            'parameter': [
                {'name': 'run_id', 'valueString': task.id},
                {'name': 'status_url', 'valueString': f'/api/engine/run/{task.id}/status/'},
                {'name': 'patient_id', 'valueString': parsed['patient_id']},
            ],
        }, 202)

    except Exception as e:
        return _fhir_response(_fhir_error(str(e)), 500)


@csrf_exempt
@require_http_methods(['GET'])
def fhir_patient(request, patient_id: str):
    """Return FHIR R4 Patient resource from AbsorbAI DB."""
    try:
        from core.models import Patient
        import datetime

        try:
            p = Patient.objects.get(patient_key=patient_id)
        except Patient.DoesNotExist:
            return _fhir_response(_fhir_error(f'Patient {patient_id} not found'), 404)

        # Approximate birth date from age
        birth_year = datetime.date.today().year - int(p.age)
        fhir_patient = {
            'resourceType': 'Patient',
            'id': p.patient_key,
            'name': [{'use': 'official', 'text': p.name, 'family': p.name.split()[-1] if p.name else '',
                       'given': p.name.split()[:-1] if p.name else []}],
            'gender': 'female' if p.sex == 'F' else 'male',
            'birthDate': f'{birth_year}-01-01',
            'extension': [
                {'url': 'http://hl7.org/fhir/StructureDefinition/patient-bodyWeight',
                 'valueQuantity': {'value': p.weight, 'unit': 'kg', 'system': 'http://unitsofmeasure.org', 'code': 'kg'}},
                {'url': 'http://hl7.org/fhir/StructureDefinition/patient-bodyHeight',
                 'valueQuantity': {'value': p.height, 'unit': 'cm', 'system': 'http://unitsofmeasure.org', 'code': 'cm'}},
            ],
        }
        return _fhir_response(fhir_patient)
    except Exception as e:
        return _fhir_response(_fhir_error(str(e)), 500)


@csrf_exempt
@require_http_methods(['POST'])
def fhir_observation(request):
    """
    Accept FHIR Observation (lab result / drug level) and trigger Bayesian update.
    POST: FHIR Observation resource.
    """
    try:
        obs = json.loads(request.body)
        if obs.get('resourceType') != 'Observation':
            return _fhir_response(_fhir_error('Expected FHIR Observation resource'), 400)

        from core.fhir.adapter import _obs_code_text, _obs_value
        from core.engine.orchestrator import update_patient_observation

        patient_ref = obs.get('subject', {}).get('reference', '').replace('Patient/', '')
        code_text = _obs_code_text(obs).lower()
        value = _obs_value(obs)

        if value is None:
            return _fhir_response(_fhir_error('Observation has no value'), 400)

        # Determine observation type
        if 'concentration' in code_text or 'level' in code_text or 'trough' in code_text:
            obs_type = 'concentration'
        elif 'creatinine' in code_text:
            obs_type = 'lab'
        else:
            obs_type = 'lab'

        # Try to extract drug name from component or focus
        drug_name = ''
        for comp in obs.get('component', []):
            ct = (comp.get('code', {}).get('text') or '').lower()
            if ct:
                drug_name = ct
                break
        focus = obs.get('focus', [{}])
        if not drug_name and focus:
            drug_name = (focus[0].get('display') or '').lower()

        if not drug_name:
            return _fhir_response(_fhir_error('Cannot determine drug name from Observation'), 400)

        result = update_patient_observation(
            patient_id=patient_ref,
            drug_name=drug_name,
            observation_type=obs_type,
            observed_value=float(value),
            lab_name=_obs_code_text(obs),
            lab_unit=obs.get('valueQuantity', {}).get('unit', ''),
        )

        return _fhir_response({
            'resourceType': 'Parameters',
            'parameter': [
                {'name': 'success', 'valueBoolean': result.get('success', False)},
                {'name': 'message', 'valueString': result.get('message', '')},
                {'name': 'uncertainty_reductions',
                 'valueString': str(result.get('uncertainty_reductions', {}))},
            ],
        })
    except Exception as e:
        return _fhir_response(_fhir_error(str(e)), 500)
