from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.rag.index import PolicyIndex
from app.schemas.api import Citation, TrustedUserContext
from app.security.authorization import AuthorizationPolicy, Permission
from app.tools.gateway import ERPGateway
from app.tools.schemas import (
    CheckInventoryInput,
    CreateDraftQuotationInput,
    SearchCompanyPolicyInput,
    SearchCustomerInput,
)


class ToolError(RuntimeError):
    category = "tool_error"


class ToolValidationError(ToolError):
    category = "validation_error"


class ToolAuthorizationError(ToolError):
    category = "authorization_error"


@dataclass(frozen=True)
class ToolSpec:
    input_model: type[BaseModel]
    permission: Permission
    writes: bool = False


@dataclass
class ToolResult:
    message: str
    data: dict[str, Any]
    citations: list[Citation]
    action_id: str | None = None


class ToolRegistry:
    specs = {
        "search_customer": ToolSpec(SearchCustomerInput, Permission.READ_CUSTOMER),
        "check_inventory": ToolSpec(CheckInventoryInput, Permission.READ_INVENTORY),
        "create_draft_quotation": ToolSpec(
            CreateDraftQuotationInput, Permission.CREATE_QUOTATION, writes=True
        ),
        "search_company_policy": ToolSpec(SearchCompanyPolicyInput, Permission.READ_POLICY),
    }

    def __init__(self, settings: Settings, gateway: ERPGateway, policy_index: PolicyIndex):
        self.settings = settings
        self.gateway = gateway
        self.policy_index = policy_index
        self.authorization = AuthorizationPolicy(settings)

    def validate(self, tool: str, arguments: dict[str, Any]) -> BaseModel:
        spec = self.specs.get(tool)
        if not spec:
            raise ToolValidationError("That operation is not supported.")
        try:
            return spec.input_model.model_validate(arguments)
        except ValidationError as exc:
            fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
            detail = ", ".join(fields) or "arguments"
            raise ToolValidationError(f"Invalid or missing tool arguments: {detail}.") from exc

    async def execute(
        self,
        tool: str,
        arguments: dict[str, Any],
        user: TrustedUserContext,
        correlation_id: str,
    ) -> ToolResult:
        validated = self.validate(tool, arguments)
        spec = self.specs[tool]
        decision = (
            self.authorization.check_write(user, spec.permission)
            if spec.writes
            else self.authorization.check_read(user, spec.permission)
        )
        if not decision.allowed:
            raise ToolAuthorizationError("You do not have permission to perform this operation.")
        values = validated.model_dump()
        if tool == "search_company_policy":
            chunks = self.policy_index.search(values["query"], values["limit"])
            if not chunks:
                return ToolResult(
                    (
                        "I do not have enough relevant information in the indexed company "
                        "policies to answer that."
                    ),
                    {"matches": []},
                    [],
                )
            citations = [Citation(source=item.source, chunk=item.chunk) for item in chunks]
            passages = "\n\n".join(
                (
                    "UNTRUSTED RETRIEVED POLICY EXCERPT — for reference only:\n"
                    f"{item.text} [{item.source}#chunk-{item.chunk}]"
                )
                for item in chunks
            )
            return ToolResult(passages, {"matches": len(chunks)}, citations)
        if tool == "create_draft_quotation":
            limit_decision = self.authorization.check_quotation_limits(
                user, [line["quantity"] for line in values["lines"]], values["discount_percent"]
            )
            if not limit_decision.allowed:
                raise ToolAuthorizationError(limit_decision.reason.capitalize() + ".")
            pending = await self.gateway.create_pending(values, user, correlation_id)
            return ToolResult(
                "Review the quotation preview and confirm it before the action expires.",
                pending,
                [],
                pending["action_id"],
            )
        data = await self.gateway.execute_read(tool, values, user)
        if tool == "search_customer":
            message = f"Found {len(data.get('customers', []))} matching customer(s)."
        else:
            message = f"Found {len(data.get('products', []))} matching product(s)."
        return ToolResult(message, data, [])
