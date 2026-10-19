"""Pydantic contracts shared by the HTTP API and internal modules."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TaskStatus = Literal[
    "queued",
    "planning",
    "running",
    "awaiting_approval",
    "paused",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
]

AutonomyLevel = Literal[0, 1, 2, 3, 4]
Risk = Literal["low", "medium", "high", "critical"]


class TaskCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=8000)
    autonomy_level: AutonomyLevel = 1
    business_id: str | None = None
    mode: Literal["demo", "test", "production"] = "demo"
    idempotency_key: str | None = Field(default=None, max_length=128)
    auto_start: bool = True


class ChatMessage(BaseModel):
    conversation_id: str = Field(default="default", max_length=64)
    message: str = Field(min_length=1, max_length=8000)
    speak: bool = False


class PermissionUpdate(BaseModel):
    scope: str
    granted: bool
    config: dict[str, Any] = Field(default_factory=dict)
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 365)


class ApprovalDecision(BaseModel):
    approve: bool
    pin: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=500)


class PinSetup(BaseModel):
    pin: str = Field(min_length=6, max_length=32)
    current_pin: str | None = None

    @field_validator("pin")
    @classmethod
    def pin_numeric(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("PIN deve conter apenas digitos")
        return value


class CaktoCredentials(BaseModel):
    client_id: str = Field(min_length=4, max_length=200)
    client_secret: str = Field(min_length=8, max_length=400)
    environment: Literal["production", "demo"] = "production"


class CaktoProductDraft(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str = Field(min_length=10, max_length=4000)
    price: float = Field(gt=0, le=1_000_000)
    type: Literal["unique", "subscription"] = "unique"
    sales_page: str = Field(min_length=8, max_length=500)
    business_id: str | None = None
    confirm_create: bool = False
    approval_id: str | None = None


class AdsDraft(BaseModel):
    business_id: str | None = None
    provider: Literal["meta", "google", "tiktok"] = "meta"
    objective: str = Field(min_length=5, max_length=2000)
    daily_budget: float = Field(ge=0, le=100_000)
    monthly_limit: float = Field(ge=0, le=1_000_000)
    audience: str | None = None
    product_id: str | None = None
    publish: bool = False
    approval_id: str | None = None


class CampaignMetric(BaseModel):
    campaign_id: str
    spend: float = 0
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    revenue: float = 0


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    phone: str | None = None
    source: str | None = None
    consent: bool = False
    notes: str | None = None
    business_id: str | None = None


class MemoryCreate(BaseModel):
    kind: Literal["session", "project", "operational", "preference", "commercial", "technical"] = "preference"
    content: str = Field(min_length=2, max_length=8000)
    key: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = "user"


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    objective: str = Field(min_length=5, max_length=4000)
    interval_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    cron: str | None = Field(default=None, max_length=120)
    autonomy_level: AutonomyLevel = 1


class BuildRequest(BaseModel):
    kind: Literal["web-app", "inventory-system", "godot-2d-racer"] = "web-app"
    name: str = Field(min_length=2, max_length=80)
    objective: str = Field(min_length=5, max_length=4000)
    run_tests: bool = True


class WebhookEventIn(BaseModel):
    provider: str = "cakto"
    event: str
    data: dict[str, Any]
    dedupe_key: str | None = None
