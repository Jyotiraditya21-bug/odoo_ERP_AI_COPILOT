from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TrustedUserContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(gt=0)
    login: str = Field(min_length=1, max_length=254)
    display_name: str = Field(min_length=1, max_length=200)
    groups: set[str] = Field(default_factory=set)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    user: TrustedUserContext
    conversation_id: str | None = Field(default=None, max_length=100)


class Citation(BaseModel):
    source: str
    chunk: int


class ChatResponse(BaseModel):
    correlation_id: str
    status: Literal["completed", "pending_confirmation", "rejected", "failed"]
    message: str
    tool: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    action_id: str | None = None
    expires_at: datetime | None = None


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=20, max_length=200)
    user: TrustedUserContext


class ConfirmationResponse(BaseModel):
    correlation_id: str
    status: Literal["executed", "rejected", "failed"]
    message: str
    result: dict[str, Any] = Field(default_factory=dict)


class ErrorBody(BaseModel):
    correlation_id: str
    category: str
    message: str
