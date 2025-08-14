"""
API Gateway service for the distributed Codex Orchestrator.
Handles routing, authentication, rate limiting, and load balancing.
"""
import os
import json
import time
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import httpx
import redis.asyncio as redis
from prometheus_client import Counter, Histogram, generate_latest

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.service_discovery import (
    ServiceRegistry, LoadBalancer, ServiceClient,
    initialize_service_registry, register_service
)
from common.messaging import (
    initialize_message_bus, get_message_bus,
    Event, EventType
)

logger = logging.getLogger(__name__)

# Metrics
request_count = Counter(
    'gateway_requests_total',
    'Total requests to API Gateway',
    ['method', 'path', 'service', 'status']
)

request_duration = Histogram(
    'gateway_request_duration_seconds',
    'Request duration in API Gateway',
    ['method', 'path', 'service']
)

# Configuration
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8000"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CONSUL_HOST = os.getenv("CONSUL_HOST", "localhost")
CONSUL_PORT = int(os.getenv("CONSUL_PORT", "8500"))
KAFKA_SERVERS = os.getenv("KAFKA_SERVERS", "localhost:9092")

# Rate limiting configuration
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "20"))

# Service routing configuration
SERVICE_ROUTES = {
    "/api/v1/projects": "project-service",
    "/api/v1/work-items": "workitem-service",
    "/api/v1/scheduler": "scheduler-service",
    "/api/v1/agents": "agent-manager-service",
    "/api/v1/runs": "run-service",
    "/api/v1/audit": "audit-service",
}

# FastAPI app
app = FastAPI(
    title="Codex API Gateway",
    description="API Gateway for distributed Codex Orchestrator",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis."""
    
    def __init__(self, app, redis_client: redis.Redis):
        super().__init__(app)
        self.redis = redis_client
        self.rate_limit = RATE_LIMIT_PER_MINUTE
        self.burst = RATE_LIMIT_BURST
    
    async def dispatch(self, request: Request, call_next):
        # Get client identifier (IP or user ID from token)
        client_id = request.client.host if request.client else "unknown"
        
        # Check if it's an authenticated request
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            # Extract user ID from token (simplified)
            client_id = f"user:{auth_header[7:20]}"
        
        # Rate limit key
        key = f"rate_limit:{client_id}:{datetime.utcnow().minute}"
        
        try:
            # Get current count
            current = await self.redis.get(key)
            count = int(current) if current else 0
            
            # Check rate limit
            if count >= self.rate_limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": "60"}
                )
            
            # Increment counter
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, 60)
            await pipe.execute()
            
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # Allow request if Redis is down
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.rate_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.rate_limit - count - 1))
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 60)
        
        return response


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Request tracing and correlation ID middleware."""
    
    async def dispatch(self, request: Request, call_next):
        # Generate or extract correlation ID
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            import uuid
            correlation_id = str(uuid.uuid4())
        
        # Add to request state
        request.state.correlation_id = correlation_id
        
        # Process request
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Add headers
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Response-Time"] = f"{duration:.3f}"
        
        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path} "
            f"Status: {response.status_code} "
            f"Duration: {duration:.3f}s "
            f"CorrelationID: {correlation_id}"
        )
        
        # Emit metrics
        service = determine_service(request.url.path)
        request_count.labels(
            method=request.method,
            path=request.url.path,
            service=service,
            status=response.status_code
        ).inc()
        
        request_duration.labels(
            method=request.method,
            path=request.url.path,
            service=service
        ).observe(duration)
        
        return response


class ServiceRouter:
    """Routes requests to appropriate microservices."""
    
    def __init__(self, registry: ServiceRegistry):
        self.registry = registry
        self.load_balancer = LoadBalancer(registry)
        self.clients: Dict[str, ServiceClient] = {}
    
    async def get_client(self, service_name: str) -> ServiceClient:
        """Get or create service client."""
        if service_name not in self.clients:
            self.clients[service_name] = ServiceClient(
                service_name,
                self.registry,
                self.load_balancer
            )
        return self.clients[service_name]
    
    async def route_request(self,
                          request: Request,
                          service_name: str) -> Response:
        """Route request to service."""
        try:
            # Get service client
            client = await self.get_client(service_name)
            
            # Prepare request
            headers = dict(request.headers)
            headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"
            headers["X-Forwarded-Proto"] = request.url.scheme
            headers["X-Original-URI"] = str(request.url)
            
            # Make request
            body = await request.body()
            
            response = await client.request(
                method=request.method,
                path=request.url.path,
                params=dict(request.query_params),
                headers=headers,
                content=body if body else None
            )
            
            # Return response
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
            
        except Exception as e:
            logger.error(f"Failed to route request: {e}")
            raise HTTPException(status_code=503, detail="Service unavailable")
    
    async def close(self):
        """Close all service clients."""
        for client in self.clients.values():
            await client.close()


def determine_service(path: str) -> str:
    """Determine which service handles the path."""
    for prefix, service in SERVICE_ROUTES.items():
        if path.startswith(prefix):
            return service
    return "unknown"


# Global instances
redis_client: Optional[redis.Redis] = None
service_registry: Optional[ServiceRegistry] = None
service_router: Optional[ServiceRouter] = None
message_bus = None


@app.on_event("startup")
async def startup():
    """Initialize gateway on startup."""
    global redis_client, service_registry, service_router, message_bus
    
    # Initialize Redis
    redis_client = redis.from_url(REDIS_URL)
    await redis_client.ping()
    logger.info("Connected to Redis")
    
    # Initialize service registry
    service_registry = await initialize_service_registry(
        backend="consul",
        host=CONSUL_HOST,
        port=CONSUL_PORT
    )
    logger.info("Initialized service registry")
    
    # Register gateway itself
    await register_service(
        name="api-gateway",
        port=GATEWAY_PORT,
        tags=["gateway", "v1"],
        metadata={"version": "1.0.0"}
    )
    
    # Initialize service router
    service_router = ServiceRouter(service_registry)
    
    # Initialize message bus
    message_bus = await initialize_message_bus(
        backend="kafka",
        bootstrap_servers=KAFKA_SERVERS
    )
    logger.info("Initialized message bus")
    
    # Add middlewares
    app.add_middleware(RateLimitMiddleware, redis_client=redis_client)
    app.add_middleware(RequestTracingMiddleware)
    
    # Publish startup event
    event = Event(
        event_type=EventType.SERVICE_HEALTH_CHANGED,
        payload={
            "service": "api-gateway",
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    await message_bus.publish("system.events", event)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    if redis_client:
        await redis_client.close()
    
    if service_router:
        await service_router.close()
    
    if message_bus:
        await message_bus.disconnect()
    
    logger.info("Gateway shutdown complete")


@app.get("/health")
async def health():
    """Health check endpoint."""
    checks = {
        "gateway": "healthy",
        "redis": "unknown",
        "services": {}
    }
    
    # Check Redis
    try:
        await redis_client.ping()
        checks["redis"] = "healthy"
    except Exception:
        checks["redis"] = "unhealthy"
    
    # Check services
    if service_registry:
        services = await service_registry.get_all_services()
        for name, instances in services.items():
            healthy = sum(1 for i in instances if i.is_healthy)
            total = len(instances)
            checks["services"][name] = f"{healthy}/{total} healthy"
    
    # Determine overall status
    status = "healthy"
    if checks["redis"] == "unhealthy":
        status = "degraded"
    
    return {
        "status": status,
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type="text/plain"
    )


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def gateway_route(request: Request, path: str):
    """Main gateway route handler."""
    # Determine target service
    service = determine_service(f"/{path}")
    
    if service == "unknown":
        raise HTTPException(status_code=404, detail="Route not found")
    
    # Route to service
    return await service_router.route_request(request, service)


# WebSocket support for real-time features
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/{service}/{path:path}")
async def websocket_proxy(websocket: WebSocket, service: str, path: str):
    """WebSocket proxy for real-time features."""
    await websocket.accept()
    
    try:
        # Get service instance
        client = await service_router.get_client(f"{service}-service")
        
        # TODO: Implement WebSocket proxying
        # This is complex and requires bidirectional streaming
        
        await websocket.send_text("WebSocket proxying not yet implemented")
        
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=GATEWAY_PORT,
        log_level="info",
        access_log=True
    )