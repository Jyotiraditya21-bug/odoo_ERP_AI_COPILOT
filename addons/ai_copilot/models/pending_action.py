import hashlib
import json
import os
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class AICopilotPendingAction(models.Model):
    _name = "ai.copilot.pending.action"
    _description = "AI Copilot Pending Action"
    _order = "create_date desc"

    name = fields.Char(default="Draft quotation", required=True, readonly=True)
    user_id = fields.Many2one("res.users", required=True, index=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    action_token_hash = fields.Char(required=True, index=True, readonly=True)
    action_type = fields.Selection(
        [("create_draft_quotation", "Create draft quotation")], required=True, readonly=True
    )
    arguments_json = fields.Text(required=True, readonly=True)
    preview = fields.Text(required=True, readonly=True)
    expires_at = fields.Datetime(required=True, index=True, readonly=True)
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
        index=True,
        readonly=True,
    )
    sale_order_id = fields.Many2one("sale.order", readonly=True)
    error_message = fields.Char(readonly=True)

    def write(self, values):
        if not self.env.su and not self.env.context.get("ai_copilot_internal"):
            raise AccessError(_("Pending actions can only be changed through copilot actions."))
        return super().write(values)

    @api.model
    def create_preview(self, values, user, correlation_id, ttl_seconds):
        if not (
            user.has_group("sales_team.group_sale_salesman")
            or user.has_group("sales_team.group_sale_manager")
        ):
            raise AccessError(_("User is not allowed to create quotations."))
        maximum_quantity = float(os.environ.get("MAX_QUOTATION_QUANTITY", "100"))
        is_manager = user.has_group("sales_team.group_sale_manager")
        maximum_discount = float(
            os.environ.get(
                "MAX_MANAGER_DISCOUNT" if is_manager else "MAX_SALESPERSON_DISCOUNT",
                "30" if is_manager else "15",
            )
        )
        if float(values.get("discount_percent", 0)) > maximum_discount:
            raise ValidationError(_("Discount exceeds the configured role limit."))
        if any(float(line["quantity"]) > maximum_quantity for line in values["lines"]):
            raise ValidationError(_("Quantity exceeds the configured maximum."))
        action_env = self.env(user=user.id)
        partner = action_env["res.partner"].search(
            [("name", "ilike", values["customer_name"]), ("customer_rank", ">", 0)], limit=2
        )
        if len(partner) != 1:
            raise ValidationError(_("Customer must resolve to exactly one accessible record."))
        preview_lines = []
        stored_lines = []
        for line in values["lines"]:
            product = action_env["product.product"].search(
                [("name", "ilike", line["product_name"]), ("sale_ok", "=", True)], limit=2
            )
            if len(product) != 1:
                raise ValidationError(
                    _("Each product must resolve to exactly one accessible record.")
                )
            quantity = float(line["quantity"])
            stored_lines.append({"product_id": product.id, "quantity": quantity})
            preview_lines.append(
                {
                    "product": product.display_name,
                    "quantity": quantity,
                    "unit_price": product.lst_price,
                    "discount_percent": float(values.get("discount_percent", 0)),
                }
            )
        token = secrets.token_urlsafe(32)
        stored = {
            "partner_id": partner.id,
            "lines": stored_lines,
            "discount_percent": float(values.get("discount_percent", 0)),
        }
        preview = {"customer": partner.display_name, "lines": preview_lines, "state": "draft"}
        record = self.sudo().create(
            {
                "user_id": user.id,
                "correlation_id": correlation_id,
                "action_token_hash": hashlib.sha256(token.encode()).hexdigest(),
                "action_type": "create_draft_quotation",
                "arguments_json": json.dumps(stored, sort_keys=True),
                "preview": json.dumps(preview, indent=2),
                "expires_at": fields.Datetime.now() + timedelta(seconds=ttl_seconds),
            }
        )
        return record, token, preview

    @api.model
    def consume(self, token, user):
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        action = self.sudo().search(
            [("action_token_hash", "=", token_hash), ("user_id", "=", user.id)], limit=1
        )
        if not action or action.status != "pending" or action.expires_at < fields.Datetime.now():
            raise AccessError(
                _("Action is invalid, expired, already used, or belongs to another user.")
            )
        if not (
            user.has_group("sales_team.group_sale_salesman")
            or user.has_group("sales_team.group_sale_manager")
        ):
            raise AccessError(_("User is no longer allowed to create quotations."))
        values = json.loads(action.arguments_json)
        maximum_quantity = float(os.environ.get("MAX_QUOTATION_QUANTITY", "100"))
        is_manager = user.has_group("sales_team.group_sale_manager")
        maximum_discount = float(
            os.environ.get(
                "MAX_MANAGER_DISCOUNT" if is_manager else "MAX_SALESPERSON_DISCOUNT",
                "30" if is_manager else "15",
            )
        )
        if values["discount_percent"] > maximum_discount or any(
            line["quantity"] > maximum_quantity for line in values["lines"]
        ):
            raise AccessError(_("Action no longer satisfies quotation limits."))
        # Consume before executing. A retry cannot create a second quotation.
        action.write({"status": "confirmed"})
        try:
            user_env = self.env(user=user.id)
            with self.env.cr.savepoint():
                order = user_env["sale.order"].create(
                    {"partner_id": values["partner_id"], "state": "draft"}
                )
                for line in values["lines"]:
                    user_env["sale.order.line"].create(
                        {
                            "order_id": order.id,
                            "product_id": line["product_id"],
                            "product_uom_qty": line["quantity"],
                            "discount": values["discount_percent"],
                        }
                    )
                if order.state != "draft":
                    raise UserError(_("Copilot-created quotations must remain in draft state."))
            action.write({"status": "executed", "sale_order_id": order.id})
            return order
        except Exception as exc:
            action.write({"status": "failed", "error_message": _("Quotation creation failed.")})
            raise UserError(_("Quotation creation failed.")) from exc

    def action_cancel(self):
        for action in self:
            if action.user_id != self.env.user and not self.env.user.has_group(
                "sales_team.group_sale_manager"
            ):
                raise AccessError(_("You may only cancel your own action."))
            if action.status != "pending":
                raise UserError(_("Only pending actions can be cancelled."))
            action.sudo().with_context(ai_copilot_internal=True).write({"status": "rejected"})
        return True
