import pytest
from app.security.authorization import AuthorizationPolicy, Permission
from app.tools.registry import ToolAuthorizationError, ToolRegistry, ToolValidationError
from app.tools.schemas import CheckInventoryInput, CreateDraftQuotationInput, SearchCustomerInput
from pydantic import ValidationError


def test_customer_input_forbids_extra_fields():
    with pytest.raises(ValidationError):
        SearchCustomerInput(name="ABC", sql="DROP TABLE res_partner")


def test_inventory_requires_a_query():
    with pytest.raises(ValidationError):
        CheckInventoryInput()


@pytest.mark.parametrize("quantity", [0, -1])
def test_quotation_quantity_must_be_positive(quantity):
    with pytest.raises(ValidationError):
        CreateDraftQuotationInput(
            customer_name="ABC Industries",
            lines=[{"product_name": "Product A", "quantity": quantity}],
        )


def test_read_and_write_permissions_are_separate(settings, salesperson, employee):
    policy = AuthorizationPolicy(settings)
    assert policy.check_read(salesperson, Permission.READ_CUSTOMER).allowed
    assert policy.check_read(employee, Permission.READ_POLICY).allowed
    assert not policy.check_write(employee, Permission.CREATE_QUOTATION).allowed


def test_quantity_limit(settings, salesperson):
    decision = AuthorizationPolicy(settings).check_quotation_limits(salesperson, [101], 0)
    assert not decision.allowed


def test_salesperson_discount_limit(settings, salesperson):
    decision = AuthorizationPolicy(settings).check_quotation_limits(salesperson, [1], 16)
    assert not decision.allowed


@pytest.mark.asyncio
async def test_registry_rejects_unsupported_tool(settings, gateway, policy_index, salesperson):
    registry = ToolRegistry(settings, gateway, policy_index)
    with pytest.raises(ToolValidationError):
        await registry.execute("run_sql", {}, salesperson, "test")


@pytest.mark.asyncio
async def test_registry_blocks_unauthorized_write(settings, gateway, policy_index, employee):
    registry = ToolRegistry(settings, gateway, policy_index)
    with pytest.raises(ToolAuthorizationError):
        await registry.execute(
            "create_draft_quotation",
            {"customer_name": "ABC", "lines": [{"product_name": "Product A", "quantity": 1}]},
            employee,
            "test",
        )
