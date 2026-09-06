from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    async def select_tool(self, message: str) -> tuple[str | None, dict[str, Any]]: ...
