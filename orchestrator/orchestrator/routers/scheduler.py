from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import SessionLocal, Base, engine
from .. import schemas, crud


router = APIRouter()


def get_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post(
    "/enqueue",
    response_model=schemas.ScheduledTaskOut,
    status_code=201,
    summary="Enqueue a work item",
)
def enqueue(payload: schemas.EnqueueRequest, db: Session = Depends(get_db)):
    wi = crud.get_work_item(db, payload.work_item_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    st = crud.enqueue(db, wi, payload.depends_on_work_item_id, payload.priority or 0, payload.delay_seconds or 0)
    return schemas.ScheduledTaskOut(
        id=st.id,
        work_item_id=st.work_item_id,
        status=st.status,
        depends_on_work_item_id=st.depends_on_work_item_id,
        priority=st.priority,
        scheduled_for=st.scheduled_for.isoformat() if getattr(st, "scheduled_for", None) else None,
    )


@router.post(
    "/requeue/work-item",
    response_model=schemas.ScheduledTaskOut,
    summary="Requeue a work item with optional delay/backoff",
)
def requeue_work_item(payload: schemas.EnqueueRequest, db: Session = Depends(get_db)):
    wi = crud.get_work_item(db, payload.work_item_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    st = crud.enqueue(db, wi, payload.depends_on_work_item_id, payload.priority or 0, payload.delay_seconds or 0)
    return schemas.ScheduledTaskOut(
        id=st.id,
        work_item_id=st.work_item_id,
        status=st.status,
        depends_on_work_item_id=st.depends_on_work_item_id,
        priority=st.priority,
        scheduled_for=st.scheduled_for.isoformat() if getattr(st, "scheduled_for", None) else None,
    )


@router.post(
    "/requeue/run/{run_id}",
    response_model=schemas.ScheduledTaskOut,
    summary="Requeue a run's work item with optional backoff",
)
def requeue_run(run_id: int, payload: schemas.RequeueRunIn | None = None, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    wi = run.work_item
    delay = (payload.delay_seconds if payload else None) or 0
    if payload and payload.backoff:
        failures = db.query(crud.models.Run).filter_by(work_item_id=wi.id, status="failed").count()
        base = crud.settings.backoff_base_seconds
        delay = base * (2 ** max(0, failures))
    st = crud.enqueue(db, wi, None, (payload.priority if payload else 0) or 0, delay)
    return schemas.ScheduledTaskOut(
        id=st.id,
        work_item_id=st.work_item_id,
        status=st.status,
        depends_on_work_item_id=st.depends_on_work_item_id,
        priority=st.priority,
        scheduled_for=st.scheduled_for.isoformat() if getattr(st, "scheduled_for", None) else None,
    )


@router.post("/tick", summary="Process scheduler tick")
def tick(db: Session = Depends(get_db)):
    processed = crud.scheduler_tick(db)
    return {"processed": processed}


@router.get("/queue", response_model=list[schemas.ScheduledTaskOut], summary="List scheduled tasks")
def queue(db: Session = Depends(get_db)):
    items = crud.list_queue(db)
    return [
        schemas.ScheduledTaskOut(
            id=st.id,
            work_item_id=st.work_item_id,
            status=st.status,
            depends_on_work_item_id=st.depends_on_work_item_id,
            priority=st.priority,
            scheduled_for=st.scheduled_for.isoformat() if getattr(st, "scheduled_for", None) else None,
        )
        for st in items
    ]
