import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, logger
from app.llm.providers import build_provider
from app.rag.index import PolicyIndex
from app.schemas.api import ChatRequest, ChatResponse, ConfirmationRequest, ConfirmationResponse
from app.service import CopilotService
from app.tools.gateway import OdooGateway
from app.tools.registry import ToolRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if len(settings.odoo_service_key.get_secret_value()) < 24:
        raise RuntimeError("ODOO_SERVICE_KEY must be configured with at least 24 characters")
    configure_logging(settings.log_level)
    index = PolicyIndex(
        settings.policy_dir, settings.chroma_path, settings.policy_relevance_threshold
    )
    index.build()
    gateway = OdooGateway(settings)
    app.state.service = CopilotService(
        build_provider(settings), ToolRegistry(settings, gateway, index), gateway
    )
    yield


app = FastAPI(title="Secure Odoo AI Copilot", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


def require_odoo_service(
    settings: Annotated[Settings, Depends(get_settings)],
    x_odoo_service_key: Annotated[str, Header()] = "",
) -> None:
    import secrets

    if not secrets.compare_digest(x_odoo_service_key, settings.odoo_service_key.get_secret_value()):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Unauthorized service caller")


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, _exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "correlation_id": request.state.correlation_id,
            "category": "request_validation",
            "message": "The request payload is invalid.",
        },
    )


@app.exception_handler(Exception)
async def unexpected_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled_error",
        correlation_id=request.state.correlation_id,
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "correlation_id": request.state.correlation_id,
            "category": "internal_error",
            "message": "An unexpected error occurred.",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_odoo_service)])
async def chat(payload: ChatRequest, request: Request):
    return await request.app.state.service.chat(payload, request.state.correlation_id)


@app.post(
    "/v1/confirm", response_model=ConfirmationResponse, dependencies=[Depends(require_odoo_service)]
)
async def confirm(payload: ConfirmationRequest, request: Request):
    return await request.app.state.service.confirm(payload, request.state.correlation_id)
