from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Secure Odoo AI Copilot"
    log_level: str = "INFO"
    odoo_base_url: str = "http://odoo:8069"
    odoo_service_key: SecretStr = SecretStr("")
    llm_provider: Literal["ollama", "openai_compatible", "rule_based"] = "ollama"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:7b"
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: SecretStr | None = None
    openai_compatible_model: str | None = None
    policy_dir: Path = Path("policies")
    chroma_path: Path = Path("data/chroma")
    policy_relevance_threshold: float = Field(0.18, ge=0, le=1)
    max_quotation_quantity: int = Field(100, ge=1)
    max_salesperson_discount: float = Field(15, ge=0, le=100)
    max_manager_discount: float = Field(30, ge=0, le=100)
    pending_action_ttl_seconds: int = Field(300, ge=30, le=3600)
    low_stock_threshold: float = Field(5, ge=0)
    request_timeout_seconds: float = Field(20, gt=0, le=120)


@lru_cache
def get_settings() -> Settings:
    return Settings()
