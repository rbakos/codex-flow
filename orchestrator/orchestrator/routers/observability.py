from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import SessionLocal, Base, engine
from .. import models
from ..crud import get_quota, list_run_steps
from datetime import datetime


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

    # Per-status run counts
    by_status = {s: db.query(models.Run).filter_by(status=s).count() for s in [
        "pending", "running", "succeeded", "failed"
    ]}

    # Average duration (seconds) for finished runs
    finished = db.query(models.Run).filter(models.Run.finished_at.isnot(None)).all()
    avg_duration = None
    if finished:
        total = 0.0
        for r in finished:
            if r.started_at and r.finished_at:
                total += (r.finished_at - r.started_at).total_seconds()
        avg_duration = round(total / max(1, len(finished)), 3)

    # Histogram of run durations (seconds)
    buckets = [
        ("<1s", 0, 1),
        ("1-5s", 1, 5),
        ("5-10s", 5, 10),
        ("10-30s", 10, 30),
        ("30-60s", 30, 60),
        ("1-5m", 60, 300),
        (">5m", 300, None),
    ]
    hist = {name: 0 for name, *_ in buckets}
    for r in finished:
        if r.started_at and r.finished_at:
            dur = (r.finished_at - r.started_at).total_seconds()
            for name, lo, hi in buckets:
                if (dur >= lo) and (hi is None or dur < hi):
                    hist[name] += 1
                    break

    return {
        "projects": projects,
        "work_items": work_items,
        "runs": runs,
        "pending_approvals": pending_approvals,
        "runs_by_status": by_status,
        "runs_avg_duration_seconds": avg_duration,
        "runs_duration_histogram": hist,
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
    out = []
    for r in items:
        duration = None
        if r.started_at and r.finished_at:
            duration = (r.finished_at - r.started_at).total_seconds()
        out.append(
            {
                "run_id": r.id,
                "work_item_id": r.work_item_id,
                "status": r.status,
                "trace_id": r.trace_id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "duration_seconds": duration,
            }
        )
    return out


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


@router.get(
    "/runs/{run_id}",
    summary="Run detail with steps",
    description="Returns run info plus structured steps and computed duration.",
)
def run_detail(run_id: int, db: Session = Depends(get_db)):
    r = db.get(models.Run, run_id)
    if not r:
        return {"detail": "Run not found"}
    duration = None
    if r.started_at and r.finished_at:
        duration = (r.finished_at - r.started_at).total_seconds()
    steps = list_run_steps(db, r)
    return {
        "run": {
            "run_id": r.id,
            "work_item_id": r.work_item_id,
            "status": r.status,
            "trace_id": r.trace_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_seconds": duration,
            "claimed_by": r.claimed_by,
        },
        "steps": [
            {
                "id": s.id,
                "idx": s.idx,
                "name": s.name,
                "status": s.status,
                "duration_seconds": s.duration_seconds,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for s in steps
        ],
    }
