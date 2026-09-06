from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from app.core.config import Settings
from app.llm.providers import RuleBasedProvider
from app.rag.index import PolicyIndex
from app.schemas.api import TrustedUserContext
from app.service import CopilotService
from app.tools.gateway import ERPError
from app.tools.registry import ToolRegistry


class FakeGateway:
    def __init__(self):
        self.pending: dict[str, dict[str, Any]] = {}
        self.audits: list[dict[str, Any]] = []
        self.fail_reads = False

    async def execute_read(self, tool, arguments, user):
        if self.fail_reads:
            raise ERPError("private backend detail")
        if tool == "search_customer":
            rows = [{"id": 1, "name": "ABC Industries", "city": "Pune", "country": "India"}]
            if "unknown" in arguments["name"].lower():
                rows = []
            return {"customers": rows}
        products = [
            {
                "id": 10,
                "name": "Product A",
                "available_quantity": 25,
                "uom": "Units",
                "low_stock": False,
            },
            {
                "id": 11,
                "name": "Low Stock Widget",
                "available_quantity": 2,
                "uom": "Units",
                "low_stock": True,
            },
        ]
        if arguments.get("low_stock_only"):
            products = [item for item in products if item["low_stock"]]
        elif arguments.get("product_name"):
            query = arguments["product_name"].lower()
            products = [item for item in products if query in item["name"].lower()]
        return {"products": products, "low_stock_threshold": 5}

    async def create_pending(self, arguments, user, correlation_id):
        token = "secure-action-token-0000000001"
        self.pending[token] = {"owner": user.user_id, "used": False, "arguments": arguments}
        return {
            "action_id": token,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "preview": {
                "customer": arguments["customer_name"],
                "lines": arguments["lines"],
                "state": "draft",
            },
        }

    async def confirm(self, action_id, user, correlation_id):
        action = self.pending.get(action_id)
        if not action or action["owner"] != user.user_id or action["used"]:
            raise ERPError("invalid action")
        action["used"] = True
        return {"quotation_id": 42, "quotation_name": "S00042", "state": "draft"}

    async def record_audit(self, payload):
        self.audits.append(payload)


@pytest.fixture
def settings(tmp_path: Path):
    return Settings(
        llm_provider="rule_based",
        policy_dir=Path(__file__).parents[2] / "policies",
        chroma_path=tmp_path / "chroma",
        policy_relevance_threshold=0.1,
        max_quotation_quantity=100,
        max_salesperson_discount=15,
        max_manager_discount=30,
    )


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def policy_index(settings):
    index = PolicyIndex(
        settings.policy_dir, settings.chroma_path, settings.policy_relevance_threshold
    )
    index.build()
    return index


@pytest.fixture
def service(settings, gateway, policy_index):
    registry = ToolRegistry(settings, gateway, policy_index)
    return CopilotService(RuleBasedProvider(), registry, gateway)


@pytest.fixture
def salesperson():
    return TrustedUserContext(
        user_id=7,
        login="sales.demo",
        display_name="Demo Salesperson",
        groups={"base.group_user", "sales_team.group_sale_salesman", "stock.group_stock_user"},
    )


@pytest.fixture
def employee():
    return TrustedUserContext(
        user_id=8, login="employee.demo", display_name="Demo Employee", groups={"base.group_user"}
    )
