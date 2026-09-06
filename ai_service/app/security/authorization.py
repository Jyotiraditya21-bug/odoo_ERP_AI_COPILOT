from dataclasses import dataclass
from enum import StrEnum

from app.core.config import Settings
from app.schemas.api import TrustedUserContext


class Permission(StrEnum):
    READ_CUSTOMER = "read_customer"
    READ_INVENTORY = "read_inventory"
    READ_POLICY = "read_policy"
    CREATE_QUOTATION = "create_quotation"


READ_GROUPS = {
    Permission.READ_CUSTOMER: {"sales_team.group_sale_salesman", "sales_team.group_sale_manager"},
    Permission.READ_INVENTORY: {"stock.group_stock_user", "stock.group_stock_manager"},
    Permission.READ_POLICY: {"base.group_user"},
}
WRITE_GROUPS = {
    Permission.CREATE_QUOTATION: {"sales_team.group_sale_salesman", "sales_team.group_sale_manager"}
}


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str


class AuthorizationPolicy:
    def __init__(self, settings: Settings):
        self.settings = settings

    def check_read(self, user: TrustedUserContext, permission: Permission) -> AuthorizationDecision:
        required = READ_GROUPS.get(permission, set())
        allowed = bool(user.groups & required)
        return AuthorizationDecision(
            allowed, "read permission granted" if allowed else "read permission denied"
        )

    def check_write(
        self, user: TrustedUserContext, permission: Permission
    ) -> AuthorizationDecision:
        required = WRITE_GROUPS.get(permission, set())
        allowed = bool(user.groups & required)
        return AuthorizationDecision(
            allowed, "write permission granted" if allowed else "write permission denied"
        )

    def check_quotation_limits(
        self, user: TrustedUserContext, quantities: list[float], discount: float
    ) -> AuthorizationDecision:
        if any(quantity > self.settings.max_quotation_quantity for quantity in quantities):
            return AuthorizationDecision(False, "quantity exceeds the configured maximum")
        is_manager = "sales_team.group_sale_manager" in user.groups
        maximum = (
            self.settings.max_manager_discount
            if is_manager
            else self.settings.max_salesperson_discount
        )
        if discount > maximum:
            return AuthorizationDecision(False, f"discount exceeds the role limit of {maximum:g}%")
        return AuthorizationDecision(True, "quotation limits satisfied")
