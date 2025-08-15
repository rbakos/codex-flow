"""
Activity tracking API endpoints.
Provides real-time visibility into system decisions and thread activities.
"""
from fastapi import APIRouter, HTTPException, WebSocket, Query
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import asyncio

from ..activity_tracker import (
    tracker, 
    Activity, 
    ActivityStatus,
    ActivityType
)

router = APIRouter()


@router.get("/active", response_model=List[Dict[str, Any]])
async def get_active_activities():
    """
    Get all currently active activities.
    Shows what the system is doing right now.
    """
    activities = tracker.get_active_activities()
    return [activity.to_dict() for activity in activities]


@router.get("/all", response_model=List[Dict[str, Any]])
async def get_all_activities(
    type: Optional[ActivityType] = None,
    status: Optional[ActivityStatus] = None,
    limit: int = Query(100, ge=1, le=1000)
):
    """
    Get all activities with optional filtering.
    
    Args:
        type: Filter by activity type
        status: Filter by activity status
        limit: Maximum number of activities to return
    """
    activities = list(tracker.activities.values())
    
    # Apply filters
    if type:
        activities = [a for a in activities if a.type == type]
    if status:
        activities = [a for a in activities if a.status == status]
    
    # Sort by started_at descending (most recent first)
    activities.sort(key=lambda a: a.started_at or datetime.min, reverse=True)
    
    # Apply limit
    activities = activities[:limit]
    
    return [activity.to_dict() for activity in activities]


@router.get("/tree", response_model=List[Dict[str, Any]])
async def get_activity_tree(parent_id: Optional[str] = None):
    """
    Get hierarchical tree of activities.
    Shows parent-child relationships between activities.
    """
    return tracker.get_activity_tree(parent_id)


@router.get("/decisions", response_model=List[Dict[str, Any]])
async def get_decision_history(limit: int = Query(50, ge=1, le=500)):
    """
    Get history of all decisions made by the system.
    Shows what decisions were made, why, and their outcomes.
    """
    decisions = tracker.get_decision_history()
    decisions = decisions[-limit:]  # Get last N decisions
    return [decision.to_dict() for decision in decisions]


@router.get("/thread/{thread_id}", response_model=List[Dict[str, Any]])
async def get_thread_activities(thread_id: int):
    """
    Get all activities for a specific thread.
    Shows everything a particular thread has done.
    """
    activities = tracker.get_thread_activities(thread_id)
    return [activity.to_dict() for activity in activities]


@router.get("/activity/{activity_id}", response_model=Dict[str, Any])
async def get_activity(activity_id: str):
    """
    Get details of a specific activity.
    Shows complete information about what happened.
    """
    if activity_id not in tracker.activities:
        raise HTTPException(status_code=404, detail="Activity not found")
    
    return tracker.activities[activity_id].to_dict()


@router.get("/export")
async def export_activities(format: str = Query("json", regex="^(json)$")):
    """
    Export all activities in specified format.
    Useful for audit trails and debugging.
    """
    try:
        export_data = tracker.export_activities(format)
        return {
            "format": format,
            "timestamp": datetime.utcnow().isoformat(),
            "data": json.loads(export_data) if format == "json" else export_data
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stats")
async def get_activity_stats():
    """
    Get statistics about system activities.
    Provides overview of what the system has been doing.
    """
    activities = list(tracker.activities.values())
    
    # Calculate statistics
    total = len(activities)
    by_status = {}
    by_type = {}
    total_duration = 0
    failed_count = 0
    
    for activity in activities:
        # Count by status
        by_status[activity.status] = by_status.get(activity.status, 0) + 1
        
        # Count by type
        by_type[activity.type] = by_type.get(activity.type, 0) + 1
        
        # Sum duration
        if activity.duration_ms:
            total_duration += activity.duration_ms
        
        # Count failures
        if activity.status == ActivityStatus.FAILED:
            failed_count += 1
    
    # Calculate average duration
    completed = [a for a in activities if a.status == ActivityStatus.COMPLETED]
    avg_duration = (
        sum(a.duration_ms for a in completed if a.duration_ms) / len(completed)
        if completed else 0
    )
    
    return {
        "total_activities": total,
        "by_status": by_status,
        "by_type": by_type,
        "total_duration_ms": total_duration,
        "average_duration_ms": avg_duration,
        "failure_rate": (failed_count / total * 100) if total > 0 else 0,
        "active_now": len(tracker.get_active_activities())
    }


@router.websocket("/stream")
async def activity_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time activity streaming.
    Provides live updates as activities occur.
    """
    await websocket.accept()
    
    # Queue for activity updates
    update_queue = asyncio.Queue()
    
    # Listener function
    def activity_listener(activity: Activity, event: str):
        asyncio.create_task(update_queue.put({
            "event": event,
            "activity": activity.to_dict(),
            "timestamp": datetime.utcnow().isoformat()
        }))
    
    # Register listener
    tracker.add_listener(activity_listener)
    
    try:
        # Send initial state
        await websocket.send_json({
            "event": "connected",
            "active_activities": [a.to_dict() for a in tracker.get_active_activities()],
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Stream updates
        while True:
            update = await update_queue.get()
            await websocket.send_json(update)
            
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        # Remove listener on disconnect
        tracker._listeners.remove(activity_listener)
        await websocket.close()


@router.get("/summary")
async def get_activity_summary():
    """
    Get a human-readable summary of recent system activity.
    Useful for understanding what the system has been doing.
    """
    activities = list(tracker.activities.values())
    activities.sort(key=lambda a: a.started_at or datetime.min, reverse=True)
    
    # Get last 10 activities
    recent = activities[:10]
    
    summary = {
        "current_status": "System is operational",
        "active_tasks": [],
        "recent_decisions": [],
        "recent_completions": [],
        "recent_failures": []
    }
    
    # Categorize activities
    for activity in recent:
        if activity.status == ActivityStatus.IN_PROGRESS:
            summary["active_tasks"].append({
                "name": activity.name,
                "doing": activity.what_its_doing,
                "started": activity.started_at.isoformat() if activity.started_at else None
            })
        elif activity.type == ActivityType.DECISION and activity.status == ActivityStatus.COMPLETED:
            summary["recent_decisions"].append({
                "name": activity.name,
                "decided": activity.what_it_did,
                "when": activity.completed_at.isoformat() if activity.completed_at else None
            })
        elif activity.status == ActivityStatus.COMPLETED:
            summary["recent_completions"].append({
                "name": activity.name,
                "completed": activity.what_it_did,
                "duration_ms": activity.duration_ms
            })
        elif activity.status == ActivityStatus.FAILED:
            summary["recent_failures"].append({
                "name": activity.name,
                "error": activity.error,
                "when": activity.completed_at.isoformat() if activity.completed_at else None
            })
    
    # Update status based on active tasks
    active_count = len(tracker.get_active_activities())
    if active_count == 0:
        summary["current_status"] = "System is idle"
    elif active_count < 5:
        summary["current_status"] = f"System is running {active_count} tasks"
    else:
        summary["current_status"] = f"System is busy with {active_count} active tasks"
    
    return summary