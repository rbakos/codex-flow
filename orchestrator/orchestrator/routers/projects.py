from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import SessionLocal, Base, engine
from .. import schemas, crud, models


router = APIRouter()


def get_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", response_model=schemas.ProjectOut, status_code=201, summary="Create a project")
def create_project(payload: schemas.ProjectCreate, db: Session = Depends(get_db)):
    return crud.create_project(db, name=payload.name, description=payload.description)


@router.get("/", response_model=list[schemas.ProjectOut], summary="List projects")
def list_projects(db: Session = Depends(get_db)):
    return db.query(models.Project).order_by(models.Project.id.asc()).all()


@router.post(
    "/{project_id}/vision",
    response_model=schemas.VisionOut,
    status_code=201,
    summary="Submit project vision",
)
def submit_vision(project_id: int, payload: schemas.VisionCreate, db: Session = Depends(get_db)):
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return crud.create_vision(db, project=project, content=payload.content)


@router.post(
    "/{project_id}/requirements/propose",
    response_model=schemas.RequirementsDraftOut,
    summary="Propose requirements from latest vision",
)
def propose_requirements(project_id: int, db: Session = Depends(get_db)):
    project = crud.get_project(db, project_id)
    if not project or not project.visions:
        raise HTTPException(status_code=404, detail="Project or vision not found")
    vision = project.visions[-1]
    existing = crud.get_requirements(db, vision.id)
    if existing:
        return existing
    return crud.propose_requirements(db, vision)


@router.post(
    "/{project_id}/requirements/approve",
    response_model=schemas.RequirementsDraftOut,
    summary="Approve latest requirements draft",
)
def approve_latest(project_id: int, db: Session = Depends(get_db)):
    project = crud.get_project(db, project_id)
    if not project or not project.visions:
        raise HTTPException(status_code=404, detail="Project or vision not found")
    vision = project.visions[-1]
    draft = crud.get_requirements(db, vision.id)
    if not draft:
        raise HTTPException(status_code=404, detail="No draft to approve")
    return crud.approve_requirements(db, draft)


@router.post("/{project_id}/quota", response_model=schemas.QuotaOut, summary="Set project usage quota")
def set_project_quota(project_id: int, payload: schemas.QuotaUpdate, db: Session = Depends(get_db)):
    pr = crud.get_project(db, project_id)
    if not pr:
        raise HTTPException(status_code=404, detail="Project not found")
    q = crud.set_quota(db, project_id, payload.max_runs_per_day)
    return schemas.QuotaOut(
        project_id=project_id,
        max_runs_per_day=q.max_runs_per_day,
        runs_today=q.runs_today,
        window_start=q.window_start.isoformat(),
    )
