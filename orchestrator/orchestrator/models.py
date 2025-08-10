from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from .db import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    visions = relationship("Vision", back_populates="project", cascade="all, delete-orphan")


class Vision(Base):
    __tablename__ = "visions"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)

    project = relationship("Project", back_populates="visions")
    requirements = relationship(
        "RequirementsDraft", back_populates="vision", cascade="all, delete-orphan", uselist=False
    )


class RequirementsDraft(Base):
    __tablename__ = "requirements_drafts"

    id = Column(Integer, primary_key=True, index=True)
    vision_id = Column(Integer, ForeignKey("visions.id", ondelete="CASCADE"), nullable=False)
    draft = Column(Text, nullable=False)
    status = Column(String(32), default="proposed")  # proposed|approved

    vision = relationship("Vision", back_populates="requirements")


class WorkItem(Base):
    __tablename__ = "work_items"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    state = Column(String(32), default="Proposed")  # Proposed → Approved → In Progress → Review → Done
    # Optional per-item retry/backoff overrides
    max_retries = Column(Integer, nullable=True)
    backoff_base_seconds = Column(Integer, nullable=True)
    backoff_jitter_seconds = Column(Integer, nullable=True)

    project = relationship("Project")
    runs = relationship("Run", back_populates="work_item", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    work_item_id = Column(Integer, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), default="pending")  # pending|running|succeeded|failed
    logs = Column(Text, default="")
    trace_id = Column(String(64), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    claimed_by = Column(String(128), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)

    work_item = relationship("WorkItem", back_populates="runs")


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, index=True)
    work_item_id = Column(Integer, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), default="pending")  # pending|approved|denied
    reason = Column(Text, default="")

    work_item = relationship("WorkItem")


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id = Column(Integer, primary_key=True, index=True)
    work_item_id = Column(Integer, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), default="queued")  # queued|running|done
    priority = Column(Integer, default=0)
    depends_on_work_item_id = Column(Integer, ForeignKey("work_items.id"), nullable=True)

    work_item = relationship("WorkItem", foreign_keys=[work_item_id])
    scheduled_for = Column(DateTime, default=datetime.utcnow)


class ToolRecipe(Base):
    __tablename__ = "tool_recipes"

    id = Column(Integer, primary_key=True, index=True)
    work_item_id = Column(Integer, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    yaml = Column(Text, nullable=False)
    status = Column(String(32), default="invalid")  # valid|invalid
    error = Column(Text, default="")

    work_item = relationship("WorkItem")


class InfoRequest(Base):
    __tablename__ = "info_requests"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), default="pending")  # pending|resolved|cancelled
    prompt = Column(Text, nullable=False)
    required_keys = Column(Text, default="")  # JSON-encoded list
    responses = Column(Text, default="")  # JSON-encoded mapping
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    run = relationship("Run")


class UsageQuota(Base):
    __tablename__ = "usage_quotas"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    max_runs_per_day = Column(Integer, default=0)  # 0 means unlimited
    runs_today = Column(Integer, default=0)
    window_start = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project")
