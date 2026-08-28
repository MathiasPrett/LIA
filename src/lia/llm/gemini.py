from google import genai
from google.genai import types

from lia.llm.base import (
    ConversationResult,
    HistoryTurn,
    LLMProvider,
    PendingConfirmation,
    ToolInvocation,
)
from lia.llm.registry import Tool

MAX_TOOL_ITERATIONS = 5

# USD por 1M tokens. Actualizar si cambia el modelo (ver docs/main-plan.md § Presupuesto).
# gemini-2.5-flash-lite dejó de estar disponible para API keys nuevas en ago-2026
# (antes de su retiro oficial del 16-oct-2026); gemini-3.1-flash-lite es su reemplazo.
PRICING_PER_MILLION = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICING_PER_MILLION.get(model, (0.0, 0.0))
    return (tokens_in / 1_000_000) * price_in + (tokens_out / 1_000_000) * price_out


def _to_function_declaration(tool: Tool) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters_json_schema=tool.parameters,
    )


def _build_contents(history: list[HistoryTurn], user_message: str) -> list[types.Content]:
    contents = []
    for turn in history:
        role = "model" if turn.role == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=turn.text)]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))
    return contents


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def run_conversation(
        self,
        system_prompt: str,
        history: list[HistoryTurn],
        user_message: str,
        tools: list[Tool],
    ) -> ConversationResult:
        tools_by_name = {tool.name: tool for tool in tools}
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=[_to_function_declaration(t) for t in tools])]
            if tools
            else None,
        )

        contents = _build_contents(history, user_message)
        tokens_in = 0
        tokens_out = 0
        invocations: list[ToolInvocation] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=contents, config=config
            )

            usage = response.usage_metadata
            if usage is not None:
                tokens_in += usage.prompt_token_count or 0
                tokens_out += usage.candidates_token_count or 0

            candidate = response.candidates[0]
            contents.append(candidate.content)

            function_calls = [
                part.function_call for part in candidate.content.parts if part.function_call
            ]

            if not function_calls:
                return ConversationResult(
                    reply_text=response.text or "",
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    tool_invocations=invocations,
                )

            needs_confirmation = next(
                (fc for fc in function_calls if tools_by_name[fc.name].requires_confirmation),
                None,
            )
            if needs_confirmation is not None:
                tool = tools_by_name[needs_confirmation.name]
                args = dict(needs_confirmation.args or {})
                summary = tool.confirmation_summary(args) if tool.confirmation_summary else str(args)
                return ConversationResult(
                    reply_text=response.text or None,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    pending_confirmation=PendingConfirmation(
                        tool_name=tool.name, arguments=args, summary=summary
                    ),
                    tool_invocations=invocations,
                )

            response_parts = []
            for fc in function_calls:
                tool = tools_by_name[fc.name]
                args = dict(fc.args or {})
                result = await tool.handler(**args)
                invocations.append(ToolInvocation(tool_name=fc.name, arguments=args))
                response_parts.append(types.Part.from_function_response(name=fc.name, response=result))

            contents.append(types.Content(role="user", parts=response_parts))

        return ConversationResult(
            reply_text="Se me enredaron las herramientas tratando de resolver esto — intenta de nuevo con un mensaje más simple.",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tool_invocations=invocations,
        )
