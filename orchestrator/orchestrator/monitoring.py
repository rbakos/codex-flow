"""
Comprehensive monitoring, health checks, and metrics for production.
Includes Prometheus metrics, health endpoints, and distributed tracing.
"""
import os
import time
import psutil
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from enum import Enum

from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
from opentelemetry import trace
from opentelemetry.exporter.jaeger import JaegerExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from .logging_config import StructuredLogger

logger = StructuredLogger(__name__)


class HealthStatus(Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class MetricsCollector:
    """Collect and expose Prometheus metrics."""
    
    def __init__(self):
        # Request metrics
        self.request_count = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status']
        )
        
        self.request_duration = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration',
            ['method', 'endpoint']
        )
        
        # Business metrics
        self.work_items_created = Counter(
            'work_items_created_total',
            'Total work items created',
            ['project_id']
        )
        
        self.runs_started = Counter(
            'runs_started_total',
            'Total runs started',
            ['work_item_id', 'agent_id']
        )
        
        self.runs_completed = Counter(
            'runs_completed_total',
            'Total runs completed',
            ['work_item_id', 'status']
        )
        
        # System metrics
        self.active_connections = Gauge(
            'active_connections',
            'Number of active connections'
        )
        
        self.db_pool_size = Gauge(
            'database_pool_size',
            'Database connection pool size'
        )
        
        self.queue_size = Gauge(
            'queue_size',
            'Number of items in queue',
            ['queue_name']
        )
        
        # Error metrics
        self.error_count = Counter(
            'errors_total',
            'Total errors',
            ['error_type', 'component']
        )
        
        # Performance metrics
        self.operation_duration = Histogram(
            'operation_duration_seconds',
            'Operation duration',
            ['operation_type']
        )
    
    def track_request(self, method: str, endpoint: str, status: int, duration: float):
        """Track HTTP request metrics."""
        self.request_count.labels(method=method, endpoint=endpoint, status=status).inc()
        self.request_duration.labels(method=method, endpoint=endpoint).observe(duration)
    
    def track_work_item_created(self, project_id: int):
        """Track work item creation."""
        self.work_items_created.labels(project_id=str(project_id)).inc()
    
    def track_run_started(self, work_item_id: int, agent_id: str):
        """Track run start."""
        self.runs_started.labels(work_item_id=str(work_item_id), agent_id=agent_id).inc()
    
    def track_run_completed(self, work_item_id: int, status: str):
        """Track run completion."""
        self.runs_completed.labels(work_item_id=str(work_item_id), status=status).inc()
    
    def track_error(self, error_type: str, component: str):
        """Track error occurrence."""
        self.error_count.labels(error_type=error_type, component=component).inc()
    
    def set_active_connections(self, count: int):
        """Set active connection count."""
        self.active_connections.set(count)
    
    def set_db_pool_size(self, size: int):
        """Set database pool size."""
        self.db_pool_size.set(size)
    
    def set_queue_size(self, queue_name: str, size: int):
        """Set queue size."""
        self.queue_size.labels(queue_name=queue_name).set(size)
    
    def get_metrics(self) -> bytes:
        """Get Prometheus metrics in text format."""
        return generate_latest(REGISTRY)


class HealthChecker:
    """Comprehensive health checking system."""
    
    def __init__(self):
        self.checks: Dict[str, callable] = {}
        self.last_check_results: Dict[str, Dict[str, Any]] = {}
        self.start_time = time.time()
    
    def register_check(self, name: str, check_func: callable):
        """Register a health check function."""
        self.checks[name] = check_func
        logger.info(f"Health check registered: {name}")
    
    async def run_checks(self) -> Dict[str, Any]:
        """Run all registered health checks."""
        results = {
            "status": HealthStatus.HEALTHY.value,
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": time.time() - self.start_time,
            "checks": {}
        }
        
        overall_status = HealthStatus.HEALTHY
        
        for name, check_func in self.checks.items():
            try:
                start = time.time()
                
                # Run check (handle both sync and async)
                if asyncio.iscoroutinefunction(check_func):
                    check_result = await check_func()
                else:
                    check_result = check_func()
                
                duration = time.time() - start
                
                results["checks"][name] = {
                    "status": check_result.get("status", HealthStatus.HEALTHY.value),
                    "duration_ms": duration * 1000,
                    "details": check_result.get("details", {}),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # Update overall status
                if check_result.get("status") == HealthStatus.UNHEALTHY.value:
                    overall_status = HealthStatus.UNHEALTHY
                elif check_result.get("status") == HealthStatus.DEGRADED.value and overall_status != HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.DEGRADED
                    
            except Exception as e:
                logger.error(f"Health check failed: {name}", error=e)
                results["checks"][name] = {
                    "status": HealthStatus.UNHEALTHY.value,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
                overall_status = HealthStatus.UNHEALTHY
        
        results["status"] = overall_status.value
        self.last_check_results = results
        
        # Log if unhealthy
        if overall_status != HealthStatus.HEALTHY:
            logger.warning(f"Health check status: {overall_status.value}", health_results=results)
        
        return results
    
    async def check_database(self) -> Dict[str, Any]:
        """Check database health."""
        from .database import db_manager
        
        try:
            is_healthy = await db_manager.health_check()
            pool_stats = await db_manager.get_pool_stats()
            
            status = HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY
            
            # Check pool exhaustion
            if pool_stats["checked_in"] == 0:
                status = HealthStatus.DEGRADED
            
            return {
                "status": status.value,
                "details": {
                    "connected": is_healthy,
                    "pool_stats": pool_stats
                }
            }
        except Exception as e:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "details": {"error": str(e)}
            }
    
    def check_disk_space(self) -> Dict[str, Any]:
        """Check available disk space."""
        try:
            disk_usage = psutil.disk_usage('/')
            free_gb = disk_usage.free / (1024 ** 3)
            percent_used = disk_usage.percent
            
            if percent_used > 90:
                status = HealthStatus.UNHEALTHY
            elif percent_used > 80:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY
            
            return {
                "status": status.value,
                "details": {
                    "free_gb": round(free_gb, 2),
                    "percent_used": percent_used
                }
            }
        except Exception as e:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "details": {"error": str(e)}
            }
    
    def check_memory(self) -> Dict[str, Any]:
        """Check memory usage."""
        try:
            memory = psutil.virtual_memory()
            
            if memory.percent > 90:
                status = HealthStatus.UNHEALTHY
            elif memory.percent > 80:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY
            
            return {
                "status": status.value,
                "details": {
                    "percent_used": memory.percent,
                    "available_gb": round(memory.available / (1024 ** 3), 2)
                }
            }
        except Exception as e:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "details": {"error": str(e)}
            }
    
    async def check_external_services(self) -> Dict[str, Any]:
        """Check external service availability."""
        results = {}
        
        # Check OpenAI if configured
        if os.getenv("OPENAI_API_KEY"):
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
                        timeout=5.0
                    )
                    results["openai"] = response.status_code == 200
            except Exception:
                results["openai"] = False
        
        # Check Redis if configured
        if os.getenv("REDIS_URL"):
            try:
                import redis.asyncio as redis
                r = redis.from_url(os.getenv("REDIS_URL"))
                await r.ping()
                results["redis"] = True
                await r.close()
            except Exception:
                results["redis"] = False
        
        # Determine overall status
        if all(results.values()):
            status = HealthStatus.HEALTHY
        elif any(results.values()):
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY if results else HealthStatus.HEALTHY
        
        return {
            "status": status.value,
            "details": results
        }


class TracingManager:
    """Manage distributed tracing with OpenTelemetry."""
    
    def __init__(self):
        self.tracer = None
        self.initialized = False
    
    def initialize(self, service_name: str = "codex-orchestrator"):
        """Initialize tracing with Jaeger backend."""
        if self.initialized:
            return
        
        # Check if Jaeger is configured
        jaeger_host = os.getenv("JAEGER_HOST", "localhost")
        jaeger_port = int(os.getenv("JAEGER_PORT", "6831"))
        
        try:
            # Create resource
            resource = Resource.create({
                "service.name": service_name,
                "service.version": "1.0.0",
                "deployment.environment": os.getenv("ENVIRONMENT", "development")
            })
            
            # Create tracer provider
            provider = TracerProvider(resource=resource)
            
            # Create Jaeger exporter
            jaeger_exporter = JaegerExporter(
                agent_host_name=jaeger_host,
                agent_port=jaeger_port,
                udp_split_oversized_batches=True
            )
            
            # Add batch processor
            processor = BatchSpanProcessor(jaeger_exporter)
            provider.add_span_processor(processor)
            
            # Set global tracer provider
            trace.set_tracer_provider(provider)
            
            # Get tracer
            self.tracer = trace.get_tracer(__name__)
            
            self.initialized = True
            logger.info(f"Tracing initialized with Jaeger at {jaeger_host}:{jaeger_port}")
            
        except Exception as e:
            logger.error("Failed to initialize tracing", error=e)
    
    def instrument_app(self, app):
        """Instrument FastAPI app for tracing."""
        if not self.initialized:
            self.initialize()
        
        try:
            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI instrumented for tracing")
        except Exception as e:
            logger.error("Failed to instrument FastAPI", error=e)
    
    def instrument_sqlalchemy(self, engine):
        """Instrument SQLAlchemy for tracing."""
        if not self.initialized:
            self.initialize()
        
        try:
            SQLAlchemyInstrumentor().instrument(engine=engine)
            logger.info("SQLAlchemy instrumented for tracing")
        except Exception as e:
            logger.error("Failed to instrument SQLAlchemy", error=e)
    
    def create_span(self, name: str):
        """Create a new tracing span."""
        if self.tracer:
            return self.tracer.start_as_current_span(name)
        return None


class AlertManager:
    """Manage alerts and notifications."""
    
    def __init__(self):
        self.alert_handlers: List[callable] = []
        self.alert_history: List[Dict[str, Any]] = []
        self.alert_cooldown: Dict[str, datetime] = {}
        
    def register_handler(self, handler: callable):
        """Register an alert handler."""
        self.alert_handlers.append(handler)
    
    async def send_alert(self, 
                        severity: str,
                        title: str,
                        description: str,
                        context: Optional[Dict[str, Any]] = None):
        """Send an alert through all registered handlers."""
        
        # Check cooldown
        alert_key = f"{severity}:{title}"
        if alert_key in self.alert_cooldown:
            if datetime.utcnow() < self.alert_cooldown[alert_key]:
                logger.info(f"Alert suppressed due to cooldown: {alert_key}")
                return
        
        alert = {
            "severity": severity,
            "title": title,
            "description": description,
            "context": context or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Add to history
        self.alert_history.append(alert)
        if len(self.alert_history) > 1000:
            self.alert_history = self.alert_history[-1000:]
        
        # Send through handlers
        for handler in self.alert_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed", error=e)
        
        # Set cooldown (5 minutes for same alert)
        self.alert_cooldown[alert_key] = datetime.utcnow() + timedelta(minutes=5)
        
        # Log the alert
        logger.warning(f"ALERT: {title}", alert=alert)
    
    def get_recent_alerts(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get recent alerts within specified hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return [
            alert for alert in self.alert_history
            if datetime.fromisoformat(alert["timestamp"]) > cutoff
        ]


# Global instances
metrics = MetricsCollector()
health = HealthChecker()
tracing = TracingManager()
alerts = AlertManager()

# Register default health checks
health.register_check("database", health.check_database)
health.register_check("disk_space", health.check_disk_space)
health.register_check("memory", health.check_memory)
health.register_check("external_services", health.check_external_services)