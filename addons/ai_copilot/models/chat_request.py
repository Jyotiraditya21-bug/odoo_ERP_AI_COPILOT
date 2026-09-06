import json
import os
import uuid

import requests
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

SAFE_GROUPS = (
    "base.group_user",
    "sales_team.group_sale_salesman",
    "sales_team.group_sale_manager",
    "stock.group_stock_user",
    "stock.group_stock_manager",
)


class AICopilotChatRequest(models.Model):
    _name = "ai.copilot.chat.request"
    _description = "AI Copilot Request"
    _order = "create_date desc"

    user_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, required=True, readonly=True
    )
    request_text = fields.Text(required=True)
    response_text = fields.Text(readonly=True)
    citations = fields.Text(readonly=True)
    tool_name = fields.Char(readonly=True)
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("confirmed", "Confirmed"),
            ("executed", "Executed"),
            ("rejected", "Rejected"),
            ("failed", "Failed"),
        ],
        default="pending",
        required=True,
        readonly=True,
    )
    correlation_id = fields.Char(readonly=True, index=True)
    pending_action_id = fields.Many2one("ai.copilot.pending.action", readonly=True)
    action_token = fields.Char(readonly=True, copy=False, groups="base.group_user")

    @api.model_create_multi
    def create(self, values_list):
        sanitized = []
        for values in values_list:
            sanitized.append(
                {"request_text": values.get("request_text"), "user_id": self.env.user.id}
            )
        return super().create(sanitized)

    def write(self, values):
        if not self.env.context.get("ai_copilot_internal"):
            if set(values) - {"request_text"} or any(record.response_text for record in self):
                raise AccessError(_("Copilot result fields cannot be changed directly."))
        return super().write(values)

    def _trusted_context(self):
        user = self.env.user
        groups = [xmlid for xmlid in SAFE_GROUPS if user.has_group(xmlid)]
        return {
            "user_id": user.id,
            "login": user.login,
            "display_name": user.display_name,
            "groups": groups,
        }

    def _call_service(self, endpoint, payload, correlation_id):
        base_url = os.environ.get("AI_SERVICE_URL", "http://ai-service:8000").rstrip("/")
        service_key = os.environ.get("ODOO_SERVICE_KEY")
        if not service_key:
            raise UserError(_("The copilot service key is not configured."))
        try:
            response = requests.post(
                f"{base_url}{endpoint}",
                json=payload,
                headers={"X-Odoo-Service-Key": service_key, "X-Correlation-ID": correlation_id},
                timeout=float(os.environ.get("AI_REQUEST_TIMEOUT_SECONDS", "30")),
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise UserError(_("The AI service is temporarily unavailable.")) from exc

    def action_submit(self):
        for chat in self:
            if chat.user_id != self.env.user:
                raise UserError(_("You may only submit your own request."))
            if chat.response_text:
                raise UserError(_("This request has already been submitted."))
            correlation_id = str(uuid.uuid4())
            result = chat._call_service(
                "/v1/chat",
                {"message": chat.request_text, "user": chat._trusted_context()},
                correlation_id,
            )
            pending = False
            if result.get("action_id"):
                import hashlib

                self.env.cr.commit()
                pending = (
                    self.env["ai.copilot.pending.action"]
                    .sudo()
                    .search(
                        [
                            (
                                "action_token_hash",
                                "=",
                                hashlib.sha256(result["action_id"].encode()).hexdigest(),
                            )
                        ],
                        limit=1,
                    )
                )
            status_map = {
                "completed": "executed",
                "pending_confirmation": "pending",
                "rejected": "rejected",
                "failed": "failed",
            }
            citations = "\n".join(
                f"{item['source']}#chunk-{item['chunk']}" for item in result.get("citations", [])
            )
            chat.with_context(ai_copilot_internal=True).write(
                {
                    "response_text": result.get("message", "") + (
                        "\n\n" + json.dumps(
                            {key: value for key, value in result["data"].items()
                             if key in {"customers", "products", "preview", "expires_at", "low_stock_threshold"}},
                            indent=2, ensure_ascii=False,
                        )
                        if result.get("data") else ""
                    ),
                    "citations": citations,
                    "tool_name": result.get("tool"),
                    "status": status_map[result["status"]],
                    "correlation_id": result["correlation_id"],
                    "pending_action_id": pending.id if pending else False,
                    "action_token": result.get("action_id") or False,
                }
            )
        return True

    def action_confirm(self):
        self.ensure_one()
        if not self.pending_action_id or not self.action_token or self.status != "pending":
            raise UserError(_("There is no pending action to confirm."))
        result = self._call_service(
            "/v1/confirm",
            {"action_id": self.action_token, "user": self._trusted_context()},
            str(uuid.uuid4()),
        )
        status = "executed" if result.get("status") == "executed" else "rejected"
        self.with_context(ai_copilot_internal=True).write(
            {
                "status": status,
                "response_text": result.get("message", ""),
                "action_token": False,
                "correlation_id": result.get("correlation_id", self.correlation_id),
            }
        )
        return True

    def action_cancel(self):
        self.ensure_one()
        if not self.pending_action_id or self.status != "pending":
            raise UserError(_("There is no pending action to cancel."))
        self.pending_action_id.action_cancel()
        self.with_context(ai_copilot_internal=True).write(
            {"status": "rejected", "response_text": _("Action cancelled."), "action_token": False}
        )
        return True
