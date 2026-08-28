from collections.abc import Awaitable, Callable
from dataclasses import dataclass

ToolHandler = Callable[..., Awaitable[dict]]
ConfirmationSummary = Callable[[dict], str]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema: {"type": "object", "properties": {...}, "required": [...]}
    handler: ToolHandler
    requires_confirmation: bool = False
    confirmation_summary: ConfirmationSummary | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def all(self) -> list[Tool]:
        return list(self._tools.values())
