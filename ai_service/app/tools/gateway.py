from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.schemas.api import TrustedUserContext


class ERPError(RuntimeError):
    pass


class ERPGateway(Protocol):
    async def execute_read(
        self, tool: str, arguments: dict[str, Any], user: TrustedUserContext
    ) -> dict[str, Any]: ...
    async def create_pending(
        self, arguments: dict[str, Any], user: TrustedUserContext, correlation_id: str
    ) -> dict[str, Any]: ...
    async def confirm(
        self, action_id: str, user: TrustedUserContext, correlation_id: str
    ) -> dict[str, Any]: ...
    async def record_audit(self, payload: dict[str, Any]) -> None: ...


class OdooGateway:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"X-Odoo-Service-Key": self.settings.odoo_service_key.get_secret_value()}
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.post(
                    f"{self.settings.odoo_base_url}{path}",
                    json={"jsonrpc": "2.0", "params": payload},
                    headers=headers,
                )
            response.raise_for_status()
            body = response.json()
            if "result" in body:  # Odoo JSON-RPC route wrapper
                body = body["result"]
            if not body.get("ok", False):
                raise ERPError(body.get("error", "ERP operation failed"))
            return body["data"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ERPError("The ERP service is temporarily unavailable.") from exc

    async def execute_read(
        self, tool: str, arguments: dict[str, Any], user: TrustedUserContext
    ) -> dict[str, Any]:
        return await self._post(
            "/ai_copilot/internal/read",
            {"tool": tool, "arguments": arguments, "user_id": user.user_id},
        )

    async def create_pending(
        self, arguments: dict[str, Any], user: TrustedUserContext, correlation_id: str
    ) -> dict[str, Any]:
        return await self._post(
            "/ai_copilot/internal/pending",
            {"arguments": arguments, "user_id": user.user_id, "correlation_id": correlation_id},
        )

    async def confirm(
        self, action_id: str, user: TrustedUserContext, correlation_id: str
    ) -> dict[str, Any]:
        return await self._post(
            "/ai_copilot/internal/confirm",
            {"action_id": action_id, "user_id": user.user_id, "correlation_id": correlation_id},
        )

    async def record_audit(self, payload: dict[str, Any]) -> None:
        await self._post("/ai_copilot/internal/audit", payload)
