from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os
from pathlib import Path
import asyncio
import contextlib
from .routers import projects, workitems
from .routers import observability, scheduler
from .config import settings
from .middleware import RequestIDMiddleware
from fastapi.middleware.cors import CORSMiddleware


tags_metadata = [
    {"name": "projects", "description": "Manage projects, visions, and requirements."},
    {"name": "work-items", "description": "Track work items, runs, approvals, and tools."},
    {"name": "scheduler", "description": "Simple dependency-aware queue and tick processing."},
    {"name": "observability", "description": "Health, metrics, logs, and traces (stub)."},
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

    # Optional background scheduler tick
    if settings.scheduler_background_interval and settings.scheduler_background_interval > 0:
        from .db import SessionLocal
        from . import crud

        async def _bg_tick():
            try:
                while True:
                    # run tick in a short-lived session
                    db = SessionLocal()
                    try:
                        crud.scheduler_tick(db)
                    finally:
                        db.close()
                    await asyncio.sleep(settings.scheduler_background_interval)
            except asyncio.CancelledError:
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
