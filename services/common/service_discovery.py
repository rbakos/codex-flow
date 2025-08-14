"""
Service discovery and registry for distributed microservices.
Supports Consul, etcd, and Kubernetes native discovery.
"""
import os
import json
import asyncio
import socket
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging
from abc import ABC, abstractmethod

import consul.aio
import etcd3
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class ServiceStatus(str, Enum):
    """Service health status."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ServiceInstance:
    """Service instance information."""
    id: str
    name: str
    address: str
    port: int
    tags: List[str]
    metadata: Dict[str, Any]
    status: ServiceStatus
    last_heartbeat: datetime
    
    @property
    def url(self) -> str:
        """Get service URL."""
        return f"http://{self.address}:{self.port}"
    
    @property
    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self.status == ServiceStatus.HEALTHY


class ServiceRegistry(ABC):
    """Abstract service registry interface."""
    
    @abstractmethod
    async def register(self, service: ServiceInstance):
        """Register service instance."""
        pass
    
    @abstractmethod
    async def deregister(self, service_id: str):
        """Deregister service instance."""
        pass
    
    @abstractmethod
    async def get_service(self, name: str) -> List[ServiceInstance]:
        """Get service instances by name."""
        pass
    
    @abstractmethod
    async def get_all_services(self) -> Dict[str, List[ServiceInstance]]:
        """Get all registered services."""
        pass
    
    @abstractmethod
    async def health_check(self, service_id: str) -> ServiceStatus:
        """Check service health."""
        pass
    
    @abstractmethod
    async def watch(self, service_name: str, callback: Callable):
        """Watch for service changes."""
        pass


class ConsulServiceRegistry(ServiceRegistry):
    """Consul-based service registry."""
    
    def __init__(self, host: str = "localhost", port: int = 8500):
        self.consul = consul.aio.Consul(host=host, port=port)
        self.watchers: Dict[str, asyncio.Task] = {}
    
    async def register(self, service: ServiceInstance):
        """Register service with Consul."""
        # Prepare health check
        check = consul.Check.http(
            f"http://{service.address}:{service.port}/health",
            interval="10s",
            timeout="5s",
            deregister="30s"
        )
        
        # Register service
        await self.consul.agent.service.register(
            name=service.name,
            service_id=service.id,
            address=service.address,
            port=service.port,
            tags=service.tags,
            meta=service.metadata,
            check=check
        )
        
        logger.info(f"Registered service {service.name} ({service.id}) with Consul")
    
    async def deregister(self, service_id: str):
        """Deregister service from Consul."""
        await self.consul.agent.service.deregister(service_id)
        logger.info(f"Deregistered service {service_id} from Consul")
    
    async def get_service(self, name: str) -> List[ServiceInstance]:
        """Get service instances from Consul."""
        _, services = await self.consul.health.service(name, passing=True)
        
        instances = []
        for service in services:
            svc = service['Service']
            checks = service['Checks']
            
            # Determine status from checks
            status = ServiceStatus.HEALTHY
            for check in checks:
                if check['Status'] == 'critical':
                    status = ServiceStatus.CRITICAL
                    break
                elif check['Status'] == 'warning':
                    status = ServiceStatus.UNHEALTHY
            
            instances.append(ServiceInstance(
                id=svc['ID'],
                name=svc['Service'],
                address=svc['Address'],
                port=svc['Port'],
                tags=svc.get('Tags', []),
                metadata=svc.get('Meta', {}),
                status=status,
                last_heartbeat=datetime.utcnow()
            ))
        
        return instances
    
    async def get_all_services(self) -> Dict[str, List[ServiceInstance]]:
        """Get all services from Consul."""
        _, services = await self.consul.catalog.services()
        
        all_instances = {}
        for service_name in services.keys():
            if service_name != 'consul':  # Skip consul itself
                instances = await self.get_service(service_name)
                if instances:
                    all_instances[service_name] = instances
        
        return all_instances
    
    async def health_check(self, service_id: str) -> ServiceStatus:
        """Check service health in Consul."""
        _, checks = await self.consul.agent.checks()
        
        service_check = f"service:{service_id}"
        if service_check in checks:
            check = checks[service_check]
            if check['Status'] == 'passing':
                return ServiceStatus.HEALTHY
            elif check['Status'] == 'warning':
                return ServiceStatus.UNHEALTHY
            elif check['Status'] == 'critical':
                return ServiceStatus.CRITICAL
        
        return ServiceStatus.UNKNOWN
    
    async def watch(self, service_name: str, callback: Callable):
        """Watch for service changes in Consul."""
        async def _watch_loop():
            index = None
            while True:
                try:
                    # Long poll for changes
                    index, services = await self.consul.health.service(
                        service_name,
                        index=index,
                        wait='30s'
                    )
                    
                    # Convert to ServiceInstance objects
                    instances = []
                    for service in services:
                        svc = service['Service']
                        instances.append(ServiceInstance(
                            id=svc['ID'],
                            name=svc['Service'],
                            address=svc['Address'],
                            port=svc['Port'],
                            tags=svc.get('Tags', []),
                            metadata=svc.get('Meta', {}),
                            status=ServiceStatus.HEALTHY,
                            last_heartbeat=datetime.utcnow()
                        ))
                    
                    # Call callback
                    if asyncio.iscoroutinefunction(callback):
                        await callback(instances)
                    else:
                        callback(instances)
                        
                except Exception as e:
                    logger.error(f"Watch error: {e}")
                    await asyncio.sleep(5)
        
        # Start watcher task
        if service_name in self.watchers:
            self.watchers[service_name].cancel()
        
        self.watchers[service_name] = asyncio.create_task(_watch_loop())
        logger.info(f"Started watching service: {service_name}")


class EtcdServiceRegistry(ServiceRegistry):
    """etcd-based service registry."""
    
    def __init__(self, host: str = "localhost", port: int = 2379):
        self.etcd = etcd3.client(host=host, port=port)
        self.service_prefix = "/services"
        self.lease_ttl = 30  # seconds
        self.leases: Dict[str, Any] = {}
    
    async def register(self, service: ServiceInstance):
        """Register service with etcd."""
        # Create lease for TTL
        lease = self.etcd.lease(self.lease_ttl)
        self.leases[service.id] = lease
        
        # Service key and value
        key = f"{self.service_prefix}/{service.name}/{service.id}"
        value = json.dumps({
            'id': service.id,
            'name': service.name,
            'address': service.address,
            'port': service.port,
            'tags': service.tags,
            'metadata': service.metadata,
            'status': service.status,
            'last_heartbeat': service.last_heartbeat.isoformat()
        })
        
        # Put with lease
        self.etcd.put(key, value, lease=lease)
        
        # Start lease keepalive
        asyncio.create_task(self._keepalive_loop(service.id, lease))
        
        logger.info(f"Registered service {service.name} ({service.id}) with etcd")
    
    async def deregister(self, service_id: str):
        """Deregister service from etcd."""
        # Revoke lease (will delete all keys)
        if service_id in self.leases:
            self.leases[service_id].revoke()
            del self.leases[service_id]
        
        logger.info(f"Deregistered service {service_id} from etcd")
    
    async def get_service(self, name: str) -> List[ServiceInstance]:
        """Get service instances from etcd."""
        prefix = f"{self.service_prefix}/{name}/"
        instances = []
        
        for value, metadata in self.etcd.get_prefix(prefix):
            if value:
                data = json.loads(value.decode())
                instances.append(ServiceInstance(
                    id=data['id'],
                    name=data['name'],
                    address=data['address'],
                    port=data['port'],
                    tags=data.get('tags', []),
                    metadata=data.get('metadata', {}),
                    status=ServiceStatus(data.get('status', 'unknown')),
                    last_heartbeat=datetime.fromisoformat(data['last_heartbeat'])
                ))
        
        return instances
    
    async def get_all_services(self) -> Dict[str, List[ServiceInstance]]:
        """Get all services from etcd."""
        all_instances = {}
        
        for value, metadata in self.etcd.get_prefix(self.service_prefix):
            if value:
                data = json.loads(value.decode())
                service_name = data['name']
                
                if service_name not in all_instances:
                    all_instances[service_name] = []
                
                all_instances[service_name].append(ServiceInstance(
                    id=data['id'],
                    name=data['name'],
                    address=data['address'],
                    port=data['port'],
                    tags=data.get('tags', []),
                    metadata=data.get('metadata', {}),
                    status=ServiceStatus(data.get('status', 'unknown')),
                    last_heartbeat=datetime.fromisoformat(data['last_heartbeat'])
                ))
        
        return all_instances
    
    async def health_check(self, service_id: str) -> ServiceStatus:
        """Check service health."""
        # Try to get service data
        services = await self.get_all_services()
        
        for service_list in services.values():
            for service in service_list:
                if service.id == service_id:
                    # Check if heartbeat is recent
                    age = datetime.utcnow() - service.last_heartbeat
                    if age < timedelta(seconds=30):
                        return ServiceStatus.HEALTHY
                    elif age < timedelta(minutes=1):
                        return ServiceStatus.UNHEALTHY
                    else:
                        return ServiceStatus.CRITICAL
        
        return ServiceStatus.UNKNOWN
    
    async def watch(self, service_name: str, callback: Callable):
        """Watch for service changes in etcd."""
        prefix = f"{self.service_prefix}/{service_name}/"
        
        async def _watch_loop():
            events_iterator, cancel = self.etcd.watch_prefix(prefix)
            
            try:
                for event in events_iterator:
                    instances = await self.get_service(service_name)
                    
                    if asyncio.iscoroutinefunction(callback):
                        await callback(instances)
                    else:
                        callback(instances)
            finally:
                cancel()
        
        asyncio.create_task(_watch_loop())
        logger.info(f"Started watching service: {service_name}")
    
    async def _keepalive_loop(self, service_id: str, lease):
        """Keep lease alive for service."""
        while service_id in self.leases:
            try:
                lease.refresh()
                await asyncio.sleep(self.lease_ttl / 3)
            except Exception as e:
                logger.error(f"Lease keepalive error: {e}")
                break


class LoadBalancer:
    """Client-side load balancer for service instances."""
    
    def __init__(self, registry: ServiceRegistry):
        self.registry = registry
        self.current_index: Dict[str, int] = {}
    
    async def get_instance(self, 
                          service_name: str,
                          strategy: str = "round_robin") -> Optional[ServiceInstance]:
        """Get service instance with load balancing."""
        instances = await self.registry.get_service(service_name)
        
        # Filter healthy instances
        healthy = [i for i in instances if i.is_healthy]
        
        if not healthy:
            return None
        
        if strategy == "round_robin":
            # Round-robin selection
            if service_name not in self.current_index:
                self.current_index[service_name] = 0
            
            index = self.current_index[service_name] % len(healthy)
            self.current_index[service_name] += 1
            
            return healthy[index]
        
        elif strategy == "random":
            # Random selection
            import random
            return random.choice(healthy)
        
        elif strategy == "least_connections":
            # Would need connection tracking
            # For now, fall back to round-robin
            return await self.get_instance(service_name, "round_robin")
        
        else:
            raise ValueError(f"Unknown strategy: {strategy}")


class CircuitBreaker:
    """Circuit breaker for service calls."""
    
    def __init__(self,
                 failure_threshold: int = 5,
                 recovery_timeout: int = 60,
                 expected_exception: type = Exception):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half_open
    
    async def call(self, func: Callable, *args, **kwargs):
        """Call function with circuit breaker."""
        # Check if circuit is open
        if self.state == "open":
            if self.last_failure_time:
                time_since_failure = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if time_since_failure > self.recovery_timeout:
                    self.state = "half_open"
                else:
                    raise Exception("Circuit breaker is open")
        
        try:
            # Make the call
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # Success - reset on half_open
            if self.state == "half_open":
                self.state = "closed"
                self.failure_count = 0
            
            return result
            
        except self.expected_exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.utcnow()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
            
            raise


class ServiceClient:
    """HTTP client with service discovery and resilience."""
    
    def __init__(self,
                 service_name: str,
                 registry: ServiceRegistry,
                 load_balancer: Optional[LoadBalancer] = None):
        self.service_name = service_name
        self.registry = registry
        self.load_balancer = load_balancer or LoadBalancer(registry)
        self.client = httpx.AsyncClient(timeout=30.0)
        self.circuit_breaker = CircuitBreaker()
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def request(self,
                     method: str,
                     path: str,
                     **kwargs) -> httpx.Response:
        """Make HTTP request to service."""
        # Get service instance
        instance = await self.load_balancer.get_instance(self.service_name)
        if not instance:
            raise Exception(f"No healthy instances for service: {self.service_name}")
        
        # Build URL
        url = f"{instance.url}{path}"
        
        # Make request with circuit breaker
        async def _make_request():
            return await self.client.request(method, url, **kwargs)
        
        return await self.circuit_breaker.call(_make_request)
    
    async def get(self, path: str, **kwargs) -> httpx.Response:
        """GET request."""
        return await self.request("GET", path, **kwargs)
    
    async def post(self, path: str, **kwargs) -> httpx.Response:
        """POST request."""
        return await self.request("POST", path, **kwargs)
    
    async def put(self, path: str, **kwargs) -> httpx.Response:
        """PUT request."""
        return await self.request("PUT", path, **kwargs)
    
    async def delete(self, path: str, **kwargs) -> httpx.Response:
        """DELETE request."""
        return await self.request("DELETE", path, **kwargs)
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


# Service registry factory
def create_service_registry(backend: str = "consul", **kwargs) -> ServiceRegistry:
    """Create service registry instance."""
    if backend == "consul":
        return ConsulServiceRegistry(**kwargs)
    elif backend == "etcd":
        return EtcdServiceRegistry(**kwargs)
    else:
        raise ValueError(f"Unknown backend: {backend}")


# Global registry instance
service_registry: Optional[ServiceRegistry] = None


async def initialize_service_registry(backend: str = "consul", **kwargs):
    """Initialize global service registry."""
    global service_registry
    service_registry = create_service_registry(backend, **kwargs)
    return service_registry


async def register_service(name: str,
                          port: int,
                          tags: List[str] = None,
                          metadata: Dict[str, Any] = None):
    """Register current service."""
    if not service_registry:
        raise RuntimeError("Service registry not initialized")
    
    # Get host IP
    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    
    # Create service instance
    service = ServiceInstance(
        id=f"{name}-{hostname}-{port}",
        name=name,
        address=ip,
        port=port,
        tags=tags or [],
        metadata=metadata or {},
        status=ServiceStatus.HEALTHY,
        last_heartbeat=datetime.utcnow()
    )
    
    # Register
    await service_registry.register(service)
    
    return service