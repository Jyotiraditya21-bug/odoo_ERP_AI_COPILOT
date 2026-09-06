from odoo import fields, models


class AICopilotAuditLog(models.Model):
    _name = "ai.copilot.audit.log"
    _description = "AI Copilot Audit Log"
    _order = "create_date desc"

    correlation_id = fields.Char(required=True, index=True, readonly=True)
    timestamp = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    user_id = fields.Many2one("res.users", required=True, index=True, readonly=True)
    original_request = fields.Text(readonly=True)
    selected_tool = fields.Char(readonly=True)
    validated_arguments = fields.Text(readonly=True)
    authorization_result = fields.Char(readonly=True)
    confirmation_state = fields.Char(readonly=True)
    execution_result = fields.Text(readonly=True)
    error_category = fields.Char(readonly=True)
    model_provider = fields.Char(readonly=True)
    latency_ms = fields.Float(readonly=True)

    def unlink(self):
        # Audit records are immutable from the UI and ORM.
        return False
