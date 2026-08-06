from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Security headers middleware (G-1.15)."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
        # CSP for MVP
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'"
        return response

class TimingMiddleware(BaseHTTPMiddleware):
    """Performance timing (G-1.15)."""
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        process_time = (time.time() - start) * 1000
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
        return response
