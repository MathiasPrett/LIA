import datetime as dt

from lia.integrations.google_tasks import create_task


class _FakeInsert:
    def __init__(self, captured: dict, response: dict):
        self._captured = captured
        self._response = response

    def insert(self, tasklist, body):
        self._captured["tasklist"] = tasklist
        self._captured["body"] = body
        return self

    def execute(self):
        return self._response


class _FakeService:
    def __init__(self, captured: dict, response: dict):
        self._tasks = _FakeInsert(captured, response)

    def tasks(self):
        return self._tasks


def test_create_task_minimal():
    captured = {}
    response = {"id": "task-1", "title": "Comprar pilas"}
    service = _FakeService(captured, response)

    task = create_task(service, "Comprar pilas")

    assert captured["tasklist"] == "@default"
    assert captured["body"] == {"title": "Comprar pilas"}
    assert task.id == "task-1"
    assert task.title == "Comprar pilas"
    assert task.due is None


def test_create_task_with_due_date_discards_time_and_keeps_only_date():
    captured = {}
    response = {"id": "task-2", "title": "Entregar informe", "due": "2026-09-10T00:00:00Z"}
    service = _FakeService(captured, response)

    task = create_task(service, "Entregar informe", due=dt.date(2026, 9, 10))

    assert captured["body"]["due"].startswith("2026-09-10")
    assert task.due == dt.date(2026, 9, 10)


def test_create_task_with_notes():
    captured = {}
    response = {"id": "task-3", "title": "Llamar al banco", "notes": "Preguntar por la tarjeta"}
    service = _FakeService(captured, response)

    task = create_task(service, "Llamar al banco", notes="Preguntar por la tarjeta")

    assert captured["body"]["notes"] == "Preguntar por la tarjeta"
    assert task.notes == "Preguntar por la tarjeta"
