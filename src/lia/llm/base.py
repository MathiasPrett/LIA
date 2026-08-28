from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from lia.llm.registry import Tool


@dataclass
class PendingConfirmation:
    tool_name: str
    arguments: dict
    summary: str


@dataclass
class ToolInvocation:
    """Registro de una herramienta ejecutada durante el turno, para logging/auditoría."""

    tool_name: str
    arguments: dict


@dataclass
class ConversationResult:
    reply_text: str | None
    tokens_in: int
    tokens_out: int
    pending_confirmation: PendingConfirmation | None = None
    tool_invocations: list[ToolInvocation] = field(default_factory=list)


@dataclass
class HistoryTurn:
    role: str  # "user" | "assistant"
    text: str


class LLMProvider(ABC):
    @abstractmethod
    async def run_conversation(
        self,
        system_prompt: str,
        history: list[HistoryTurn],
        user_message: str,
        tools: list[Tool],
    ) -> ConversationResult: ...
