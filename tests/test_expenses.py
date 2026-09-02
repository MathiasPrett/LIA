import datetime as dt

from lia.db import make_engine, make_session_factory
from lia.services.expenses import (
    add_expense,
    day_bounds,
    delete_last_expense,
    format_clp,
    list_budgets,
    list_expenses,
    month_bounds,
    month_spend_for_category,
    set_budget,
    summarize,
    to_csv_bytes,
    update_last_expense,
)


def _session_factory():
    engine = make_engine(":memory:")
    return make_session_factory(engine)


def _gasto(session, monto, categoria, spent_at, descripcion="algo"):
    return add_expense(session, monto, descripcion, categoria, spent_at)


# --- Fronteras de mes: el bug más probable de esta feature ---


def test_gasto_de_la_noche_del_ultimo_dia_cuenta_en_ese_mes():
    # 23:00 del 30/09 en hora chilena. Si esto se guardara en UTC caería el 1/10.
    session_factory = _session_factory()
    with session_factory() as session:
        _gasto(session, 5000, "fiesta", dt.datetime(2026, 9, 30, 23, 0))
        septiembre = month_bounds(dt.datetime(2026, 9, 15, 12, 0))
        octubre = month_bounds(dt.datetime(2026, 10, 15, 12, 0))

        assert summarize(session, *septiembre)["total"] == 5000
        assert summarize(session, *octubre)["total"] == 0


def test_gasto_de_madrugada_del_dia_uno_no_cuenta_en_el_mes_anterior():
    session_factory = _session_factory()
    with session_factory() as session:
        _gasto(session, 7000, "comida", dt.datetime(2026, 10, 1, 0, 30))
        septiembre = month_bounds(dt.datetime(2026, 9, 15, 12, 0))
        octubre = month_bounds(dt.datetime(2026, 10, 15, 12, 0))

        assert summarize(session, *septiembre)["total"] == 0
        assert summarize(session, *octubre)["total"] == 7000


def test_month_bounds_cruza_bien_el_fin_de_ano():
    inicio, fin = month_bounds(dt.datetime(2026, 12, 10, 12, 0))
    assert inicio == dt.datetime(2026, 12, 1, 0, 0)
    assert fin.year == 2026 and fin.month == 12 and fin.day == 31


# --- Resumen ---


def test_summarize_agrupa_por_categoria_y_ordena_por_monto():
    session_factory = _session_factory()
    with session_factory() as session:
        _gasto(session, 3000, "comida", dt.datetime(2026, 9, 2, 13, 0))
        _gasto(session, 2000, "comida", dt.datetime(2026, 9, 3, 13, 0))
        _gasto(session, 9000, "fiesta", dt.datetime(2026, 9, 4, 23, 0))

        resumen = summarize(session, *month_bounds(dt.datetime(2026, 9, 15)))

        assert resumen["total"] == 14000
        assert resumen["por_categoria"][0] == {"categoria": "fiesta", "total": 9000, "cantidad": 1}
        assert resumen["por_categoria"][1] == {"categoria": "comida", "total": 5000, "cantidad": 2}


def test_total_consumo_excluye_ahorro_pero_el_total_lo_incluye():
    # Un aporte a Fintual no es consumo: si entrara al total de gasto, lo inflaría.
    session_factory = _session_factory()
    with session_factory() as session:
        _gasto(session, 10000, "comida", dt.datetime(2026, 9, 2, 13, 0))
        _gasto(session, 200000, "ahorro", dt.datetime(2026, 9, 5, 10, 0))

        resumen = summarize(session, *month_bounds(dt.datetime(2026, 9, 15)))

        assert resumen["total"] == 210000
        assert resumen["total_consumo"] == 10000


def test_summarize_sin_gastos_devuelve_cero_y_no_none():
    session_factory = _session_factory()
    with session_factory() as session:
        resumen = summarize(session, *month_bounds(dt.datetime(2026, 9, 15)))
        assert resumen["total"] == 0
        assert resumen["total_consumo"] == 0
        assert resumen["por_categoria"] == []


# --- Presupuestos ---


def test_presupuesto_marca_supera_solo_por_encima_del_limite():
    session_factory = _session_factory()
    with session_factory() as session:
        set_budget(session, "fiesta", 30000)

        _gasto(session, 29000, "fiesta", dt.datetime(2026, 9, 4, 23, 0))
        assert summarize(session, *month_bounds(dt.datetime(2026, 9, 15)))["presupuestos"][0]["supera"] is False

        _gasto(session, 1000, "fiesta", dt.datetime(2026, 9, 5, 23, 0))  # justo en el límite
        assert summarize(session, *month_bounds(dt.datetime(2026, 9, 15)))["presupuestos"][0]["supera"] is False

        _gasto(session, 1, "fiesta", dt.datetime(2026, 9, 6, 23, 0))  # un peso por encima
        assert summarize(session, *month_bounds(dt.datetime(2026, 9, 15)))["presupuestos"][0]["supera"] is True


def test_presupuesto_en_cero_lo_elimina():
    session_factory = _session_factory()
    with session_factory() as session:
        set_budget(session, "fiesta", 30000)
        assert list_budgets(session) == {"fiesta": 30000}
        set_budget(session, "fiesta", 0)
        assert list_budgets(session) == {}


def test_month_spend_for_category_solo_suma_esa_categoria_y_ese_mes():
    session_factory = _session_factory()
    with session_factory() as session:
        _gasto(session, 5000, "fiesta", dt.datetime(2026, 9, 4, 23, 0))
        _gasto(session, 8000, "comida", dt.datetime(2026, 9, 4, 13, 0))
        _gasto(session, 9000, "fiesta", dt.datetime(2026, 8, 4, 23, 0))  # mes anterior

        assert month_spend_for_category(session, "fiesta", dt.datetime(2026, 9, 15)) == 5000


# --- Corregir / eliminar ---


def test_corregir_ultimo_gasto_solo_toca_los_campos_pasados():
    session_factory = _session_factory()
    with session_factory() as session:
        _gasto(session, 2000, "comida", dt.datetime(2026, 9, 2, 13, 0), descripcion="helado")
        corregido = update_last_expense(session, amount_clp=3000)

        assert corregido.amount_clp == 3000
        assert corregido.description == "helado"  # intacto
        assert corregido.category == "comida"  # intacto
        assert len(list_expenses(session, *month_bounds(dt.datetime(2026, 9, 15)))) == 1


def test_corregir_y_eliminar_sin_gastos_devuelven_none_sin_reventar():
    session_factory = _session_factory()
    with session_factory() as session:
        assert update_last_expense(session, amount_clp=1000) is None
        assert delete_last_expense(session) is None


def test_eliminar_ultimo_borra_solo_el_mas_reciente():
    session_factory = _session_factory()
    with session_factory() as session:
        _gasto(session, 2000, "comida", dt.datetime(2026, 9, 2, 13, 0), descripcion="primero")
        _gasto(session, 3000, "fiesta", dt.datetime(2026, 9, 3, 23, 0), descripcion="segundo")

        borrado = delete_last_expense(session)
        restantes = list_expenses(session, *month_bounds(dt.datetime(2026, 9, 15)))

        assert borrado.description == "segundo"
        assert [e.description for e in restantes] == ["primero"]


def test_categoria_invalida_cae_en_otros():
    session_factory = _session_factory()
    with session_factory() as session:
        gasto = _gasto(session, 1000, "criptomonedas", dt.datetime(2026, 9, 2, 13, 0))
        assert gasto.category == "otros"


# --- CSV ---


def test_csv_lleva_bom_cabecera_y_fecha_local():
    session_factory = _session_factory()
    with session_factory() as session:
        _gasto(session, 2500, "comida", dt.datetime(2026, 9, 2, 13, 45), descripcion="café con leche")
        gastos = list_expenses(session, *month_bounds(dt.datetime(2026, 9, 15)))

        raw = to_csv_bytes(gastos)

        assert raw.startswith(b"\xef\xbb\xbf")  # BOM: Excel abre bien las tildes
        texto = raw.decode("utf-8-sig")
        lineas = texto.strip().splitlines()
        assert lineas[0] == "fecha,hora,monto,descripcion,categoria"
        assert lineas[1] == "2026-09-02,13:45,2500,café con leche,comida"


def test_csv_vacio_deja_solo_la_cabecera():
    assert to_csv_bytes([]).decode("utf-8-sig").strip() == "fecha,hora,monto,descripcion,categoria"


# --- Rango por días ---


def test_day_bounds_incluye_el_dia_final_completo():
    inicio, fin = day_bounds(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert inicio == dt.datetime(2026, 9, 1, 0, 0)
    assert fin.day == 30 and fin.hour == 23 and fin.minute == 59


# --- Formato ---


def test_format_clp_usa_punto_de_miles():
    assert format_clp(34000) == "$34.000"
    assert format_clp(2000) == "$2.000"
    assert format_clp(500) == "$500"
    assert format_clp(1234567) == "$1.234.567"
