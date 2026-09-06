import time
import uuid
from typing import Any

import httpx

from app.core.logging import logger, redact
from app.schemas.api import ChatRequest, ChatResponse, ConfirmationRequest, ConfirmationResponse
from app.security.injection import detect_prompt_injection
from app.tools.gateway import ERPError, ERPGateway
from app.tools.registry import ToolAuthorizationError, ToolError, ToolRegistry


class CopilotService:
    def __init__(self, provider, registry: ToolRegistry, gateway: ERPGateway):
        self.provider = provider
        self.registry = registry
        self.gateway = gateway

    async def _audit(self, payload: dict[str, Any]) -> None:
        try:
            await self.gateway.record_audit(redact(payload))
        except (
            Exception
        ) as exc:  # audit transport must not leak details or replace the primary response
            logger.error("audit_delivery_failed", error_type=type(exc).__name__)

    async def chat(self, request: ChatRequest, correlation_id: str | None = None) -> ChatResponse:
        correlation_id = correlation_id or str(uuid.uuid4())
        started = time.perf_counter()
        audit: dict[str, Any] = {
            "correlation_id": correlation_id,
            "user_id": request.user.user_id,
            "original_request": request.message,
            "model_provider": self.provider.name,
            "authorization_result": "not_checked",
            "confirmation_state": "not_required",
        }
        try:
            injection = detect_prompt_injection(request.message)
            if injection:
                audit.update(authorization_result="blocked", error_category="prompt_injection")
                return ChatResponse(
                    correlation_id=correlation_id, status="rejected", message=injection
                )
            tool, arguments = await self.provider.select_tool(request.message)
            audit.update(selected_tool=tool or "unsupported", validated_arguments=arguments)
            if not tool:
                audit.update(
                    authorization_result="not_applicable", error_category="unsupported_request"
                )
                return ChatResponse(
                    correlation_id=correlation_id,
                    status="rejected",
                    message=(
                        "I can only search customers, check inventory, search company policy, "
                        "or prepare a draft quotation."
                    ),
                )
            result = await self.registry.execute(tool, arguments, request.user, correlation_id)
            status = "pending_confirmation" if result.action_id else "completed"
            audit.update(
                authorization_result="allowed",
                confirmation_state="pending" if result.action_id else "not_required",
                execution_result="preview_created" if result.action_id else "completed",
            )
            return ChatResponse(
                correlation_id=correlation_id,
                status=status,
                message=result.message,
                tool=tool,
                data=result.data,
                citations=result.citations,
                action_id=result.action_id,
                expires_at=result.data.get("expires_at"),
            )
        except ToolAuthorizationError as exc:
            audit.update(authorization_result="denied", error_category=exc.category)
            return ChatResponse(
                correlation_id=correlation_id,
                status="rejected",
                message=str(exc),
                tool=audit.get("selected_tool"),
            )
        except ToolError as exc:
            audit.update(authorization_result="not_applicable", error_category=exc.category)
            return ChatResponse(
                correlation_id=correlation_id,
                status="rejected",
                message=str(exc),
                tool=audit.get("selected_tool"),
            )
        except (httpx.HTTPError, ERPError, ValueError, KeyError):
            audit.update(error_category="provider_error", execution_result="failed")
            return ChatResponse(
                correlation_id=correlation_id,
                status="failed",
                message="The assistant service is temporarily unavailable. Please try again.",
            )
        finally:
            audit["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            logger.info("copilot_request", **redact(audit))
            await self._audit(audit)

    async def confirm(
        self, request: ConfirmationRequest, correlation_id: str | None = None
    ) -> ConfirmationResponse:
        correlation_id = correlation_id or str(uuid.uuid4())
        started = time.perf_counter()
        audit = {
            "correlation_id": correlation_id,
            "user_id": request.user.user_id,
            "selected_tool": "create_draft_quotation",
            "validated_arguments": {"action_id": request.action_id},
            "model_provider": "none",
            "confirmation_state": "confirmed",
        }
        try:
            result = await self.gateway.confirm(request.action_id, request.user, correlation_id)
            audit.update(authorization_result="allowed", execution_result="executed")
            return ConfirmationResponse(
                correlation_id=correlation_id,
                status="executed",
                message="Draft quotation created successfully.",
                result=result,
            )
        except Exception:
            audit.update(
                authorization_result="denied",
                execution_result="failed",
                error_category="confirmation_error",
            )
            return ConfirmationResponse(
                correlation_id=correlation_id,
                status="rejected",
                message="This action is invalid, expired, already used, or not owned by you.",
            )
        finally:
            audit["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            logger.info("copilot_confirmation", **redact(audit))
            await self._audit(audit)
