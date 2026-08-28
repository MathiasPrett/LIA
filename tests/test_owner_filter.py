from types import SimpleNamespace

from lia.bot.handlers import OwnerFilter


def _message(sender_id: int | None) -> SimpleNamespace:
    from_user = SimpleNamespace(id=sender_id) if sender_id is not None else None
    return SimpleNamespace(from_user=from_user)


def test_owner_is_allowed():
    owner_filter = OwnerFilter(owner_user_id=42)
    assert owner_filter.filter(_message(42)) is True


def test_stranger_is_rejected():
    owner_filter = OwnerFilter(owner_user_id=42)
    assert owner_filter.filter(_message(99)) is False


def test_message_without_user_is_rejected():
    owner_filter = OwnerFilter(owner_user_id=42)
    assert owner_filter.filter(_message(None)) is False
