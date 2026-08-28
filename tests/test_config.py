from lia.config import Settings


def _settings(calendar_ids: str) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="fake",
        owner_user_id=1,
        gemini_api_key="fake",
        canvas_base_url="https://fake.instructure.com",
        canvas_access_token="fake",
        calendar_ids=calendar_ids,
    )


def test_calendar_ids_without_labels_use_id_as_label():
    settings = _settings("primary,xxx@group.calendar.google.com")
    assert settings.calendar_id_list == ["primary", "xxx@group.calendar.google.com"]
    assert settings.calendar_labels == {
        "primary": "primary",
        "xxx@group.calendar.google.com": "xxx@group.calendar.google.com",
    }


def test_calendar_ids_with_labels():
    settings = _settings("primary:Personal,xxx@group.calendar.google.com:Compartido con Fulanita")
    assert settings.calendar_id_list == ["primary", "xxx@group.calendar.google.com"]
    assert settings.calendar_labels == {
        "primary": "Personal",
        "xxx@group.calendar.google.com": "Compartido con Fulanita",
    }


def test_calendar_ids_mixed_labeled_and_unlabeled():
    settings = _settings("primary:Personal,xxx@group.calendar.google.com")
    assert settings.calendar_labels == {
        "primary": "Personal",
        "xxx@group.calendar.google.com": "xxx@group.calendar.google.com",
    }
