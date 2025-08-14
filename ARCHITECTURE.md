# Codex Orchestrator - Distributed Architecture

## Overview

The Codex Orchestrator is refactored from a monolithic application into a distributed microservices architecture with the following principles:

- **Service Independence**: Each service owns its data and can be deployed independently
- **Event-Driven Communication**: Services communicate via events/messages
- **Resilience**: Circuit breakers, retries, and fallbacks
- **Scalability**: Horizontal scaling of individual services
- **Observability**: Distributed tracing, metrics, and logging

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                            Client Layer                              │
│  Web UI | CLI | API Clients | Agents                                │
└────────────────────┬────────────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────────────┐
│                         API Gateway                                  │
│  - Authentication/Authorization                                      │
│  - Rate Limiting                                                     │
│  - Request Routing                                                   │
│  - Load Balancing                                                    │
└────────────────────┬────────────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────────────┐
│                      Service Mesh (Istio/Linkerd)                   │
│  - Service Discovery                                                 │
│  - Circuit Breakers                                                  │
│  - Distributed Tracing                                              │
│  - mTLS                                                             │
└──────┬──────────────┬───────────────┬───────────────┬──────────────┘
       │              │               │               │
┌──────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐ ┌──────▼──────┐
│   Project   │ │ WorkItem │ │  Scheduler  │ │    Agent    │
│   Service   │ │  Service │ │   Service   │ │   Manager   │
└──────┬──────┘ └────┬─────┘ └──────┬──────┘ └──────┬──────┘
       │              │               │               │
┌──────▼──────────────▼───────────────▼───────────────▼──────────────┐
│                    Message Bus (Kafka/RabbitMQ)                     │
│  - Event Streaming                                                  │
│  - Command/Query Separation                                         │
│  - Async Communication                                              │
└──────┬──────────────┬───────────────┬───────────────┬──────────────┘
       │              │               │               │
┌──────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐ ┌──────▼──────┐
│   Project   │ │ WorkItem │ │  Scheduler  │ │    Agent    │
│     DB      │ │    DB    │ │     DB      │ │     DB      │
│ (PostgreSQL)│ │(PostgreSQL)│ │   (Redis)   │ │ (MongoDB)   │
└─────────────┘ └──────────┘ └─────────────┘ └─────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Shared Infrastructure                           │
│  - Redis Cache                                                      │
│  - Elasticsearch (Logs)                                             │
│  - Prometheus (Metrics)                                             │
│  - Jaeger (Tracing)                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

## Service Boundaries

### 1. API Gateway Service
**Responsibilities:**
- Request routing and load balancing
- Authentication and authorization
- Rate limiting and throttling
- Request/response transformation
- API versioning

**Technology:** Kong, Envoy, or custom FastAPI service

### 2. Project Service
**Responsibilities:**
- Project CRUD operations
- Vision and requirements management
- Project-level authorization
- Usage quotas and limits

**Data:** Projects, Visions, Requirements, Quotas

### 3. WorkItem Service
**Responsibilities:**
- Work item lifecycle management
- Tool recipe validation
- Approval workflows
- Artifact storage

**Data:** WorkItems, ToolRecipes, Approvals, Artifacts

### 4. Scheduler Service
**Responsibilities:**
- Task scheduling and dependencies
- Queue management
- Priority handling
- Retry and backoff logic

**Data:** ScheduledTasks, Queue state (Redis)

### 5. Agent Manager Service
**Responsibilities:**
- Agent registration and health
- Run assignment and claiming
- Heartbeat management
- Load distribution

**Data:** Agents, Runs, Claims, Metrics

### 6. Notification Service
**Responsibilities:**
- Email/Slack/webhook notifications
- Alert management
- Event subscriptions

**Data:** Subscriptions, Templates, History

### 7. Audit Service
**Responsibilities:**
- Event sourcing
- Audit trail
- Compliance reporting

**Data:** Events, Audit logs

## Communication Patterns

### Synchronous Communication (REST/gRPC)
Used for:
- Client-facing APIs
- Real-time queries
- Health checks

### Asynchronous Communication (Message Queue)
Used for:
- Event notifications
- Long-running operations
- Service decoupling

### Event Types

```yaml
# Domain Events
ProjectCreated:
  project_id: uuid
  name: string
  created_by: uuid
  timestamp: datetime

WorkItemStateChanged:
  work_item_id: uuid
  previous_state: string
  new_state: string
  changed_by: uuid
  timestamp: datetime

RunCompleted:
  run_id: uuid
  work_item_id: uuid
  status: string
  agent_id: string
  timestamp: datetime

# Command Events
ScheduleWorkItem:
  work_item_id: uuid
  priority: int
  dependencies: array
  scheduled_by: uuid

ClaimRun:
  run_id: uuid
  agent_id: string
  ttl: int

# System Events
ServiceHealthChanged:
  service: string
  status: string
  details: object
```

## Data Consistency

### Saga Pattern for Distributed Transactions
```python
class WorkItemCreationSaga:
    steps = [
        CreateWorkItemStep,
        ValidateToolRecipeStep,
        AssignQuotaStep,
        ScheduleTaskStep,
        NotifySubscribersStep
    ]
    
    compensations = [
        DeleteWorkItemCompensation,
        None,  # No compensation needed
        ReleaseQuotaCompensation,
        UnscheduleTaskCompensation,
        None  # No compensation needed
    ]
```

### Event Sourcing for Audit
All state changes are stored as events:
```python
Event(
    aggregate_id="workitem_123",
    event_type="WorkItemCreated",
    data={...},
    timestamp=datetime.utcnow(),
    correlation_id="req_456"
)
```

## Service Discovery

### Consul Integration
```yaml
services:
  - name: project-service
    address: 10.0.1.10
    port: 8001
    tags: ["v1", "primary"]
    health_check:
      http: http://10.0.1.10:8001/health
      interval: 10s
```

## Resilience Patterns

### Circuit Breaker
```python
@circuit_breaker(
    failure_threshold=5,
    recovery_timeout=60,
    expected_exception=ServiceUnavailable
)
async def call_scheduler_service(payload):
    return await http_client.post(
        "http://scheduler-service/schedule",
        json=payload
    )
```

### Retry with Exponential Backoff
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(TemporaryError)
)
async def process_message(message):
    # Process message
```

### Bulkhead Pattern
```python
# Isolate resources for critical operations
critical_pool = ConnectionPool(size=10)
normal_pool = ConnectionPool(size=20)

async def critical_operation():
    async with critical_pool.get_connection() as conn:
        # Isolated from normal operations
```

## Deployment Strategy

### Kubernetes Deployment
Each service deployed as separate deployment with:
- Horizontal Pod Autoscaler
- Pod Disruption Budget
- Resource limits and requests
- Health and readiness probes

### Service Mesh (Istio)
- Automatic mTLS between services
- Traffic management and canary deployments
- Distributed tracing
- Circuit breakers at mesh level

## Migration Strategy

### Phase 1: Extract Read Models
- Create read-only API services
- Implement CQRS pattern
- Add caching layer

### Phase 2: Extract Business Logic
- Move business logic to domain services
- Implement event publishing
- Add saga orchestration

### Phase 3: Data Separation
- Separate databases per service
- Implement data synchronization
- Add eventual consistency handling

### Phase 4: Full Microservices
- Complete service isolation
- Remove direct database access
- Full event-driven architecture

## Performance Considerations

### Caching Strategy
- **L1 Cache**: In-memory service cache (5 minutes)
- **L2 Cache**: Redis shared cache (1 hour)
- **L3 Cache**: CDN for static content (24 hours)

### Database Optimization
- Read replicas for query services
- Sharding for high-volume data
- Time-series database for metrics

### Message Queue Optimization
- Partitioned topics for parallel processing
- Message batching for throughput
- Dead letter queues for failed messages

## Security Considerations

### Zero Trust Architecture
- mTLS for service communication
- JWT tokens with short expiry
- Service-specific credentials
- Network policies for isolation

### API Gateway Security
- Rate limiting per client
- DDoS protection
- WAF integration
- API key management

## Monitoring and Observability

### Metrics (Prometheus)
- Service-level metrics
- Business metrics
- Infrastructure metrics
- Custom metrics per service

### Logging (ELK Stack)
- Structured JSON logging
- Correlation IDs
- Log aggregation
- Real-time search

### Tracing (Jaeger)
- Distributed request tracing
- Service dependency mapping
- Performance bottleneck identification
- Error tracking

## Service Level Objectives

### API Gateway
- Availability: 99.99%
- Latency: p99 < 100ms
- Error rate: < 0.1%

### Core Services
- Availability: 99.9%
- Latency: p99 < 500ms
- Error rate: < 1%

### Background Services
- Availability: 99%
- Processing time: p99 < 5s
- Queue depth: < 1000 messages