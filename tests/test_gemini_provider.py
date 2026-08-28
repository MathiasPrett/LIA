from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lia.llm.base import HistoryTurn
from lia.llm.gemini import GeminiProvider
from lia.llm.registry import Tool


def _usage(tokens_in: int, tokens_out: int) -> SimpleNamespace:
    return SimpleNamespace(prompt_token_count=tokens_in, candidates_token_count=tokens_out)


def _text_response(text: str, tokens_in: int = 10, tokens_out: int = 5) -> SimpleNamespace:
    part = SimpleNamespace(function_call=None, text=text)
    content = SimpleNamespace(parts=[part], role="model")
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(
        candidates=[candidate], usage_metadata=_usage(tokens_in, tokens_out), text=text
    )


def _function_call_response(
    name: str, args: dict, tokens_in: int = 10, tokens_out: int = 5
) -> SimpleNamespace:
    fc = SimpleNamespace(name=name, args=args)
    part = SimpleNamespace(function_call=fc, text=None)
    content = SimpleNamespace(parts=[part], role="model")
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(
        candidates=[candidate], usage_metadata=_usage(tokens_in, tokens_out), text=""
    )


def _make_provider() -> GeminiProvider:
    return GeminiProvider(api_key="fake-key", model="gemini-2.5-flash-lite")


@pytest.mark.asyncio
async def test_plain_text_reply_no_tools():
    provider = _make_provider()
    provider._client.aio.models.generate_content = AsyncMock(
        return_value=_text_response("Hola, ¿en qué te ayudo?")
    )

    result = await provider.run_conversation(
        system_prompt="sos LIA", history=[], user_message="hola", tools=[]
    )

    assert result.reply_text == "Hola, ¿en qué te ayudo?"
    assert result.pending_confirmation is None
    assert result.tokens_in == 10
    assert result.tokens_out == 5


@pytest.mark.asyncio
async def test_read_tool_is_executed_automatically():
    handler = AsyncMock(return_value={"eventos": []})
    tool = Tool(
        name="listar_eventos",
        description="lista eventos",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        requires_confirmation=False,
    )
    provider = _make_provider()
    provider._client.aio.models.generate_content = AsyncMock(
        side_effect=[
            _function_call_response("listar_eventos", {"desde": "2026-08-27", "hasta": "2026-08-27"}),
            _text_response("No tenés eventos hoy."),
        ]
    )

    result = await provider.run_conversation(
        system_prompt="sos LIA", history=[], user_message="qué tengo hoy", tools=[tool]
    )

    handler.assert_awaited_once_with(desde="2026-08-27", hasta="2026-08-27")
    assert result.reply_text == "No tenés eventos hoy."
    assert result.pending_confirmation is None
    assert len(result.tool_invocations) == 1
    assert result.tool_invocations[0].tool_name == "listar_eventos"
    assert result.tokens_in == 20  # dos llamadas, 10 c/u
    assert result.tokens_out == 10


@pytest.mark.asyncio
async def test_write_tool_stops_for_confirmation_without_executing():
    handler = AsyncMock(return_value={"titulo": "no debería llamarse"})
    tool = Tool(
        name="crear_evento",
        description="crea evento",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        requires_confirmation=True,
        confirmation_summary=lambda args: f"Evento: {args['titulo']}",
    )
    provider = _make_provider()
    provider._client.aio.models.generate_content = AsyncMock(
        return_value=_function_call_response(
            "crear_evento",
            {"titulo": "Almuerzo con Javi", "inicio": "2026-08-29T13:00:00-04:00", "fin": "2026-08-29T14:00:00-04:00"},
        )
    )

    result = await provider.run_conversation(
        system_prompt="sos LIA",
        history=[],
        user_message="agendame almuerzo con Javi el viernes a la 1",
        tools=[tool],
    )

    handler.assert_not_awaited()
    assert result.pending_confirmation is not None
    assert result.pending_confirmation.tool_name == "crear_evento"
    assert result.pending_confirmation.summary == "Evento: Almuerzo con Javi"
    assert result.pending_confirmation.arguments["titulo"] == "Almuerzo con Javi"


@pytest.mark.asyncio
async def test_history_turns_are_included_in_contents():
    provider = _make_provider()
    seen_contents = []

    async def fake_generate_content(*, model, contents, config):
        seen_contents.append(list(contents))  # copia: el código muta la lista original después
        return _text_response("dale")

    provider._client.aio.models.generate_content = fake_generate_content

    await provider.run_conversation(
        system_prompt="sos LIA",
        history=[
            HistoryTurn(role="user", text="hola"),
            HistoryTurn(role="assistant", text="hola, ¿en qué te ayudo?"),
        ],
        user_message="nada, gracias",
        tools=[],
    )

    contents = seen_contents[0]
    assert len(contents) == 3
    assert contents[0].role == "user"
    assert contents[1].role == "model"
    assert contents[2].role == "user"


@pytest.mark.asyncio
async def test_gives_up_after_max_iterations():
    handler = AsyncMock(return_value={"ok": True})
    tool = Tool(
        name="listar_eventos",
        description="lista eventos",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        requires_confirmation=False,
    )
    provider = _make_provider()
    provider._client.aio.models.generate_content = AsyncMock(
        return_value=_function_call_response("listar_eventos", {"desde": "x", "hasta": "y"})
    )

    result = await provider.run_conversation(
        system_prompt="sos LIA", history=[], user_message="qué tengo", tools=[tool]
    )

    assert result.pending_confirmation is None
    assert "intenta de nuevo" in result.reply_text.lower()
