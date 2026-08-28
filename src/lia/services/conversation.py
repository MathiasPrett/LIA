import json

from sqlalchemy.orm import Session

from lia.db import Conversation, LlmUsage
from lia.llm.base import ConversationResult, HistoryTurn, LLMProvider
from lia.llm.gemini import estimate_cost_usd
from lia.llm.registry import Tool


def load_recent_history(session: Session, limit: int) -> list[HistoryTurn]:
    rows = (
        session.query(Conversation)
        .order_by(Conversation.created_at.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [HistoryTurn(role=r.role, text=r.content) for r in rows]


def save_turn(session: Session, role: str, content: str, tool_calls: str | None = None) -> None:
    session.add(Conversation(role=role, content=content, tool_calls=tool_calls))
    session.commit()


def log_usage(session: Session, model: str, tokens_in: int, tokens_out: int) -> None:
    cost = estimate_cost_usd(model, tokens_in, tokens_out)
    session.add(LlmUsage(model=model, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost))
    session.commit()


async def handle_user_message(
    session: Session,
    provider: LLMProvider,
    system_prompt: str,
    tools: list[Tool],
    model: str,
    history_turns: int,
    user_message: str,
) -> ConversationResult:
    history = load_recent_history(session, history_turns)
    result = await provider.run_conversation(system_prompt, history, user_message, tools)

    log_usage(session, model, result.tokens_in, result.tokens_out)
    save_turn(session, "user", user_message)

    if result.pending_confirmation is None:
        tool_calls_json = (
            json.dumps([inv.__dict__ for inv in result.tool_invocations])
            if result.tool_invocations
            else None
        )
        save_turn(session, "assistant", result.reply_text or "", tool_calls=tool_calls_json)

    return result
