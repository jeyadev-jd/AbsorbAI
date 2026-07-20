import time
from collections import defaultdict
from django.http import JsonResponse
from django.conf import settings


class RateLimitMiddleware:
    """Simple per-IP rate limiter using in-memory sliding window."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._requests = defaultdict(list)
        self.max_requests = getattr(settings, 'RATE_LIMIT_REQUESTS', 60)
        self.window = getattr(settings, 'RATE_LIMIT_WINDOW', 60)

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)

        ip = self._get_ip(request)
        now = time.time()
        cutoff = now - self.window

        self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]

        if len(self._requests[ip]) >= self.max_requests:
            return JsonResponse(
                {'success': False, 'message': 'Rate limit exceeded. Try again later.'},
                status=429,
            )

        self._requests[ip].append(now)
        return self.get_response(request)

    def _get_ip(self, request):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '127.0.0.1')
