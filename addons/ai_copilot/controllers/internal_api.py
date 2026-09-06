import json
import os
import secrets

from odoo import http
from odoo.http import request


class AICopilotInternalController(http.Controller):
    def _authorized(self):
        configured = os.environ.get("ODOO_SERVICE_KEY", "")
        supplied = request.httprequest.headers.get("X-Odoo-Service-Key", "")
        return bool(configured) and secrets.compare_digest(configured, supplied)

    def _error(self, message="Operation rejected"):
        return {"ok": False, "error": message}

    def _user(self, user_id):
        return request.env["res.users"].sudo().browse(int(user_id)).exists()

    @http.route("/ai_copilot/internal/read", type="json", auth="none", methods=["POST"], csrf=False)
    def read_tool(self, tool=None, arguments=None, user_id=None, **_kwargs):
        if not self._authorized():
            return self._error("Unauthorized service caller")
        user = self._user(user_id)
        if not user:
            return self._error()
        env = request.env(user=user.id)
        arguments = arguments or {}
        if tool == "search_customer":
            partners = env["res.partner"].search(
                [("name", "ilike", arguments["name"]), ("customer_rank", ">", 0)],
                limit=arguments.get("limit", 10),
            )
            return {
                "ok": True,
                "data": {
                    "customers": [
                        {
                            "id": item.id,
                            "name": item.display_name,
                            "city": item.city or "",
                            "country": item.country_id.name or "",
                        }
                        for item in partners
                    ]
                },
            }
        if tool == "check_inventory":
            domain = [("type", "=", "product")]
            if arguments.get("product_name"):
                domain.append(("name", "ilike", arguments["product_name"]))
            products = env["product.product"].search(domain, limit=arguments.get("limit", 20))
            threshold = float(os.environ.get("LOW_STOCK_THRESHOLD", "5"))
            rows = [
                {
                    "id": item.id,
                    "name": item.display_name,
                    "available_quantity": item.qty_available,
                    "uom": item.uom_id.name,
                    "low_stock": item.qty_available <= threshold,
                }
                for item in products
            ]
            if arguments.get("low_stock_only"):
                rows = [item for item in rows if item["low_stock"]]
            return {"ok": True, "data": {"products": rows, "low_stock_threshold": threshold}}
        return self._error("Unsupported operation")

    @http.route(
        "/ai_copilot/internal/pending", type="json", auth="none", methods=["POST"], csrf=False
    )
    def create_pending(self, arguments=None, user_id=None, correlation_id=None, **_kwargs):
        if not self._authorized():
            return self._error("Unauthorized service caller")
        user = self._user(user_id)
        if not user:
            return self._error()
        try:
            ttl = int(os.environ.get("PENDING_ACTION_TTL_SECONDS", "300"))
            action, token, preview = request.env["ai.copilot.pending.action"].create_preview(
                arguments, user, correlation_id, ttl
            )
            return {
                "ok": True,
                "data": {
                    "action_id": token,
                    "expires_at": action.expires_at.isoformat(),
                    "preview": preview,
                },
            }
        except Exception:
            return self._error("Quotation preview could not be created")

    @http.route(
        "/ai_copilot/internal/confirm", type="json", auth="none", methods=["POST"], csrf=False
    )
    def confirm(self, action_id=None, user_id=None, **_kwargs):
        if not self._authorized():
            return self._error("Unauthorized service caller")
        user = self._user(user_id)
        if not user:
            return self._error()
        try:
            order = request.env["ai.copilot.pending.action"].consume(action_id, user)
            return {
                "ok": True,
                "data": {
                    "quotation_id": order.id,
                    "quotation_name": order.name,
                    "state": order.state,
                },
            }
        except Exception:
            return self._error("Confirmation rejected")

    @http.route(
        "/ai_copilot/internal/audit", type="json", auth="none", methods=["POST"], csrf=False
    )
    def audit(self, **payload):
        if not self._authorized():
            return self._error("Unauthorized service caller")
        user = self._user(payload.get("user_id"))
        if not user:
            return self._error()
        safe = {
            key: payload.get(key)
            for key in (
                "correlation_id",
                "original_request",
                "selected_tool",
                "authorization_result",
                "confirmation_state",
                "execution_result",
                "error_category",
                "model_provider",
                "latency_ms",
            )
        }
        safe["user_id"] = user.id
        safe["validated_arguments"] = json.dumps(
            payload.get("validated_arguments", {}), sort_keys=True
        )
        request.env["ai.copilot.audit.log"].sudo().create(safe)
        return {"ok": True, "data": {"recorded": True}}
