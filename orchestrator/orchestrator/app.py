from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os
from pathlib import Path
import asyncio
import contextlib
import logging
from .routers import projects, workitems
from .routers import observability, scheduler
from .routers import activity  # New activity tracking router
from .config import settings
from .middleware import RequestIDMiddleware
from fastapi.middleware.cors import CORSMiddleware
from .monitoring_dashboard import get_dashboard_html
from .activity_tracker import tracker, ActivityType, track_async_task

logger = logging.getLogger(__name__)


tags_metadata = [
    {"name": "projects", "description": "Manage projects, visions, and requirements."},
    {"name": "work-items", "description": "Track work items, runs, approvals, and tools."},
    {"name": "scheduler", "description": "Simple dependency-aware queue and tick processing."},
    {"name": "observability", "description": "Health, metrics, logs, and traces (stub)."},
    {"name": "activity", "description": "Real-time activity tracking and decision monitoring."},
]


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        openapi_tags=tags_metadata,
        description="MVP Codex Orchestrator control plane API",
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=(settings.cors_origins.split(",") if getattr(settings, "cors_origins", "*") != "*" else ["*"]),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects.router, prefix="/projects", tags=["projects"])
    app.include_router(workitems.router, prefix="/work-items", tags=["work-items"])
    app.include_router(observability.router, prefix="/observability", tags=["observability"])
    app.include_router(scheduler.router, prefix="/scheduler", tags=["scheduler"])
    app.include_router(activity.router, prefix="/activity", tags=["activity"])
    
    # Add monitoring dashboard route
    @app.get("/monitor", response_class=HTMLResponse, include_in_schema=False)
    async def monitoring_dashboard(request: Request):
        """Serve the activity monitoring dashboard."""
        return HTMLResponse(content=get_dashboard_html())

    # Optional background scheduler tick
    if settings.scheduler_background_interval and settings.scheduler_background_interval > 0:
        from .db import SessionLocal
        from . import crud

        @track_async_task("Background scheduler tick processing")
        async def _bg_tick():
            """Background task that processes scheduler queue."""
            activity_id = tracker.create_activity(
                type=ActivityType.THREAD,
                name="Background Scheduler",
                what_it_will_do=f"Process scheduler queue every {settings.scheduler_background_interval} seconds"
            )
            tracker.start_activity(activity_id, "Background scheduler started")
            
            try:
                tick_count = 0
                while True:
                    # Track each tick
                    tick_activity = tracker.create_activity(
                        type=ActivityType.AGENT_ACTION,
                        name=f"Scheduler Tick #{tick_count}",
                        what_it_will_do="Process pending work items",
                        parent_id=activity_id
                    )
                    tracker.start_activity(tick_activity, "Processing scheduler queue")
                    
                    # run tick in a short-lived session
                    db = SessionLocal()
                    try:
                        processed = crud.scheduler_tick(db)
                        tracker.complete_activity(
                            tick_activity,
                            f"Processed {processed} items",
                            result={"processed": processed}
                        )
                        tick_count += 1
                    except Exception as e:
                        tracker.fail_activity(tick_activity, str(e))
                        logger.error(f"Background tick failed: {e}")
                    finally:
                        db.close()
                    
                    await asyncio.sleep(settings.scheduler_background_interval)
            except asyncio.CancelledError:
                tracker.complete_activity(activity_id, f"Background scheduler stopped after {tick_count} ticks")
                return

        @app.on_event("startup")
        async def _start_bg():
            app.state._bg_task = asyncio.create_task(_bg_tick())

        @app.on_event("shutdown")
        async def _stop_bg():
            task = getattr(app.state, "_bg_task", None)
            if task:
                task.cancel()
                with contextlib.suppress(Exception):
                    await task

    # Optional static UI mount (only if folder exists)
    try:
        repo_root = Path(__file__).resolve().parents[2]
        ui_dir = repo_root / "ui"
        if ui_dir.exists() and ui_dir.is_dir():
            app.mount("/ui", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    except Exception:
        pass

    return app


app = create_app()
