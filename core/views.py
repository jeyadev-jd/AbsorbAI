from django.shortcuts import render, redirect
from django.http import JsonResponse
import jwt
import datetime
import json
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

JWT_SECRET = getattr(settings, 'SECRET_KEY', 'absorb-fallback-secret-key')

USERS = {
  'patient@demo.com': {'pass': 'patient123', 'role': 'patient', 'name': 'Ananya Rao', 'fname': 'Ananya', 'patientKey': 'ananya'},
  'doctor@demo.com': {'pass': 'doctor123', 'role': 'doctor', 'name': 'Dr. Priya Mehta', 'fname': 'Priya', 'patientKey': None},
}

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

@csrf_exempt
def api_login(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email', '').lower()
            password = data.get('password', '')
            role = data.get('role', '')

            user = USERS.get(email)
            if user and user['pass'] == password and user['role'] == role:
                payload = {
                    'email': email,
                    'role': user['role'],
                    'fname': user['fname'],
                    'name': user['name'],
                    # Optional: adding a patient key for the frontend
                    'patientKey': user.get('patientKey'),
                    'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=2)
                }
                token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
                
                response = JsonResponse({'success': True, 'user': user})
                response.set_cookie(
                    'jwt_token', token, 
                    httponly=False,  # Allow JS reading for frontend logic simplicity, or keep True if securely extracting via Django template tags
                    samesite='Lax'
                )
                return response
            else:
                return JsonResponse({'success': False, 'message': 'Invalid credentials.'}, status=401)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'success': False, 'message': 'POST strictly required'}, status=405)

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
    return render(request, 'index.html', {
        'initial_page': 'patient',
        'auth_user': json.dumps(decoded)
    })

def doctor_view(request):
    decoded = verify_jwt_cookie(request, required_role='doctor')
    if not decoded:
        return redirect('/auth/')
    return render(request, 'index.html', {
        'initial_page': 'doctor',
        'auth_user': json.dumps(decoded)
    })
