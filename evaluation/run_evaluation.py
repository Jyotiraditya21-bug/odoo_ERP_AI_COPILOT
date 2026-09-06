"""Run deterministic, offline evaluation against actual service code and write reports."""

import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai_service"))

from app.core.config import Settings  # noqa: E402
from app.llm.providers import RuleBasedProvider  # noqa: E402
from app.rag.index import PolicyIndex  # noqa: E402
from app.schemas.api import ChatRequest, TrustedUserContext  # noqa: E402
from app.service import CopilotService  # noqa: E402
from app.tools.registry import ToolRegistry  # noqa: E402


class EvaluationGateway:
    def __init__(self):
        self.pending = {}

    async def execute_read(self, tool, arguments, user):
        if tool == "search_customer":
            matches = (
                []
                if "unknown" in arguments["name"].lower()
                else [{"id": 1, "name": "ABC Industries"}]
            )
            return {"customers": matches}
        products = [
            {"id": 1, "name": "Product A", "available_quantity": 25, "low_stock": False},
            {"id": 2, "name": "Low Stock Widget", "available_quantity": 2, "low_stock": True},
        ]
        if arguments.get("low_stock_only"):
            products = [product for product in products if product["low_stock"]]
        return {"products": products, "low_stock_threshold": 5}

    async def create_pending(self, arguments, user, correlation_id):
        token = f"evaluation-action-{len(self.pending):020d}"
        self.pending[token] = arguments
        return {
            "action_id": token,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "preview": {"state": "draft", **arguments},
        }

    async def confirm(self, action_id, user, correlation_id):
        return {"quotation_id": 1, "state": "draft"}

    async def record_audit(self, payload):
        return None


def user(role):
    groups = {"base.group_user"}
    if role != "employee":
        groups |= {"sales_team.group_sale_salesman", "stock.group_stock_user"}
    return TrustedUserContext(
        user_id=1, login=f"{role}.demo", display_name=role.title(), groups=groups
    )


async def run():
    cases = json.loads((ROOT / "evaluation" / "cases.json").read_text())
    settings = Settings(
        llm_provider="rule_based",
        policy_dir=ROOT / "policies",
        chroma_path=ROOT / "data" / "evaluation-chroma",
        policy_relevance_threshold=0.1,
    )
    index = PolicyIndex(
        settings.policy_dir, settings.chroma_path, settings.policy_relevance_threshold
    )
    index.build()
    gateway = EvaluationGateway()
    service = CopilotService(RuleBasedProvider(), ToolRegistry(settings, gateway, index), gateway)
    rows = []
    for case in cases:
        started = time.perf_counter()
        response = await service.chat(
            ChatRequest(message=case["message"], user=user(case.get("user", "salesperson")))
        )
        latency = round((time.perf_counter() - started) * 1000, 2)
        tool_correct = response.tool == case["expected_tool"]
        status_correct = response.status == case["expected_status"]
        citation_correct = not case.get("citation") or any(
            c.source == case["citation"] for c in response.citations
        )
        auth_correct = not case.get("auth_block") or response.status == "rejected"
        unsafe_prevented = not case.get("unsafe") or response.status in {
            "pending_confirmation",
            "rejected",
        }
        rows.append(
            {
                "id": case["id"],
                "tool": response.tool,
                "status": response.status,
                "tool_correct": tool_correct,
                "validation_success": status_correct,
                "authorization_block_success": auth_correct,
                "unsafe_action_prevented": unsafe_prevented,
                "citation_correct": citation_correct,
                "latency_ms": latency,
            }
        )

    def rate(field, selected=None):
        sample = [
            row for row, case in zip(rows, cases, strict=True) if selected is None or selected(case)
        ]
        return (
            round(100 * sum(bool(row[field]) for row in sample) / len(sample), 1)
            if sample
            else 100.0
        )

    metrics = {
        "cases": len(rows),
        "tool_selection_accuracy_percent": rate("tool_correct"),
        "validation_success_percent": rate("validation_success"),
        "authorization_block_success_percent": rate(
            "authorization_block_success", lambda c: c.get("auth_block")
        ),
        "unsafe_action_prevention_percent": rate(
            "unsafe_action_prevented", lambda c: c.get("unsafe")
        ),
        "citation_correctness_percent": rate("citation_correct", lambda c: c.get("citation")),
        "median_latency_ms": round(statistics.median(row["latency_ms"] for row in rows), 2),
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "rule_based (offline deterministic evaluation)",
    }
    report = {"metrics": metrics, "cases": rows}
    (ROOT / "evaluation" / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    table_rows = []
    for row in rows:
        result = "pass" if row["validation_success"] else "fail"
        table_rows.append(
            f"| {row['id']} | {row['tool'] or 'none'} | {row['status']} | "
            f"{result} | {row['latency_ms']} |"
        )
    table = "\n".join(table_rows)
    markdown = f"""# Evaluation Report

Generated from actual offline executions at `{metrics["generated_at"]}`.
This evaluates deterministic routing and safety logic with a fake ERP gateway;
it is not a production performance benchmark.

| Metric | Result |
|---|---:|
| Cases | {metrics["cases"]} |
| Tool-selection accuracy | {metrics["tool_selection_accuracy_percent"]}% |
| Validation success | {metrics["validation_success_percent"]}% |
| Authorization-block success | {metrics["authorization_block_success_percent"]}% |
| Unsafe-action prevention | {metrics["unsafe_action_prevention_percent"]}% |
| Citation correctness | {metrics["citation_correctness_percent"]}% |
| Median service latency | {metrics["median_latency_ms"]} ms |

| Case | Selected tool | Status | Expected status | Latency (ms) |
|---|---|---|---|---:|
{table}
"""
    (ROOT / "evaluation" / "report.md").write_text(markdown)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
