from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import SessionLocal, Base, engine
from .. import schemas, crud
from ..config import settings


router = APIRouter()


def get_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", response_model=schemas.WorkItemOut, status_code=201, summary="Create work item")
def create_work_item(payload: schemas.WorkItemCreate, db: Session = Depends(get_db)):
    return crud.create_work_item(db, project_id=payload.project_id, title=payload.title, description=payload.description)


@router.post(
    "/{wi_id}/start",
    response_model=schemas.RunOut,
    responses={403: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}},
    summary="Start a run for a work item",
)
def start_run(wi_id: int, db: Session = Depends(get_db)):
    wi = crud.get_work_item(db, wi_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    if settings.require_approval:
        latest = crud.get_latest_approval(db, wi)
        if not latest or latest.status != "approved":
            raise HTTPException(status_code=403, detail="Approval required before starting run")
    return crud.start_run(db, wi)


@router.post(
    "/runs/{run_id}/complete",
    response_model=schemas.RunOut,
    responses={404: {"model": schemas.ErrorOut}},
    summary="Complete a run",
)
def complete_run(run_id: int, success: bool = True, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return crud.complete_run(db, run, success=success)


@router.post(
    "/{wi_id}/approvals",
    response_model=schemas.ApprovalOut,
    status_code=201,
    responses={404: {"model": schemas.ErrorOut}},
    summary="Request an approval",
)
def request_approval(wi_id: int, payload: schemas.ApprovalCreate | None = None, db: Session = Depends(get_db)):
    wi = crud.get_work_item(db, wi_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    reason = payload.reason if payload else None
    return crud.create_approval_request(db, wi, reason)


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=schemas.ApprovalOut,
    responses={404: {"model": schemas.ErrorOut}},
    summary="Approve an approval request",
)
def approve(approval_id: int, db: Session = Depends(get_db)):
    ar = db.get(crud.models.ApprovalRequest, approval_id)
    if not ar:
        raise HTTPException(status_code=404, detail="Approval not found")
    return crud.approve_request(db, ar)


@router.get(
    "/{wi_id}",
    response_model=schemas.WorkItemOut,
    responses={404: {"model": schemas.ErrorOut}},
    summary="Get a work item",
)
def get_work_item(wi_id: int, db: Session = Depends(get_db)):
    wi = crud.get_work_item(db, wi_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    return wi


@router.get(
    "/{wi_id}/runs",
    response_model=list[schemas.RunOut],
    responses={404: {"model": schemas.ErrorOut}},
    summary="List runs for a work item",
)
def list_runs(wi_id: int, db: Session = Depends(get_db)):
    wi = crud.get_work_item(db, wi_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    return wi.runs


@router.get(
    "/runs/{run_id}",
    response_model=schemas.RunOut,
    responses={404: {"model": schemas.ErrorOut}},
    summary="Get a run by ID",
)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post(
    "/{wi_id}/tool-recipe",
    response_model=schemas.ToolRecipeOut,
    responses={404: {"model": schemas.ErrorOut}},
    summary="Set a tool recipe for a work item",
)
def set_tool_recipe(wi_id: int, payload: schemas.ToolRecipeCreate, db: Session = Depends(get_db)):
    wi = crud.get_work_item(db, wi_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    return crud.set_tool_recipe(db, wi, payload.yaml)


@router.get(
    "/{wi_id}/tool-recipe",
    response_model=schemas.ToolRecipeOut,
    responses={404: {"model": schemas.ErrorOut}},
    summary="Get the tool recipe for a work item",
)
def get_tool_recipe(wi_id: int, db: Session = Depends(get_db)):
    wi = crud.get_work_item(db, wi_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    tr = crud.get_tool_recipe(db, wi)
    if not tr:
        raise HTTPException(status_code=404, detail="Tool recipe not found")
    return tr
@router.get(
    "/runs/{run_id}/logs",
    summary="Get run logs",
    description=(
        "Returns raw text logs by default. Use query params `format=json` "
        "to receive structured lines, with optional `q`, `limit`, and `offset` filtering."
    ),
)
def get_run_logs(
    run_id: int,
    db: Session = Depends(get_db),
    format: str = "text",
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    content = run.logs or ""
    if format == "json":
        lines = content.splitlines()
        if q:
            lines = [ln for ln in lines if q in ln]
        total = len(lines)
        if offset:
            lines = lines[offset:]
        if limit is not None:
            lines = lines[: max(limit, 0)]
        return JSONResponse({"total": total, "returned": len(lines), "lines": lines})
    return Response(content=content, media_type="text/plain")


@router.post(
    "/runs/{run_id}/logs",
    summary="Append a log line to a run",
    responses={404: {"model": schemas.ErrorOut}},
)
def append_run_log(run_id: int, payload: schemas.LogAppend, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return crud.append_run_log(db, run, payload.line)


@router.post(
    "/runs/{run_id}/steps",
    response_model=schemas.RunStepOut,
    summary="Record a structured step event (name/status/duration)",
)
def post_run_step(run_id: int, payload: schemas.RunStepCreate, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    step = crud.add_run_step(
        db,
        run,
        name=payload.name,
        status=payload.status or "succeeded",
        duration_seconds=payload.duration_seconds,
        started_at=payload.started_at,
        finished_at=payload.finished_at,
    )
    return step


@router.get(
    "/runs/{run_id}/steps",
    response_model=list[schemas.RunStepOut],
    summary="List structured step events for a run",
)
def get_run_steps(run_id: int, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return crud.list_run_steps(db, run)


@router.patch(
    "/runs/steps/{step_id}",
    response_model=schemas.RunStepOut,
    summary="Update a step (status/finished_at/duration)",
)
def patch_run_step(step_id: int, payload: schemas.RunStepUpdate, db: Session = Depends(get_db)):
    step = crud.get_run_step(db, step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    return crud.update_run_step(
        db,
        step,
        status=payload.status,
        duration_seconds=payload.duration_seconds,
        finished_at=payload.finished_at,
    )


@router.post(
    "/runs/{run_id}/info-requests",
    response_model=schemas.InfoRequestOut,
    summary="Create an info request for a run",
)
def create_info_request(run_id: int, payload: schemas.InfoRequestCreate, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    ir = crud.create_info_request(db, run, payload.prompt, payload.required_keys)
    # shape response
    return schemas.InfoRequestOut(
        id=ir.id,
        run_id=ir.run_id,
        status=ir.status,
        prompt=ir.prompt,
        required_keys=__import__("json").loads(ir.required_keys or "[]"),
        responses=(__import__("json").loads(ir.responses) if ir.responses else None),
    )


@router.get(
    "/runs/{run_id}/info-requests",
    response_model=list[schemas.InfoRequestOut],
    summary="List info requests for a run",
)
def list_info_requests(run_id: int, db: Session = Depends(get_db), plaintext: bool = False, x_orch_secret: str | None = None):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    items = crud.list_info_requests(db, run)
    out = []
    import json as _json
    from ..crypto_utils import decrypt_text
    from ..config import settings

    for ir in items:
        responses_obj = None
        if ir.responses and plaintext and x_orch_secret and x_orch_secret == settings.secret_key:
            # attempt decrypt if encrypted
            plain, _ = decrypt_text(ir.responses)
            try:
                responses_obj = _json.loads(plain)
            except Exception:
                responses_obj = None
        out.append(
            schemas.InfoRequestOut(
                id=ir.id,
                run_id=ir.run_id,
                status=ir.status,
                prompt=ir.prompt,
                required_keys=_json.loads(ir.required_keys or "[]"),
                responses=responses_obj,
            )
        )
    return out


@router.post(
    "/runs/info-requests/{req_id}/respond",
    response_model=schemas.InfoRequestOut,
    summary="Respond to an info request",
)
def respond_info_request(req_id: int, payload: schemas.InfoRequestRespond, db: Session = Depends(get_db)):
    ir = crud.get_info_request(db, req_id)
    if not ir:
        raise HTTPException(status_code=404, detail="Info request not found")
    ir = crud.respond_info_request(db, ir, payload.values)
    import json as _json

    return schemas.InfoRequestOut(
        id=ir.id,
        run_id=ir.run_id,
        status=ir.status,
        prompt=ir.prompt,
        required_keys=_json.loads(ir.required_keys or "[]"),
        responses=(_json.loads(ir.responses) if ir.responses else None),
    )


@router.post("/runs/{run_id}/claim", response_model=schemas.ClaimOut, summary="Claim a running run")
def claim_run(run_id: int, payload: schemas.ClaimIn, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    ok = crud.claim_run(db, run, payload.agent_id, ttl_seconds=payload.ttl_seconds or 300)
    expires_in = (payload.ttl_seconds or 300) if ok else None
    return schemas.ClaimOut(success=ok, claimed_by=run.claimed_by if ok else None, expires_in=expires_in)


@router.post("/runs/{run_id}/heartbeat", response_model=schemas.ClaimOut, summary="Heartbeat a claimed run")
def heartbeat_run(run_id: int, payload: schemas.HeartbeatIn, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    ok = crud.heartbeat_run(db, run, payload.agent_id)
    return schemas.ClaimOut(success=ok, claimed_by=run.claimed_by if ok else None, expires_in=None)


@router.post(
    "/{wi_id}/policy",
    response_model=schemas.WorkItemOut,
    summary="Set per-work-item retry/backoff policy overrides",
)
def set_work_item_policy(
    wi_id: int,
    payload: schemas.WorkItemPolicyUpdate,
    db: Session = Depends(get_db),
):
    wi = crud.get_work_item(db, wi_id)
    if not wi:
        raise HTTPException(status_code=404, detail="Work item not found")
    if payload.max_retries is not None:
        wi.max_retries = payload.max_retries
    if payload.backoff_base_seconds is not None:
        wi.backoff_base_seconds = payload.backoff_base_seconds
    if payload.backoff_jitter_seconds is not None:
        wi.backoff_jitter_seconds = payload.backoff_jitter_seconds
    db.add(wi)
    db.commit()
    db.refresh(wi)
    return wi


@router.websocket("/runs/{run_id}/logs/ws")
async def logs_ws(websocket: WebSocket, run_id: int):
    await websocket.accept()
    # naive polling-based streamer; sends new lines as they appear
    sent_len = 0
    try:
        while True:
            # Using a short sleep inside the receive_text timeout could be added, but we just poll
            from ..db import SessionLocal

            db = SessionLocal()
            try:
                run = crud.get_run(db, run_id)
                if not run:
                    await websocket.send_text("[orchestrator] run not found")
                    await websocket.close(code=1008)
                    return
                content = run.logs or ""
                if len(content) > sent_len:
                    new = content[sent_len:]
                    for line in new.splitlines():
                        await websocket.send_text(line)
                    sent_len = len(content)
            finally:
                db.close()
            import asyncio

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
