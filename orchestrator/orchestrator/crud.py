from sqlalchemy.orm import Session

from . import models
from .config import settings
from .planner import propose_requirements_from_openai
import yaml
import uuid
import json
from datetime import datetime, timedelta
import random
from .crypto_utils import encrypt_text
from .activity_tracker import tracker, ActivityType, track_activity


def create_project(db: Session, name: str, description: str | None = None) -> models.Project:
    """Create a new project with activity tracking."""
    with track_activity(
        ActivityType.DECISION,
        f"Create project: {name}",
        f"Will create new project '{name}' with usage quota initialization"
    ) as activity_id:
        project = models.Project(name=name, description=description)
        db.add(project)
        db.commit()
        db.refresh(project)
        # Initialize usage quota row (unlimited by default)
        q = models.UsageQuota(project_id=project.id, max_runs_per_day=0, runs_today=0)
        db.add(q)
        db.commit()
        
        tracker.complete_activity(
            activity_id,
            f"Successfully created project #{project.id}: {name}",
            result={"project_id": project.id, "name": name}
        )
        return project


def get_project(db: Session, project_id: int) -> models.Project | None:
    return db.get(models.Project, project_id)


def create_vision(db: Session, project: models.Project, content: str) -> models.Vision:
    v = models.Vision(project=project, content=content)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def propose_requirements(db: Session, vision: models.Vision) -> models.RequirementsDraft:
    """Propose requirements with decision tracking."""
    activity_id = tracker.create_activity(
        type=ActivityType.DECISION,
        name="Propose Requirements",
        what_it_will_do=f"Generate requirements draft for project '{vision.project.name}'",
        context={"vision_id": vision.id, "project_name": vision.project.name}
    )
    
    tracker.start_activity(activity_id, "Attempting to generate requirements using AI or fallback")
    
    # Try OpenAI-backed planner if enabled, otherwise fall back to deterministic draft.
    body = propose_requirements_from_openai(vision.project.name, vision.content) or (
        f"Proposed Requirements for project '{vision.project.name}':\n"
        f"- Goals: derive from vision text.\n"
        f"- MVP: implement minimal endpoints and CI.\n"
        f"- Non-Goals: items not in scope.\n"
        f"Vision Summary: {vision.content[:200]}"
    )
    
    draft = models.RequirementsDraft(vision=vision, draft=body, status="proposed")
    db.add(draft)
    db.commit()
    db.refresh(draft)
    
    tracker.complete_activity(
        activity_id,
        f"Created requirements draft for project '{vision.project.name}'",
        result={"draft_id": draft.id, "method": "AI" if "OpenAI" not in body[:50] else "fallback"}
    )
    
    return draft


def approve_requirements(db: Session, draft: models.RequirementsDraft) -> models.RequirementsDraft:
    draft.status = "approved"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def get_vision(db: Session, vision_id: int) -> models.Vision | None:
    return db.get(models.Vision, vision_id)


def get_requirements(db: Session, vision_id: int) -> models.RequirementsDraft | None:
    return db.query(models.RequirementsDraft).filter_by(vision_id=vision_id).one_or_none()


def create_work_item(db: Session, project_id: int, title: str, description: str | None = None) -> models.WorkItem:
    wi = models.WorkItem(project_id=project_id, title=title, description=description)
    db.add(wi)
    db.commit()
    db.refresh(wi)
    return wi


def transition_work_item(db: Session, wi: models.WorkItem, new_state: str) -> models.WorkItem:
    wi.state = new_state
    db.add(wi)
    db.commit()
    db.refresh(wi)
    return wi


def start_run(db: Session, wi: models.WorkItem) -> models.Run:
    """Start a run with comprehensive activity tracking."""
    with track_activity(
        ActivityType.WORK_ITEM,
        f"Start run for: {wi.title}",
        f"Will create and start execution run for work item #{wi.id}"
    ) as activity_id:
        # simple agent stub: mark running and append a log line
        tid = str(uuid.uuid4())
        run = models.Run(work_item=wi, status="running", logs=f"Starting run... trace_id={tid}\n", trace_id=tid)
        wi.state = "In Progress"
        db.add(run)
        db.add(wi)
        db.commit()
        db.refresh(run)
        
        tracker.complete_activity(
            activity_id,
            f"Started run #{run.id} for work item '{wi.title}'",
            result={"run_id": run.id, "work_item_id": wi.id, "trace_id": tid}
        )
        return run


def complete_run(db: Session, run: models.Run, success: bool = True) -> models.Run:
    """Complete a run with decision tracking for retry logic."""
    activity_id = tracker.create_activity(
        type=ActivityType.DECISION,
        name=f"Complete run #{run.id}",
        what_it_will_do=f"Will mark run as {'succeeded' if success else 'failed'} and handle retry logic"
    )
    
    tracker.start_activity(activity_id, f"Completing run with status: {'success' if success else 'failure'}")
    
    run.status = "succeeded" if success else "failed"
    run.logs = (run.logs or "") + ("Completed successfully.\n" if success else "Failed.\n")
    # mark finish time for duration metrics
    run.finished_at = datetime.utcnow()
    db.add(run)
    # advance work item
    wi = run.work_item
    wi.state = "Done" if success else "Review"
    db.add(wi)
    db.commit()
    db.refresh(run)
    
    retry_scheduled = False
    if not success and settings.max_retries > 0:
        failures = db.query(models.Run).filter_by(work_item_id=wi.id, status="failed").count()
        if failures <= settings.max_retries:
            base = getattr(settings, "backoff_base_seconds", 30)
            delay = base * (2 ** max(0, failures - 1))
            
            # Track retry decision
            retry_activity = tracker.create_activity(
                type=ActivityType.DECISION,
                name="Schedule retry",
                what_it_will_do=f"Schedule retry #{failures} with {delay}s delay",
                parent_id=activity_id
            )
            tracker.start_activity(retry_activity, f"Scheduling retry with backoff delay of {delay} seconds")
            
            # schedule retry with backoff
            st = models.ScheduledTask(
                work_item_id=wi.id,
                status="queued",
                priority=0,
                depends_on_work_item_id=None,
                scheduled_for=datetime.utcnow() + __import__("datetime").timedelta(seconds=delay),
            )
            db.add(st)
            db.commit()
            retry_scheduled = True
            
            tracker.complete_activity(
                retry_activity,
                f"Scheduled retry #{failures} for work item #{wi.id}",
                result={"retry_number": failures, "delay_seconds": delay}
            )
    
    tracker.complete_activity(
        activity_id,
        f"Run #{run.id} completed as {'success' if success else 'failure'}" + 
        (f", retry scheduled" if retry_scheduled else ""),
        result={"run_id": run.id, "success": success, "retry_scheduled": retry_scheduled}
    )
    
    return run


def append_run_log(db: Session, run: models.Run, line: str) -> models.Run:
    run.logs = (run.logs or "") + (line if line.endswith("\n") else line + "\n")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_work_item(db: Session, wi_id: int) -> models.WorkItem | None:
    return db.get(models.WorkItem, wi_id)


def get_run(db: Session, run_id: int) -> models.Run | None:
    return db.get(models.Run, run_id)


def create_approval_request(db: Session, wi: models.WorkItem, reason: str | None = None) -> models.ApprovalRequest:
    ar = models.ApprovalRequest(work_item=wi, status="pending", reason=reason or "")
    db.add(ar)
    db.commit()
    db.refresh(ar)
    return ar


def approve_request(db: Session, ar: models.ApprovalRequest) -> models.ApprovalRequest:
    ar.status = "approved"
    db.add(ar)
    db.commit()
    db.refresh(ar)
    return ar


def get_latest_approval(db: Session, wi: models.WorkItem) -> models.ApprovalRequest | None:
    return (
        db.query(models.ApprovalRequest)
        .filter_by(work_item_id=wi.id)
        .order_by(models.ApprovalRequest.id.desc())
        .first()
    )


def enqueue(
    db: Session,
    wi: models.WorkItem,
    depends_on_id: int | None = None,
    priority: int | None = 0,
    delay_seconds: int | None = 0,
) -> models.ScheduledTask:
    st = models.ScheduledTask(
        work_item_id=wi.id,
        status="queued",
        depends_on_work_item_id=depends_on_id,
        priority=priority or 0,
        scheduled_for=datetime.utcnow() + timedelta(seconds=delay_seconds or 0),
    )
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


def list_queue(db: Session) -> list[models.ScheduledTask]:
    return db.query(models.ScheduledTask).all()


def get_quota(db: Session, project_id: int) -> models.UsageQuota:
    q = db.query(models.UsageQuota).filter_by(project_id=project_id).one_or_none()
    if not q:
        q = models.UsageQuota(project_id=project_id, max_runs_per_day=0, runs_today=0)
        db.add(q)
        db.commit()
        db.refresh(q)
    return q


def set_quota(db: Session, project_id: int, max_runs_per_day: int | None) -> models.UsageQuota:
    q = get_quota(db, project_id)
    if max_runs_per_day is not None and max_runs_per_day >= 0:
        q.max_runs_per_day = max_runs_per_day
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def _reset_window_if_needed(q: models.UsageQuota):
    from datetime import timedelta

    now = datetime.utcnow()
    if now - q.window_start >= timedelta(days=1):
        q.window_start = now
        q.runs_today = 0


def try_consume_run(db: Session, project_id: int) -> tuple[bool, int]:
    q = get_quota(db, project_id)
    _reset_window_if_needed(q)
    if q.max_runs_per_day and q.runs_today >= q.max_runs_per_day:
        remaining = 0
        return False, remaining
    q.runs_today += 1
    db.add(q)
    db.commit()
    remaining = (q.max_runs_per_day - q.runs_today) if q.max_runs_per_day else -1
    return True, remaining


def scheduler_tick(db: Session) -> int:
    """Process scheduler queue with comprehensive activity tracking."""
    activity_id = tracker.create_activity(
        type=ActivityType.SCHEDULER_TICK,
        name="Scheduler Tick",
        what_it_will_do="Process queued work items and start eligible runs"
    )
    
    tracker.start_activity(activity_id, "Querying for eligible scheduled tasks")
    
    processed = 0
    # start runs for queued items due now with deps satisfied, highest priority first
    now = datetime.utcnow()
    queued = (
        db.query(models.ScheduledTask)
        .filter(models.ScheduledTask.status == "queued")
        .filter(models.ScheduledTask.scheduled_for <= now)
        .order_by(models.ScheduledTask.priority.desc(), models.ScheduledTask.id.asc())
        .all()
    )
    for st in queued:
        # Track each task processing decision
        task_activity = tracker.create_activity(
            type=ActivityType.DECISION,
            name=f"Process task #{st.id}",
            what_it_will_do=f"Evaluate and potentially start work item #{st.work_item_id}",
            parent_id=activity_id
        )
        tracker.start_activity(task_activity, "Checking dependencies and approvals")
        
        dep_ok = True
        if st.depends_on_work_item_id:
            dep_wi = db.get(models.WorkItem, st.depends_on_work_item_id)
            dep_ok = dep_wi is not None and dep_wi.state == "Done"
        if not dep_ok:
            tracker.complete_activity(task_activity, "Skipped: dependencies not satisfied")
            continue

        wi = db.get(models.WorkItem, st.work_item_id)
        if not wi:
            st.status = "done"
            db.add(st)
            tracker.complete_activity(task_activity, "Work item not found, marking task as done")
            continue
        if settings.require_approval:
            latest = get_latest_approval(db, wi)
            if not latest or latest.status != "approved":
                tracker.complete_activity(task_activity, "Skipped: approval required but not found")
                continue
        # enforce per-project quota
        ok, _remaining = try_consume_run(db, wi.project_id)
        if not ok:
            # skip for now; leave queued to retry next tick
            tracker.complete_activity(task_activity, "Skipped: quota exceeded")
            continue
        # start run
        run = start_run(db, wi)
        st.status = "running"
        db.add(st)
        processed += 1
        
        tracker.complete_activity(
            task_activity,
            f"Started run #{run.id} for work item '{wi.title}'",
            result={"run_id": run.id, "work_item_id": wi.id}
        )
    
    db.commit()
    
    tracker.complete_activity(
        activity_id,
        f"Processed {processed} scheduled tasks",
        result={"processed_count": processed, "queued_count": len(queued)}
    )
    
    return processed


def set_tool_recipe(db: Session, wi: models.WorkItem, yaml_text: str) -> models.ToolRecipe:
    # Validate YAML per simple schema: tools: [ {name, version, checksum?, env? {}, network?: bool} ]
    status = "valid"
    error = ""
    try:
        data = yaml.safe_load(yaml_text) if yaml_text else None
        if not isinstance(data, dict):
            raise ValueError("recipe must be a mapping")
        tools = data.get("tools")
        if not isinstance(tools, list) or not tools:
            raise ValueError("tools must be a non-empty list")
        for t in tools:
            if not isinstance(t, dict):
                raise ValueError("tool entries must be mappings")
            if not t.get("name"):
                raise ValueError("tool.name is required")
            if not t.get("version"):
                raise ValueError("tool.version is required")
            env = t.get("env")
            if env is not None and not isinstance(env, dict):
                raise ValueError("tool.env must be a mapping")
            if "network" in t and not isinstance(t["network"], bool):
                raise ValueError("tool.network must be boolean")
        steps = data.get("steps")
        if steps is not None:
            if not isinstance(steps, list) or not steps:
                raise ValueError("steps must be a non-empty list")
            for s in steps:
                if isinstance(s, str):
                    if not s.strip():
                        raise ValueError("step string must be non-empty")
                elif isinstance(s, dict):
                    if not isinstance(s.get("run"), str) or not s.get("run").strip():
                        raise ValueError("step.run must be a non-empty string")
                    if "env" in s and not isinstance(s["env"], dict):
                        raise ValueError("step.env must be a mapping if provided")
                    if "timeout" in s and not (isinstance(s["timeout"], int) and s["timeout"] > 0):
                        raise ValueError("step.timeout must be positive integer seconds")
                    if "cwd" in s and not isinstance(s["cwd"], str):
                        raise ValueError("step.cwd must be a string if provided")
                else:
                    raise ValueError("steps entries must be strings or mappings")
    except Exception as e:
        status = "invalid"
        error = str(e)

    tr = (
        db.query(models.ToolRecipe)
        .filter_by(work_item_id=wi.id)
        .one_or_none()
    )
    if tr:
        tr.yaml = yaml_text
        tr.status = status
        tr.error = error
    else:
        tr = models.ToolRecipe(work_item_id=wi.id, yaml=yaml_text, status=status, error=error)
        db.add(tr)
    db.commit()
    db.refresh(tr)
    return tr


def get_tool_recipe(db: Session, wi: models.WorkItem) -> models.ToolRecipe | None:
    return db.query(models.ToolRecipe).filter_by(work_item_id=wi.id).one_or_none()


def claim_run(db: Session, run: models.Run, agent_id: str, ttl_seconds: int = 300) -> bool:
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    expired = False
    if run.heartbeat_at:
        expired = (now - run.heartbeat_at) > timedelta(seconds=ttl_seconds)
    if run.status != "running":
        return False
    if run.claimed_by and not expired and run.claimed_by != agent_id:
        return False
    run.claimed_by = agent_id
    if not run.claimed_at:
        run.claimed_at = now
    run.heartbeat_at = now
    db.add(run)
    db.commit()
    db.refresh(run)
    return True


def heartbeat_run(db: Session, run: models.Run, agent_id: str) -> bool:
    from datetime import datetime

    if run.claimed_by != agent_id:
        return False
    run.heartbeat_at = datetime.utcnow()
    db.add(run)
    db.commit()
    db.refresh(run)
    return True


def create_info_request(db: Session, run: models.Run, prompt: str, required_keys: list[str]) -> models.InfoRequest:
    ir = models.InfoRequest(
        run=run,
        status="pending",
        prompt=prompt,
        required_keys=json.dumps(required_keys),
        responses="",
    )
    db.add(ir)
    db.commit()
    db.refresh(ir)
    return ir


def list_info_requests(db: Session, run: models.Run) -> list[models.InfoRequest]:
    return db.query(models.InfoRequest).filter_by(run_id=run.id).order_by(models.InfoRequest.id.asc()).all()


def get_info_request(db: Session, req_id: int) -> models.InfoRequest | None:
    return db.get(models.InfoRequest, req_id)


def respond_info_request(db: Session, ir: models.InfoRequest, values: dict) -> models.InfoRequest:
    # Optionally encrypt stored responses at rest
    text = json.dumps(values)
    enc, ok = encrypt_text(text)
    ir.responses = enc if ok else text
    ir.status = "resolved"
    ir.resolved_at = datetime.utcnow()
    db.add(ir)
    db.commit()
    db.refresh(ir)
    return ir


def add_run_step(
    db: Session,
    run: models.Run,
    name: str,
    status: str = "succeeded",
    duration_seconds: float | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> models.RunStep:
    # compute next index
    idx = (
        db.query(models.RunStep)
        .filter_by(run_id=run.id)
        .count()
    )
    # infer duration if not provided but both times are present
    dur = duration_seconds
    if dur is None and started_at and finished_at:
        try:
            dur = (finished_at - started_at).total_seconds()
        except Exception:
            dur = None

    step = models.RunStep(
        run_id=run.id,
        idx=idx,
        name=name,
        status=status,
        duration_seconds=dur,
        started_at=started_at or datetime.utcnow(),
        finished_at=finished_at,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def list_run_steps(db: Session, run: models.Run) -> list[models.RunStep]:
    return (
        db.query(models.RunStep)
        .filter_by(run_id=run.id)
        .order_by(models.RunStep.idx.asc(), models.RunStep.id.asc())
        .all()
    )


def get_run_step(db: Session, step_id: int) -> models.RunStep | None:
    return db.get(models.RunStep, step_id)


def update_run_step(
    db: Session,
    step: models.RunStep,
    status: str | None = None,
    duration_seconds: float | None = None,
    finished_at: datetime | None = None,
) -> models.RunStep:
    if status is not None:
        step.status = status
    if duration_seconds is not None:
        step.duration_seconds = duration_seconds
    if finished_at is not None:
        step.finished_at = finished_at
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def add_run_artifact(
    db: Session,
    run: models.Run,
    name: str,
    media_type: str | None,
    kind: str | None,
    content_base64: str,
) -> models.RunArtifact:
    from base64 import b64decode

    size = 0
    try:
        size = len(b64decode(content_base64))
    except Exception:
        size = 0
    art = models.RunArtifact(
        run_id=run.id,
        name=name,
        media_type=media_type,
        kind=(kind or "file"),
        size_bytes=size,
        content_base64=content_base64,
    )
    db.add(art)
    db.commit()
    db.refresh(art)
    return art


def list_run_artifacts(db: Session, run: models.Run) -> list[models.RunArtifact]:
    return (
        db.query(models.RunArtifact)
        .filter_by(run_id=run.id)
        .order_by(models.RunArtifact.id.asc())
        .all()
    )


def get_run_artifact(db: Session, artifact_id: int) -> models.RunArtifact | None:
    return db.get(models.RunArtifact, artifact_id)


def add_run_summary(db: Session, run: models.Run, data: dict) -> models.RunSummary:
    title = None
    tags = None
    try:
        if isinstance(data, dict):
            title = data.get("title") if isinstance(data.get("title"), str) else None
            t = data.get("tags") or data.get("labels")
            if isinstance(t, list):
                tags = [x for x in t if isinstance(x, str)] or None
    except Exception:
        title = None
        tags = None
    row = models.RunSummary(run_id=run.id, title=title, tags=tags, data=data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_run_summaries(db: Session, run: models.Run) -> list[models.RunSummary]:
    return (
        db.query(models.RunSummary)
        .filter_by(run_id=run.id)
        .order_by(models.RunSummary.id.asc())
        .all()
    )


def get_run_summary(db: Session, summary_id: int) -> models.RunSummary | None:
    return db.get(models.RunSummary, summary_id)
