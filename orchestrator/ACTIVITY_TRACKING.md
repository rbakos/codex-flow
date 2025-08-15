# Activity Tracking System Documentation

## Overview

The Codex Orchestrator now includes a comprehensive activity tracking system that provides real-time visibility into all system decisions, thread activities, and operations. This system ensures that every significant action is logged with details about what it will do, what it's doing, and what it has done.

## Key Features

### 1. Comprehensive Activity Tracking
- **Decisions**: All system decisions are tracked with reasoning and outcomes
- **Threads**: Thread lifecycle and activities are monitored
- **Async Tasks**: Asynchronous operations are tracked from start to completion
- **API Calls**: External API interactions are logged
- **Database Operations**: Database queries and updates are monitored
- **AI Inference**: AI/ML model invocations are tracked
- **Work Items**: Work item processing and state transitions
- **Agent Actions**: Agent activities and executions
- **Scheduler Ticks**: Scheduler queue processing

### 2. Real-time Monitoring Dashboard
- **Web Interface**: Beautiful HTML dashboard at `/monitor`
- **WebSocket Streaming**: Real-time activity updates via WebSocket
- **Activity Statistics**: Comprehensive metrics and success rates
- **Visual Status Indicators**: Color-coded activity states
- **Hierarchical View**: Parent-child activity relationships

### 3. Activity States
Each activity progresses through these states:
- `PLANNED`: Activity is created and queued
- `IN_PROGRESS`: Activity is currently executing
- `COMPLETED`: Activity finished successfully
- `FAILED`: Activity encountered an error
- `CANCELLED`: Activity was cancelled

## Implementation Details

### Core Components

#### 1. ActivityTracker (`orchestrator/activity_tracker.py`)
The singleton tracker manages all system activities:

```python
from orchestrator.activity_tracker import tracker, ActivityType, track_activity

# Create and track an activity
with track_activity(
    ActivityType.DECISION,
    "Process payment",
    "Will validate and process payment for order #123"
) as activity_id:
    # Your code here
    tracker.complete_activity(
        activity_id,
        "Payment processed successfully",
        result={"transaction_id": "xyz"}
    )
```

#### 2. Decorators for Automatic Tracking

```python
from orchestrator.activity_tracker import track_decision, track_thread, track_async_task

@track_decision("Determine optimal resource allocation")
def allocate_resources(project_id: str):
    # Function automatically tracked
    return allocation_plan

@track_thread("Process background data sync")
def background_sync():
    # Thread execution tracked
    sync_data()

@track_async_task("Fetch external API data")
async def fetch_api_data():
    # Async task tracked
    return await api_call()
```

#### 3. Context Manager for Flexible Tracking

```python
from orchestrator.activity_tracker import track_activity, ActivityType

with track_activity(
    ActivityType.WORK_ITEM,
    "Deploy service",
    "Will deploy service to production"
) as activity_id:
    deploy_service()
    tracker.complete_activity(
        activity_id,
        "Service deployed successfully",
        result={"version": "1.2.3"}
    )
```

### API Endpoints

#### Activity Monitoring Endpoints
- `GET /activity/active` - Get currently active activities
- `GET /activity/all` - Get all activities with filtering
- `GET /activity/tree` - Get hierarchical activity tree
- `GET /activity/decisions` - Get decision history
- `GET /activity/thread/{thread_id}` - Get thread activities
- `GET /activity/activity/{activity_id}` - Get specific activity details
- `GET /activity/stats` - Get activity statistics
- `GET /activity/summary` - Get human-readable summary
- `GET /activity/export` - Export activities for audit
- `WS /activity/stream` - WebSocket for real-time updates

#### Monitoring Dashboard
- `GET /monitor` - Web-based monitoring dashboard

## Integration Points

### 1. CRUD Operations (`orchestrator/crud.py`)
All database operations include activity tracking:
- Project creation
- Requirements generation
- Run lifecycle management
- Scheduler operations
- Retry decisions

### 2. Work Item Processing (`orchestrator/routers/workitems.py`)
Work item operations are comprehensively tracked:
- Work item creation
- Run initiation
- Approval checks
- Completion handling

### 3. Planner Integration (`orchestrator/planner.py`)
AI-powered planning decisions are tracked:
- OpenAI API calls
- Requirements generation
- Decision reasoning

### 4. Agent Operations (`scripts/agent.py`)
Agent activities include tracking for:
- Scheduler ticks
- Work item processing
- Thread spawning
- Background tasks

## Usage Examples

### Example 1: Tracking a Decision

```python
activity_id = tracker.create_activity(
    type=ActivityType.DECISION,
    name="Select deployment strategy",
    what_it_will_do="Analyze metrics to choose blue-green or canary deployment"
)

tracker.start_activity(activity_id, "Analyzing deployment metrics")

# Perform decision logic
if metrics.error_rate < 0.01:
    strategy = "canary"
else:
    strategy = "blue-green"

tracker.complete_activity(
    activity_id,
    f"Selected {strategy} deployment based on error rate",
    result={"strategy": strategy, "error_rate": metrics.error_rate}
)
```

### Example 2: Tracking Nested Activities

```python
parent_id = tracker.create_activity(
    type=ActivityType.WORK_ITEM,
    name="Process batch job",
    what_it_will_do="Process 1000 records in batches"
)

for batch in batches:
    child_id = tracker.create_activity(
        type=ActivityType.AGENT_ACTION,
        name=f"Process batch {batch.id}",
        what_it_will_do=f"Process {len(batch.records)} records",
        parent_id=parent_id
    )
    
    process_batch(batch)
    
    tracker.complete_activity(
        child_id,
        f"Processed {len(batch.records)} records successfully"
    )

tracker.complete_activity(parent_id, "All batches processed")
```

### Example 3: WebSocket Streaming

```javascript
// Connect to activity stream
const ws = new WebSocket('ws://localhost:18080/activity/stream');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.event === 'started') {
        console.log(`Activity started: ${data.activity.name}`);
        console.log(`Doing: ${data.activity.what_its_doing}`);
    } else if (data.event === 'completed') {
        console.log(`Activity completed: ${data.activity.name}`);
        console.log(`Result: ${data.activity.what_it_did}`);
    }
};
```

## Monitoring Dashboard Features

The monitoring dashboard (`/monitor`) provides:

1. **System Overview**
   - Active task count
   - Total activities processed
   - Success rate percentage
   - Average duration metrics

2. **Real-time Activity Feed**
   - Currently executing activities
   - Live updates via WebSocket
   - Progress indicators

3. **Decision History**
   - Recent decisions made
   - Decision reasoning
   - Outcomes and results

4. **Activity Categories**
   - Recent completions
   - Recent failures with errors
   - Thread activities
   - Agent actions

5. **Visual Design**
   - Gradient background
   - Color-coded status indicators
   - Responsive grid layout
   - Smooth animations

## Benefits

1. **Complete Observability**: Every decision and action is tracked
2. **Debugging Support**: Detailed activity history for troubleshooting
3. **Audit Trail**: Comprehensive logs for compliance and review
4. **Performance Monitoring**: Duration tracking and success rates
5. **Real-time Visibility**: Live updates of system activities
6. **Hierarchical Tracking**: Parent-child relationships for complex workflows

## Best Practices

1. **Always provide descriptive names** for activities
2. **Include context data** for debugging
3. **Track both successes and failures** with appropriate messages
4. **Use parent-child relationships** for nested operations
5. **Limit result data size** to prevent memory issues
6. **Use appropriate activity types** for categorization
7. **Include error details** when activities fail

## Future Enhancements

Potential improvements to consider:
- Persistent storage of activities in database
- Activity replay functionality
- Advanced filtering and search
- Export to various formats (CSV, JSON, etc.)
- Alerting on specific activity patterns
- Performance profiling integration
- Distributed tracing support
- Machine learning on activity patterns

## Conclusion

The activity tracking system provides comprehensive visibility into the Codex Orchestrator's operations. By tracking what the system will do, is doing, and has done, it ensures complete transparency and aids in debugging, monitoring, and optimization of the orchestration platform.