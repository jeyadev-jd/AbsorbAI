from celery import shared_task
from django.utils import timezone
from django.core.cache import cache


@shared_task(bind=True, max_retries=2)
def run_hifi_analysis(self, patient_id: str, patient_key: str, patient_profile: dict,
                      prescriptions: list, dietary_factors: list, cache_key: str):
    """
    Hi-fidelity engine run (n=500 Monte Carlo). Updates cache + EngineRun record.
    Called as background task after the fast n=100 response is already returned.
    """
    from .engine.orchestrator import analyze_patient_regimen

    try:
        result = analyze_patient_regimen(
            patient_id=patient_id,
            patient_profile=patient_profile,
            prescriptions=prescriptions,
            dietary_factors=dietary_factors,
            n_monte_carlo=500,
        )
        result['decision_support_only'] = True
        result['high_fidelity'] = True

        cache.set(cache_key, result, timeout=600)

        # Persist updated EngineRun
        from .models import EngineRun, Patient
        from django.conf import settings
        patient_obj = Patient.objects.filter(patient_key=patient_key).first()
        EngineRun.objects.create(
            patient=patient_obj,
            patient_id_str=patient_id,
            input_hash=cache_key,
            n_monte_carlo=500,
            engine_version=getattr(settings, 'ENGINE_VERSION', '1.0.0'),
            drug_db_version=getattr(settings, 'DRUG_DB_VERSION', '1.0.0'),
            status='done',
            result_json=result,
            celery_task_id=self.request.id or '',
            completed_at=timezone.now(),
        )
        return {'status': 'done', 'patient_id': patient_id}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)


@shared_task(bind=True, max_retries=1)
def run_full_analysis_async(self, patient_id: str, patient_key: str, patient_profile: dict,
                             prescriptions: list, dietary_factors: list, n_monte_carlo: int = 500):
    """
    Full async analysis — used when caller wants a run_id to poll.
    Stores result in EngineRun; caller polls /api/engine/run/<id>/status/.
    """
    from .engine.orchestrator import analyze_patient_regimen
    from .models import EngineRun, Patient
    from django.conf import settings
    import hashlib, json

    cache_key = 'engine:' + hashlib.sha256(
        json.dumps({'p': patient_id, 'rx': prescriptions, 'd': sorted(dietary_factors or [])},
                   sort_keys=True, default=str).encode()
    ).hexdigest()[:24]

    run = None
    try:
        patient_obj = Patient.objects.filter(patient_key=patient_key).first()
        run = EngineRun.objects.create(
            patient=patient_obj,
            patient_id_str=patient_id,
            input_hash=cache_key,
            n_monte_carlo=n_monte_carlo,
            engine_version=getattr(settings, 'ENGINE_VERSION', '1.0.0'),
            drug_db_version=getattr(settings, 'DRUG_DB_VERSION', '1.0.0'),
            status='running',
            celery_task_id=self.request.id or '',
        )

        result = analyze_patient_regimen(
            patient_id=patient_id,
            patient_profile=patient_profile,
            prescriptions=prescriptions,
            dietary_factors=dietary_factors,
            n_monte_carlo=n_monte_carlo,
        )
        result['decision_support_only'] = True
        result['run_id'] = str(run.id)
        cache.set(cache_key, result, timeout=600)

        run.status = 'done'
        run.result_json = result
        run.completed_at = timezone.now()
        run.save()

        return {'status': 'done', 'run_id': str(run.id)}

    except Exception as exc:
        if run:
            run.status = 'failed'
            run.error_msg = str(exc)
            run.save()
        raise self.retry(exc=exc, countdown=15)
