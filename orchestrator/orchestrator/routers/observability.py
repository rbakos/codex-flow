from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import SessionLocal, Base, engine
from .. import models
from ..crud import get_quota


router = APIRouter()


def get_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get(
    "/metrics",
    summary="Service metrics",
    description="Basic counters for projects, work items, runs, and pending approvals.",
)
def metrics(db: Session = Depends(get_db)):
    projects = db.query(models.Project).count()
    work_items = db.query(models.WorkItem).count()
    runs = db.query(models.Run).count()
    pending_approvals = db.query(models.ApprovalRequest).filter_by(status="pending").count()
    return {
        "projects": projects,
        "work_items": work_items,
        "runs": runs,
        "pending_approvals": pending_approvals,
    }


@router.get("/health", summary="Liveness check")
def health():
    return {"status": "ok"}


@router.get("/ping", summary="Quick ping")
def ping():
    return {"pong": True}


@router.get(
    "/traces",
    summary="Trace listing stub",
    description=(
        "Returns a lightweight view of recent runs with their trace identifiers. "
        "For MVP, trace IDs are generated UUIDs when runs start."
    ),
)
def traces(db: Session = Depends(get_db)):
    items = (
        db.query(models.Run)
        .order_by(models.Run.id.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "run_id": r.id,
            "work_item_id": r.work_item_id,
            "status": r.status,
            "trace_id": r.trace_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in items
    ]


@router.get(
    "/usage",
    summary="Usage/quotas snapshot",
    description="Returns per-project quotas and current usage for quick budgeting dashboards.",
)
def usage(db: Session = Depends(get_db)):
    rows = db.query(models.Project).all()
    out = []
    for pr in rows:
        q = get_quota(db, pr.id)
        out.append(
            {
                "project_id": pr.id,
                "name": pr.name,
                "max_runs_per_day": q.max_runs_per_day,
                "runs_today": q.runs_today,
                "window_start": q.window_start.isoformat(),
            }
        )
    return out
