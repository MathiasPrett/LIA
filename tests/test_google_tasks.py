import datetime as dt

from lia.integrations.google_tasks import create_task, list_tasks


class _FakeInsert:
    def __init__(self, captured: dict, response: dict):
        self._captured = captured
        self._response = response

    def insert(self, tasklist, body):
        self._captured["tasklist"] = tasklist
        self._captured["body"] = body
        return self

    def list(self, tasklist, showCompleted, maxResults):
        self._captured["tasklist"] = tasklist
        self._captured["showCompleted"] = showCompleted
        self._captured["maxResults"] = maxResults
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


# --- Lectura (el bug: no existía forma de leer Google Tasks) ---


def test_list_tasks_pide_solo_las_pendientes():
    captured = {}
    service = _FakeService(captured, {"items": []})

    list_tasks(service)

    assert captured["tasklist"] == "@default"
    assert captured["showCompleted"] is False


def test_list_tasks_parsea_el_formato_real_de_google():
    # Formato exacto que devuelve la API (verificado contra la cuenta real).
    response = {
        "items": [
            {"id": "a", "title": "Entrega Letters", "due": "2026-09-03T00:00:00.000Z"},
            {"id": "b", "title": "Con notas", "notes": "detalle", "due": "2026-09-05T00:00:00.000Z"},
        ]
    }
    tareas = list_tasks(_FakeService({}, response))

    assert [t.title for t in tareas] == ["Entrega Letters", "Con notas"]
    assert tareas[0].due == dt.date(2026, 9, 3)
    assert tareas[1].notes == "detalle"


def test_tarea_sin_campo_due_queda_con_due_none():
    # Caso real de esta cuenta: Google omite `due` por completo, no lo manda en null.
    # Es lo que hace que "vence hoy" y "no tiene fecha" sean cosas distintas.
    response = {"items": [{"id": "a", "title": "Empezar Entrega 2 DDS", "status": "needsAction"}]}
    tareas = list_tasks(_FakeService({}, response))

    assert len(tareas) == 1
    assert tareas[0].due is None


def test_list_tasks_sin_items_devuelve_lista_vacia():
    assert list_tasks(_FakeService({}, {})) == []


def test_create_task_usa_el_formato_de_fecha_que_devuelve_google():
    captured = {}
    service = _FakeService(captured, {"id": "x", "title": "t", "due": "2026-09-10T00:00:00.000Z"})

    create_task(service, "t", due=dt.date(2026, 9, 10))

    assert captured["body"]["due"] == "2026-09-10T00:00:00.000Z"
