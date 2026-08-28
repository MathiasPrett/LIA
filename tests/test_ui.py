from unittest.mock import AsyncMock

import pytest
from telegram.constants import ParseMode
from telegram.error import BadRequest

from lia.bot.ui import edit_formatted, reply_formatted, send_formatted


@pytest.mark.asyncio
async def test_reply_formatted_uses_markdown_when_valid():
    message = AsyncMock()

    await reply_formatted(message, "*hola*")

    message.reply_text.assert_awaited_once_with("*hola*", parse_mode=ParseMode.MARKDOWN, reply_markup=None)


@pytest.mark.asyncio
async def test_reply_formatted_falls_back_to_plain_text_on_bad_markdown():
    message = AsyncMock()
    message.reply_text.side_effect = [BadRequest("Can't parse entities"), None]

    await reply_formatted(message, "3*4 no cierra el asterisco")

    assert message.reply_text.await_count == 2
    first_call, second_call = message.reply_text.await_args_list
    assert first_call.kwargs["parse_mode"] == ParseMode.MARKDOWN
    assert "parse_mode" not in second_call.kwargs


@pytest.mark.asyncio
async def test_send_formatted_falls_back_to_plain_text_on_bad_markdown():
    bot = AsyncMock()
    bot.send_message.side_effect = [BadRequest("Can't parse entities"), None]

    await send_formatted(bot, chat_id=123, text="texto _mal formado")

    assert bot.send_message.await_count == 2
    first_call, second_call = bot.send_message.await_args_list
    assert first_call.kwargs["parse_mode"] == ParseMode.MARKDOWN
    assert "parse_mode" not in second_call.kwargs


@pytest.mark.asyncio
async def test_edit_formatted_falls_back_to_plain_text_on_bad_markdown():
    query = AsyncMock()
    query.edit_message_text.side_effect = [BadRequest("Can't parse entities"), None]

    await edit_formatted(query, "texto *mal formado")

    assert query.edit_message_text.await_count == 2
