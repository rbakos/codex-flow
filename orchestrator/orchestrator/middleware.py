from starlette.middleware.base import BaseHTTPMiddleware
import uuid
from .rate_limit import SlidingWindowRateLimiter
from .config import settings

_limiter = SlidingWindowRateLimiter(max_per_minute=settings.rate_limit_per_min)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        # naive client key: remote addr
        client = request.client.host if request.client else "anonymous"
        ok, remaining = _limiter.allow(client)
        if not ok:
            from starlette.responses import JSONResponse

            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        response = await call_next(request)
        response.headers["x-request-id"] = req_id
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
