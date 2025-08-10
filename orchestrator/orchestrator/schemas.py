from pydantic import BaseModel
from typing import Optional


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None

    class Config:
        orm_mode = True


class VisionCreate(BaseModel):
    content: str


class VisionOut(BaseModel):
    id: int
    project_id: int
    content: str

    class Config:
        orm_mode = True


class RequirementsDraftOut(BaseModel):
    id: int
    vision_id: int
    draft: str
    status: str

    class Config:
        orm_mode = True


class WorkItemCreate(BaseModel):
    project_id: int
    title: str
    description: Optional[str] = None


class WorkItemOut(BaseModel):
    id: int
    project_id: int
    title: str
    description: Optional[str] = None
    state: str
    max_retries: Optional[int] = None
    backoff_base_seconds: Optional[int] = None
    backoff_jitter_seconds: Optional[int] = None

    class Config:
        orm_mode = True


class RunOut(BaseModel):
    id: int
    work_item_id: int
    status: str
    logs: str
    claimed_by: Optional[str] = None

    class Config:
        orm_mode = True


class ApprovalCreate(BaseModel):
    reason: Optional[str] = None


class ApprovalOut(BaseModel):
    id: int
    work_item_id: int
    status: str
    reason: str | None = None

    class Config:
        orm_mode = True


class EnqueueRequest(BaseModel):
    work_item_id: int
    depends_on_work_item_id: Optional[int] = None
    priority: Optional[int] = 0
    delay_seconds: Optional[int] = 0


class ScheduledTaskOut(BaseModel):
    id: int
    work_item_id: int
    status: str
    depends_on_work_item_id: Optional[int] = None
    priority: int
    scheduled_for: Optional[str] = None

    class Config:
        orm_mode = True


class ErrorOut(BaseModel):
    detail: str
    code: Optional[str] = None


class ToolRecipeCreate(BaseModel):
    yaml: str


class ToolRecipeOut(BaseModel):
    id: int
    work_item_id: int
    yaml: str
    status: str
    error: Optional[str] = None

    class Config:
        orm_mode = True


class LogAppend(BaseModel):
    line: str


class InfoRequestCreate(BaseModel):
    prompt: str
    required_keys: list[str]


class InfoRequestOut(BaseModel):
    id: int
    run_id: int
    status: str
    prompt: str
    required_keys: list[str]
    responses: Optional[dict] = None

    class Config:
        orm_mode = True


class InfoRequestRespond(BaseModel):
    values: dict


class ClaimIn(BaseModel):
    agent_id: str
    ttl_seconds: Optional[int] = 300


class ClaimOut(BaseModel):
    success: bool
    claimed_by: Optional[str] = None
    expires_in: Optional[int] = None


class HeartbeatIn(BaseModel):
    agent_id: str


class RequeueRunIn(BaseModel):
    delay_seconds: Optional[int] = None
    priority: Optional[int] = 0
    backoff: Optional[bool] = True


class WorkItemPolicyUpdate(BaseModel):
    max_retries: Optional[int] = None
    backoff_base_seconds: Optional[int] = None
    backoff_jitter_seconds: Optional[int] = None


class QuotaUpdate(BaseModel):
    max_runs_per_day: Optional[int] = None


class QuotaOut(BaseModel):
    project_id: int
    max_runs_per_day: int
    runs_today: int
    window_start: str
