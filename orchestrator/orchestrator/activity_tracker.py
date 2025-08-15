"""
Activity Tracking and Decision Logging System.
Provides comprehensive visibility into all system decisions and thread activities.
"""
import asyncio
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from dataclasses import dataclass, asdict
import json
import logging
from contextlib import contextmanager
import functools
import inspect

logger = logging.getLogger(__name__)


class ActivityStatus(str, Enum):
    """Status of an activity or decision."""
    PLANNED = "planned"          # What it will be doing
    IN_PROGRESS = "in_progress"  # What it's doing
    COMPLETED = "completed"      # What it has done
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActivityType(str, Enum):
    """Type of activity being tracked."""
    DECISION = "decision"
    THREAD = "thread"
    ASYNC_TASK = "async_task"
    API_CALL = "api_call"
    DATABASE_OPERATION = "database_operation"
    AI_INFERENCE = "ai_inference"
    WORK_ITEM = "work_item"
    AGENT_ACTION = "agent_action"
    SCHEDULER_TICK = "scheduler_tick"


@dataclass
class Activity:
    """Represents a tracked activity in the system."""
    id: str
    type: ActivityType
    status: ActivityStatus
    name: str
    description: str
    what_it_will_do: str
    what_its_doing: str
    what_it_did: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    parent_id: Optional[str] = None
    thread_id: Optional[int] = None
    context: Dict[str, Any] = None
    error: Optional[str] = None
    result: Optional[Any] = None
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime objects to ISO format
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        return data


class ActivityTracker:
    """
    Singleton tracker for all system activities and decisions.
    Provides real-time visibility into what the system is doing.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.activities: Dict[str, Activity] = {}
        self.active_threads: Dict[int, str] = {}
        self.decision_history: List[Activity] = []
        self._lock = threading.Lock()
        self._listeners: List[Callable] = []
        self._initialized = True
        
        logger.info("Activity Tracker initialized")
    
    def create_activity(self,
                       type: ActivityType,
                       name: str,
                       what_it_will_do: str,
                       parent_id: Optional[str] = None,
                       context: Optional[Dict[str, Any]] = None) -> str:
        """
        Create a new activity and return its ID.
        
        Args:
            type: Type of activity
            name: Name of the activity
            what_it_will_do: Description of planned action
            parent_id: ID of parent activity if nested
            context: Additional context data
        
        Returns:
            Activity ID
        """
        activity_id = str(uuid.uuid4())
        
        activity = Activity(
            id=activity_id,
            type=type,
            status=ActivityStatus.PLANNED,
            name=name,
            description=f"Planning: {name}",
            what_it_will_do=what_it_will_do,
            what_its_doing="",
            what_it_did="",
            parent_id=parent_id,
            thread_id=threading.current_thread().ident,
            context=context or {},
            metadata={}
        )
        
        with self._lock:
            self.activities[activity_id] = activity
            
            if type == ActivityType.DECISION:
                self.decision_history.append(activity)
        
        self._notify_listeners(activity, "created")
        logger.info(f"Activity created: {activity_id} - {name} - Will: {what_it_will_do}")
        
        return activity_id
    
    def start_activity(self, activity_id: str, what_its_doing: str):
        """Mark activity as in progress."""
        with self._lock:
            if activity_id in self.activities:
                activity = self.activities[activity_id]
                activity.status = ActivityStatus.IN_PROGRESS
                activity.what_its_doing = what_its_doing
                activity.started_at = datetime.utcnow()
                activity.description = f"Executing: {activity.name}"
                
                self._notify_listeners(activity, "started")
                logger.info(f"Activity started: {activity_id} - Doing: {what_its_doing}")
    
    def complete_activity(self, 
                         activity_id: str, 
                         what_it_did: str,
                         result: Optional[Any] = None):
        """Mark activity as completed."""
        with self._lock:
            if activity_id in self.activities:
                activity = self.activities[activity_id]
                activity.status = ActivityStatus.COMPLETED
                activity.what_it_did = what_it_did
                activity.completed_at = datetime.utcnow()
                activity.result = result
                activity.description = f"Completed: {activity.name}"
                
                if activity.started_at:
                    duration = (activity.completed_at - activity.started_at).total_seconds() * 1000
                    activity.duration_ms = duration
                
                self._notify_listeners(activity, "completed")
                logger.info(f"Activity completed: {activity_id} - Did: {what_it_did} - Duration: {activity.duration_ms}ms")
    
    def fail_activity(self, activity_id: str, error: str):
        """Mark activity as failed."""
        with self._lock:
            if activity_id in self.activities:
                activity = self.activities[activity_id]
                activity.status = ActivityStatus.FAILED
                activity.error = error
                activity.completed_at = datetime.utcnow()
                activity.description = f"Failed: {activity.name}"
                activity.what_it_did = f"Failed: {error}"
                
                if activity.started_at:
                    duration = (activity.completed_at - activity.started_at).total_seconds() * 1000
                    activity.duration_ms = duration
                
                self._notify_listeners(activity, "failed")
                logger.error(f"Activity failed: {activity_id} - Error: {error}")
    
    def add_listener(self, callback: Callable):
        """Add a listener for activity updates."""
        self._listeners.append(callback)
    
    def _notify_listeners(self, activity: Activity, event: str):
        """Notify all listeners of activity changes."""
        for listener in self._listeners:
            try:
                listener(activity, event)
            except Exception as e:
                logger.error(f"Error notifying listener: {e}")
    
    def get_active_activities(self) -> List[Activity]:
        """Get all currently active activities."""
        with self._lock:
            return [a for a in self.activities.values() 
                   if a.status == ActivityStatus.IN_PROGRESS]
    
    def get_activity_tree(self, parent_id: Optional[str] = None) -> Dict[str, Any]:
        """Get hierarchical tree of activities."""
        with self._lock:
            activities = []
            for activity in self.activities.values():
                if activity.parent_id == parent_id:
                    children = self.get_activity_tree(activity.id)
                    activity_dict = activity.to_dict()
                    if children:
                        activity_dict['children'] = children
                    activities.append(activity_dict)
            return activities
    
    def get_thread_activities(self, thread_id: int) -> List[Activity]:
        """Get all activities for a specific thread."""
        with self._lock:
            return [a for a in self.activities.values() 
                   if a.thread_id == thread_id]
    
    def get_decision_history(self) -> List[Activity]:
        """Get history of all decisions made."""
        with self._lock:
            return list(self.decision_history)
    
    def export_activities(self, format: str = "json") -> str:
        """Export all activities in specified format."""
        with self._lock:
            activities_data = [a.to_dict() for a in self.activities.values()]
            
            if format == "json":
                return json.dumps(activities_data, indent=2)
            else:
                raise ValueError(f"Unsupported format: {format}")


# Global tracker instance
tracker = ActivityTracker()


# Decorators for automatic activity tracking

def track_decision(what_it_will_do: str):
    """Decorator to track decision-making functions."""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            activity_id = tracker.create_activity(
                type=ActivityType.DECISION,
                name=func.__name__,
                what_it_will_do=what_it_will_do,
                context={"args": str(args), "kwargs": str(kwargs)}
            )
            
            tracker.start_activity(activity_id, f"Making decision in {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                tracker.complete_activity(
                    activity_id,
                    f"Decision made: {func.__name__} returned {type(result).__name__}",
                    result=str(result)[:1000]  # Limit result size
                )
                return result
            except Exception as e:
                tracker.fail_activity(activity_id, str(e))
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            activity_id = tracker.create_activity(
                type=ActivityType.DECISION,
                name=func.__name__,
                what_it_will_do=what_it_will_do,
                context={"args": str(args), "kwargs": str(kwargs)}
            )
            
            tracker.start_activity(activity_id, f"Making decision in {func.__name__}")
            
            try:
                result = func(*args, **kwargs)
                tracker.complete_activity(
                    activity_id,
                    f"Decision made: {func.__name__} returned {type(result).__name__}",
                    result=str(result)[:1000]
                )
                return result
            except Exception as e:
                tracker.fail_activity(activity_id, str(e))
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def track_thread(what_it_will_do: str):
    """Decorator to track thread execution."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            activity_id = tracker.create_activity(
                type=ActivityType.THREAD,
                name=f"Thread: {func.__name__}",
                what_it_will_do=what_it_will_do,
                context={"args": str(args), "kwargs": str(kwargs)}
            )
            
            tracker.start_activity(activity_id, f"Thread running: {func.__name__}")
            
            try:
                result = func(*args, **kwargs)
                tracker.complete_activity(
                    activity_id,
                    f"Thread completed: {func.__name__}",
                    result=str(result)[:1000]
                )
                return result
            except Exception as e:
                tracker.fail_activity(activity_id, str(e))
                raise
        return wrapper
    return decorator


def track_async_task(what_it_will_do: str):
    """Decorator to track async tasks."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            activity_id = tracker.create_activity(
                type=ActivityType.ASYNC_TASK,
                name=f"Task: {func.__name__}",
                what_it_will_do=what_it_will_do,
                context={"args": str(args), "kwargs": str(kwargs)}
            )
            
            tracker.start_activity(activity_id, f"Async task executing: {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                tracker.complete_activity(
                    activity_id,
                    f"Async task completed: {func.__name__}",
                    result=str(result)[:1000]
                )
                return result
            except Exception as e:
                tracker.fail_activity(activity_id, str(e))
                raise
        return wrapper
    return decorator


@contextmanager
def track_activity(type: ActivityType, name: str, what_it_will_do: str):
    """Context manager for tracking activities."""
    activity_id = tracker.create_activity(
        type=type,
        name=name,
        what_it_will_do=what_it_will_do
    )
    
    tracker.start_activity(activity_id, f"Executing: {name}")
    
    try:
        yield activity_id
        tracker.complete_activity(activity_id, f"Completed: {name}")
    except Exception as e:
        tracker.fail_activity(activity_id, str(e))
        raise


class ThreadTracker(threading.Thread):
    """Enhanced Thread class with automatic activity tracking."""
    
    def __init__(self, *args, what_it_will_do: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.what_it_will_do = what_it_will_do or f"Thread: {self.name}"
        self.activity_id = None
    
    def run(self):
        """Override run to add tracking."""
        self.activity_id = tracker.create_activity(
            type=ActivityType.THREAD,
            name=self.name,
            what_it_will_do=self.what_it_will_do
        )
        
        tracker.start_activity(self.activity_id, f"Thread {self.name} is running")
        
        try:
            super().run()
            tracker.complete_activity(
                self.activity_id,
                f"Thread {self.name} completed successfully"
            )
        except Exception as e:
            tracker.fail_activity(self.activity_id, str(e))
            raise


class AsyncTaskTracker:
    """Wrapper for async tasks with automatic tracking."""
    
    @staticmethod
    async def create_task(coro, name: str, what_it_will_do: str):
        """Create and track an async task."""
        activity_id = tracker.create_activity(
            type=ActivityType.ASYNC_TASK,
            name=name,
            what_it_will_do=what_it_will_do
        )
        
        tracker.start_activity(activity_id, f"Async task {name} is running")
        
        try:
            result = await coro
            tracker.complete_activity(
                activity_id,
                f"Async task {name} completed",
                result=str(result)[:1000]
            )
            return result
        except Exception as e:
            tracker.fail_activity(activity_id, str(e))
            raise