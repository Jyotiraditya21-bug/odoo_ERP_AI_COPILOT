from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchCustomerInput(StrictToolInput):
    name: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)


class CheckInventoryInput(StrictToolInput):
    product_name: str | None = Field(default=None, min_length=2, max_length=200)
    low_stock_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def require_query(self):
        if not self.product_name and not self.low_stock_only:
            raise ValueError("provide product_name or set low_stock_only")
        return self


class QuotationLineInput(StrictToolInput):
    product_name: str = Field(min_length=2, max_length=200)
    quantity: float = Field(gt=0)


class CreateDraftQuotationInput(StrictToolInput):
    customer_name: str = Field(min_length=2, max_length=200)
    lines: list[QuotationLineInput] = Field(min_length=1, max_length=20)
    discount_percent: float = Field(default=0, ge=0, le=100)


class SearchCompanyPolicyInput(StrictToolInput):
    query: str = Field(min_length=3, max_length=1000)
    limit: int = Field(default=3, ge=1, le=5)
