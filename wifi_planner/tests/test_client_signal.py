"""Estado RF de los clientes: integración real con el motor y con la UI.

Comprueba que el estado de cada cliente sale del RSSI **real** calculado
en su posición (``engine.simulator.simulate_coverage``, la misma ruta que
alimenta el heatmap), que se clasifica con los límites de
``ui/client_signal.py``, que el indicador se pinta en el lienzo y que el
panel de información lo muestra — y que todo esto se actualiza cuando
cambia la RF del documento (AP, cliente, paredes, banda).

Escenario de los 5 estados (piso 60×10, AP en (2,5)):

    pared x=12 concreto (12 dB), x=16 ladrillo (6 dB),
    x=52 concreto reforzado (15 dB)

    CLIENT-001 (4,5)   2 m  -> SEÑAL BUENA
    CLIENT-002 (14,5) 12 m  -> SEÑAL FUERTE
    CLIENT-003 (17,5) 15 m  -> SEÑAL DÉBIL
    CLIENT-004 (45,5) 43 m  -> SEÑAL INESTABLE
    CLIENT-005 (55,5) 53 m  -> SIN SEÑAL

Los valores concretos los decide el motor RF (aquí solo se comprueba la
coherencia: la UI nunca calcula RSSI por su cuenta ni lee el heatmap).
"""

from __future__ import annotations

import pytest

from core.geometry import Point2D
from engine.simulator import simulate_coverage
from tests.factories import make_session
from ui.client_signal import (
    BUENA_MIN_DBM,
    DEBIL_MIN_DBM,
    FUERTE_MIN_DBM,
    INESTABLE_MIN_DBM,
    STATE_BUENA,
    STATE_DEBIL,
    STATE_FUERTE,
    STATE_INESTABLE,
    STATE_SIN_SENAL,
    evaluate_client_state,
    state_for_rssi,
)
from ui.session import SelectionKind
from ui.viewport import Viewport

# ---------------------------------------------------------------------------
# Escenario de referencia (5 clientes, 3 paredes, 1 AP)
# ---------------------------------------------------------------------------

WALLS = (
    (12.0, "concrete"),
    (16.0, "brick"),
    (52.0, "reinforced_concrete"),
)
CLIENT_POSITIONS = (
    (4.0, 5.0),
    (14.0, 5.0),
    (17.0, 5.0),
    (45.0, 5.0),
    (55.0, 5.0),
)


def build_scenario():
    """Sesión con 1 AP, 3 paredes y 5 clientes a distancias crecientes."""
    session = make_session()
    session.set_floor_dimensions(60.0, 10.0)
    session.set_snap_to_grid(False)
    session.add_access_point(Point2D(2.0, 5.0))
    for x, material_id in WALLS:
        wall = session.add_wall(Point2D(x, 0.0), Point2D(x, 10.0))
        session.set_wall_material(wall.id, material_id)
    clients = [session.add_client(Point2D(x, y)) for x, y in CLIENT_POSITIONS]
    return session, clients


# ===========================================================================
# Clasificación (límites centralizados)
# ===========================================================================

def test_state_for_rssi_uses_the_central_limits():
    assert state_for_rssi(-40.0) == STATE_BUENA
    assert state_for_rssi(BUENA_MIN_DBM) == STATE_BUENA
    assert state_for_rssi(BUENA_MIN_DBM - 0.1) == STATE_FUERTE
    assert state_for_rssi(FUERTE_MIN_DBM) == STATE_FUERTE
    assert state_for_rssi(FUERTE_MIN_DBM - 0.1) == STATE_DEBIL
    assert state_for_rssi(DEBIL_MIN_DBM) == STATE_DEBIL
    assert state_for_rssi(DEBIL_MIN_DBM - 0.1) == STATE_INESTABLE
    assert state_for_rssi(INESTABLE_MIN_DBM) == STATE_INESTABLE
    assert state_for_rssi(INESTABLE_MIN_DBM - 0.1) == STATE_SIN_SENAL
    # Sin evaluación (o valor no finito) => SIN SEÑAL.
    assert state_for_rssi(None) == STATE_SIN_SENAL
    assert state_for_rssi(float("nan")) == STATE_SIN_SENAL


# ===========================================================================
# El estado sale del motor RF real (misma ruta que el heatmap)
# ===========================================================================

def test_client_state_is_the_engine_rssi_at_the_exact_position():
    """El RSSI mostrado ES el del engine en la posición del cliente."""
    session, clients = build_scenario()
    client = clients[1]
    ap = session.project.access_points[0]

    state = session.client_state(client)

    # Misma llamada que hace el heatmap por punto (Fase 4), con la
    # posición exacta del cliente como única muestra.
    result = simulate_coverage(
        project=session.project,
        access_point=ap,
        frequency_band=session.resolve_band_for_ap(ap, session.band_id),
        sample_points=[client.position],
        walls=session.floor.walls,
        openings=session.floor.openings,
        obstacles=session.floor.obstacles,
    )
    evaluation = result.evaluations[0]

    assert state.rssi_dbm == evaluation.rx_power_dbm
    assert state.snr_db == evaluation.snr_db
    assert state.distance_m == evaluation.distance_m
    assert state.ap_id == ap.id
    assert state.band_id == "band_2_4"
    assert state.band_name == "2.4 GHz"
    assert state.state == state_for_rssi(evaluation.rx_power_dbm)
    assert state.associated is True


def test_scenario_shows_the_five_states():
    """1 AP, clientes a distintas distancias y paredes entre ellos."""
    session, clients = build_scenario()

    states = [session.client_state(c) for c in clients]

    assert [s.state for s in states] == [
        STATE_BUENA,
        STATE_FUERTE,
        STATE_DEBIL,
        STATE_INESTABLE,
        STATE_SIN_SENAL,
    ]
    # La señal cae monótonamente con la distancia + paredes.
    rssi = [s.rssi_dbm for s in states]
    assert all(a > b for a, b in zip(rssi, rssi[1:]))
    # Cada etiqueta es la de SU RSSI (nada inventado por la UI).
    for state in states:
        assert state.state == state_for_rssi(state.rssi_dbm)
    # El cliente sin señal utilizable queda SIN asociación...
    assert states[4].associated is False
    # ...pero la medición existe (hubo evaluación, vino por debajo del
    # umbral): el panel puede enseñar el número.
    assert states[4].measured is True
    assert states[4].ap_id is not None


def test_client_state_without_ap_is_sin_senal():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    client = session.add_client(Point2D(5.0, 5.0))

    state = session.client_state(client)

    assert state.ap_id is None
    assert state.rssi_dbm is None
    assert state.associated is False
    assert state.measured is False
    assert state.state == STATE_SIN_SENAL


def test_client_state_associates_the_ap_with_best_rssi():
    session = make_session()
    session.set_floor_dimensions(30.0, 10.0)
    session.set_snap_to_grid(False)
    near_right = session.add_access_point(Point2D(26.0, 5.0))
    near_left = session.add_access_point(Point2D(2.0, 5.0))

    close_to_right = session.add_client(Point2D(24.0, 5.0))
    close_to_left = session.add_client(Point2D(4.0, 5.0))

    assert session.client_state(close_to_right).ap_id == near_right.id
    assert session.client_state(close_to_left).ap_id == near_left.id
    assert near_left.id != near_right.id


# ===========================================================================
# Actualización dinámica: nada queda congelado desde que se creó el cliente
# ===========================================================================

def test_client_state_cache_is_reused_and_invalidated_by_edits():
    session, clients = build_scenario()
    client = clients[0]

    first = session.client_state(client)
    assert session.client_state(client) is first  # caché dentro del ciclo

    session.move_client(client.id, Point2D(4.0, 9.0))

    after_move = session.client_state(client)
    assert after_move is not first  # la entrada del movido se invalidó
    assert after_move.rssi_dbm != first.rssi_dbm
    # ...y el estado de los demás no se tira (los clientes no irradian):
    # es lo que mantiene fluido el arrastre en planos con muchos clientes.
    others = session.client_states()
    assert others[clients[3].id] is not None


def test_adding_a_client_reuses_the_states_of_the_others():
    session, clients = build_scenario()
    states = session.client_states()
    assert len(states) == len(clients)
    untouched = states[clients[2].id]

    nuevo = session.add_client(Point2D(8.0, 5.0))

    after = session.client_states()
    assert len(after) == len(clients) + 1
    assert after[nuevo.id].rssi_dbm is not None  # el nuevo sí se calcula
    assert after[clients[2].id] is untouched      # los demás se reutilizan


def test_deleting_a_client_drops_its_state():
    session, clients = build_scenario()
    session.client_states()
    victim = clients[0]

    session.select(SelectionKind.CLIENT, victim.id)
    assert session.delete_selection() is True

    assert victim.id not in session.client_states()
    assert len(session.client_states()) == len(clients) - 1


def test_client_state_updates_when_the_ap_moves():
    session, clients = build_scenario()
    client = clients[1]
    before = session.client_state(client)

    session.move_ap(session.project.access_points[0].id, Point2D(2.0, 1.0))

    after = session.client_state(client)
    assert after.rssi_dbm != before.rssi_dbm
    assert after.state == state_for_rssi(after.rssi_dbm)


def test_client_state_updates_when_a_wall_is_removed():
    session, clients = build_scenario()
    client = clients[2]  # detrás de ladrillo (x=16) + concreto (x=12)
    before = session.client_state(client)
    assert before.state == STATE_DEBIL

    wall = session.floor.walls[1]
    session.select(SelectionKind.WALL, wall.id)
    assert session.delete_selection() is True

    after = session.client_state(client)
    assert after.rssi_dbm > before.rssi_dbm
    assert after.state == state_for_rssi(after.rssi_dbm)


def test_client_state_updates_on_band_change():
    session, clients = build_scenario()
    client = clients[2]
    band_24 = session.client_state(client)

    session.set_band("band_5")

    band_5 = session.client_state(client)
    assert band_5.band_name == "5 GHz"
    assert band_5.rssi_dbm != band_24.rssi_dbm
    # A 5 GHz la pérdida es mayor: el RSSI baja.
    assert band_5.rssi_dbm < band_24.rssi_dbm
    assert band_5.state == state_for_rssi(band_5.rssi_dbm)


def test_evaluate_client_state_never_raises_without_aps():
    session = make_session()
    client = session.add_client(Point2D(1.0, 1.0))
    state = evaluate_client_state(session, client)
    assert state.state == STATE_SIN_SENAL


# ===========================================================================
# UI: indicador en el plano + panel de información
# ===========================================================================

@pytest.fixture
def tk_editor():
    """Lienzo + panel de propiedades reales, fuera de la pantalla."""
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - depende del sistema
        pytest.skip(f"Tkinter no disponible: {exc}")
    try:
        root = tk.Tk()
    except Exception as exc:  # pragma: no cover - sin display
        pytest.skip(f"No hay display para Tk: {exc}")

    session = make_session()
    root.geometry("640x480+4000+4000")
    root.update_idletasks()
    root.update()

    from ui.editor_canvas import EditorCanvas
    from ui.panels.properties import PropertiesPanel

    viewport = Viewport(
        world_width_m=session.floor_width_m,
        world_height_m=session.floor_height_m,
        canvas_width_px=640,
        canvas_height_px=480,
    )
    canvas = EditorCanvas(
        root,
        session=session,
        viewport=viewport,
        on_model_changed=lambda: None,
        on_cursor=lambda _x, _y: None,
    )
    canvas.pack(fill="both", expand=True)
    properties = PropertiesPanel(
        root,
        session=session,
        on_changed=lambda: None,
        on_simulate=lambda: None,
    )
    root.update()
    try:
        yield root, canvas, viewport, session, properties
    finally:
        root.destroy()


def _indicator_color(canvas, slug: str) -> str:
    """Color del badge del estado indicado (señal del lienzo)."""
    from ui import theme

    items = canvas.find_withtag(f"client_state:{slug}")
    assert items, f"no hay indicador '{slug}' en el lienzo"
    badge = canvas.itemcget(items[-1], "fill")
    halo = canvas.itemcget(items[0], "outline")
    assert badge == halo
    assert badge == theme.CLIENT_STATE_COLOR[
        {
            "buena": STATE_BUENA,
            "fuerte": STATE_FUERTE,
            "debil": STATE_DEBIL,
            "inestable": STATE_INESTABLE,
            "sin_senal": STATE_SIN_SENAL,
        }[slug]
    ]
    return badge


def test_canvas_draws_the_client_state_indicator(tk_editor):
    root, canvas, viewport, session, _properties = tk_editor
    session.set_floor_dimensions(60.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    client = session.add_client(Point2D(4.0, 5.0))

    canvas.render_project()
    root.update()

    state = session.client_state(client)
    assert state.state == STATE_BUENA
    # Halo + badge con el color del estado (tag por estado).
    assert len(canvas.find_withtag("client_state:buena")) == 2
    color = _indicator_color(canvas, "buena")
    assert color

    # El icono del cliente sigue pintándose (el indicador es un extra,
    # no sustituye al cliente por un círculo de cobertura).
    from ui import theme

    session.select(None, None)
    canvas.render_project()
    root.update()
    iconos = [
        i
        for i in canvas.find_withtag("all")
        if canvas.type(i) == "oval"
        and canvas.itemcget(i, "fill") == theme.CLIENT_COLOR
    ]
    assert iconos


def test_canvas_indicator_changes_when_the_rf_changes(tk_editor):
    root, canvas, viewport, session, _properties = tk_editor
    session.set_floor_dimensions(60.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    for x, material_id in ((12.0, "concrete"), (16.0, "brick")):
        wall = session.add_wall(Point2D(x, 0.0), Point2D(x, 10.0))
        session.set_wall_material(wall.id, material_id)
    client = session.add_client(Point2D(17.0, 5.0))

    canvas.render_project()
    root.update()
    assert session.client_state(client).state == STATE_DEBIL
    debil_color = _indicator_color(canvas, "debil")

    # Cambio de banda: mismo cliente, otra frecuencia, otro estado.
    session.set_band("band_5")
    canvas.render_project()
    root.update()

    state = session.client_state(client)
    assert state.state == state_for_rssi(state.rssi_dbm)
    assert state.state != STATE_DEBIL
    slug = {
        STATE_BUENA: "buena",
        STATE_FUERTE: "fuerte",
        STATE_DEBIL: "debil",
        STATE_INESTABLE: "inestable",
        STATE_SIN_SENAL: "sin_senal",
    }[state.state]
    nuevo_color = _indicator_color(canvas, slug)
    assert nuevo_color != debil_color
    # El estado viejo ya no está pintado.
    assert canvas.find_withtag("client_state:debil") == ()


def test_properties_panel_shows_client_rf_info(tk_editor):
    root, canvas, viewport, session, properties = tk_editor
    session.set_floor_dimensions(60.0, 10.0)
    ap = session.add_access_point(Point2D(2.0, 5.0))
    client = session.add_client(Point2D(4.0, 5.0))

    session.select(SelectionKind.CLIENT, client.id)
    properties.refresh()
    root.update()

    text = properties._info.get("1.0", "end")
    state = session.client_state(client)
    assert f"ID: {client.id}" in text
    assert f"AP asociado: {ap.id}" in text
    assert "Banda: 2.4 GHz" in text
    assert f"RSSI: {state.rssi_dbm:.1f} dBm" in text
    assert f"SNR: {state.snr_db:.1f} dB" in text
    assert f"Estado: {state.state}" in text

    # Sin AP: Ninguno + SIN SEÑAL (la medición ya no existe).
    session.select(SelectionKind.AP, ap.id)
    assert session.delete_selection() is True
    session.select(SelectionKind.CLIENT, client.id)
    properties.refresh()

    text = properties._info.get("1.0", "end")
    assert "AP asociado: Ninguno" in text
    assert "Estado: SIN SEÑAL" in text
    assert "RSSI: —" in text
    assert "SNR: —" in text


def test_properties_panel_state_tracks_the_model(tk_editor):
    root, canvas, viewport, session, properties = tk_editor
    session.set_floor_dimensions(60.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    for x, material_id in ((12.0, "concrete"), (16.0, "brick")):
        wall = session.add_wall(Point2D(x, 0.0), Point2D(x, 10.0))
        session.set_wall_material(wall.id, material_id)
    client = session.add_client(Point2D(17.0, 5.0))
    session.select(SelectionKind.CLIENT, client.id)

    properties.refresh()
    assert f"Estado: {STATE_DEBIL}" in properties._info.get("1.0", "end")

    # Cambiar la banda cambia el RSSI y el estado del panel.
    session.set_band("band_5")
    properties.refresh()
    text = properties._info.get("1.0", "end")
    state = session.client_state(client)
    assert f"Estado: {state.state}" in text
    assert f"RSSI: {state.rssi_dbm:.1f} dBm" in text
    assert state.state != STATE_DEBIL
