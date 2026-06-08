from django.urls import path
from . import views
from .fhir import views as fhir_views

urlpatterns = [
    # ── UI pages ──────────────────────────────────────────────────────────────
    path('', views.index, name='index'),
    path('auth/', views.auth_view, name='auth'),
    path('patient/', views.patient_view, name='patient'),
    path('doctor/', views.doctor_view, name='doctor'),

    # ── Auth API ──────────────────────────────────────────────────────────────
    path('api/login/', views.api_login, name='api_login'),
    path('api/logout/', views.api_logout, name='api_logout'),

    # ── Engine API ────────────────────────────────────────────────────────────
    path('api/engine/analyze/', views.api_analyze_regimen, name='api_analyze'),
    path('api/engine/run/<str:run_id>/status/', views.api_engine_run_status, name='api_run_status'),
    path('api/engine/observation/', views.api_update_observation, name='api_observation'),
    path('api/engine/suggestions/', views.api_prescription_suggestions, name='api_suggestions'),
    path('api/engine/audit/', views.api_audit_log, name='api_audit'),

    # ── Patient API ───────────────────────────────────────────────────────────
    path('api/patient/profile/', views.api_patient_profile, name='api_patient_profile'),
    path('api/patient/profile/update/', views.api_update_patient_profile, name='api_profile_update'),

    # ── Drug DB API ───────────────────────────────────────────────────────────
    path('api/drugs/search/', views.api_drug_search, name='api_drug_search'),
    path('api/drugs/interactions/', views.api_drug_interactions, name='api_drug_interactions'),

    # ── Adherence API ─────────────────────────────────────────────────────────
    path('api/adherence/log/', views.api_adherence_log, name='api_adherence_log'),
    path('api/adherence/history/', views.api_adherence_history, name='api_adherence_history'),

    # ── FHIR R4 endpoints ─────────────────────────────────────────────────────
    path('fhir/analyze/', fhir_views.fhir_analyze, name='fhir_analyze'),
    path('fhir/analyze/async/', fhir_views.fhir_analyze_async, name='fhir_analyze_async'),
    path('fhir/patient/<str:patient_id>/', fhir_views.fhir_patient, name='fhir_patient'),
    path('fhir/observation/', fhir_views.fhir_observation, name='fhir_observation'),
]
