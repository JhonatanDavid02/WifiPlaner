"""Caché de la cobertura del AP seleccionado: sin RF para cambios de UI.

Cuenta las ejecuciones REALES de ``simulate_coverage`` (el símbolo que
usa ``ui.session``) en lugar de mirar hashes o píxeles:

    NO recalculan RF →  A) seleccionar un AP con cobertura cacheada,
                        B) volver a seleccionar el mismo AP,
                        C) mover un cliente,
                        D) desactivar el heatmap,
                        E) cambiar la métrica RSSI ↔ SNR;
    SÍ recalculan    →  F) mover un AP,
                        G) mover una pared,
                        H) cambiar de banda,
                        I) cambiar la resolución.
"""

from __future__ import annotations

import time

import pytest

from core.geometry import Point2D
from tests.factories import make_session
from ui import session as session_mod
from ui.session import SelectionKind

# 20×10 m @ 1,0 m => 21 × 11 = 231 puntos por pase de cobertura.
POINTS_PER_PASS = 231


def count_rf(monkeypatch):
    """Envuelve ``ui.session.simulate_coverage`` y devuelve el contador."""
    counts = {"calls": 0, "points": 0}
    original = session_mod.simulate_coverage

    def wrapper(*args, **kwargs):
        counts["calls"] += 1
        points = kwargs.get("sample_points")
        if points is None and len(args) > 2:
            points = args[2]
        counts["points"] += len(points or [])
        return original(*args, **kwargs)

    monkeypatch.setattr(session_mod, "simulate_coverage", wrapper)
    return counts


@pytest.fixture
def rf(monkeypatch):
    return count_rf(monkeypatch)


def build_session():
    """Plano 20×10 @ 1,0 m: 2 APs, 1 pared, 1 cliente, sin selección."""
    session = make_session()
    session.set_floor_dimensions(20.0, 10.0)
    session.set_grid_resolution(1.0)
    session.set_snap_to_grid(False)
    ap1 = session.add_access_point(Point2D(2.0, 5.0))
    ap2 = session.add_access_point(Point2D(18.0, 5.0))
    wall = session.add_wall(Point2D(10.0, 0.0), Point2D(10.0, 10.0))
    session.set_wall_material(wall.id, "concrete")
    client = session.add_client(Point2D(4.0, 5.0))
    session.select(None, None)
    return session, ap1, ap2, wall, client


def reset(counts):
    counts["calls"] = 0
    counts["points"] = 0


# ===========================================================================
# A + B) seleccionar / re-seleccionar un AP reutiliza la caché
# ===========================================================================

def test_selecting_an_ap_reuses_the_cached_coverage(rf):
    session, ap1, ap2, _wall, _client = build_session()

    # A) primera selección: sí hay que calcularla (una vez, un pase).
    session.select(SelectionKind.AP, ap1.id)
    first = session.selected_ap_coverage()
    assert first is not None
    assert rf["calls"] == 1
    assert rf["points"] == POINTS_PER_PASS

    # Deseleccionar no calcula nada ni tira la caché.
    session.select(None, None)
    assert session.selected_ap_coverage() is None
    assert rf["calls"] == 1

    # B) volver al MISMO AP: 0 llamadas, el MISMO objeto de resultado.
    session.select(SelectionKind.AP, ap1.id)
    assert session.selected_ap_coverage() is first
    assert rf["calls"] == 1

    # Otro AP, primera vez: sí calcula la SUYA.
    session.select(SelectionKind.AP, ap2.id)
    second = session.selected_ap_coverage()
    assert second is not None and second is not first
    assert rf["calls"] == 2
    assert second.evaluations[0].access_point_id == ap2.id

    # Y volver al primero: reutiliza lo ya calculado.
    session.select(SelectionKind.AP, ap1.id)
    assert session.selected_ap_coverage() is first
    assert rf["calls"] == 2


def test_selection_does_not_run_the_background_heatmap(rf):
    session, ap1, _ap2, _wall, _client = build_session()
    session.run_heatmap()
    session.heatmap_dirty = False
    reset(rf)

    session.select(SelectionKind.AP, ap1.id)
    session.selected_ap_coverage()

    # La selección solo toca su capa: el fondo NO se recalcula.
    assert session.heatmap_dirty is False
    assert rf["calls"] == 1  # solo la capa (cacheada a partir de ahí)


# ===========================================================================
# C) mover un cliente no toca la cobertura del AP
# ===========================================================================

def test_moving_a_client_does_not_recalculate_the_ap_coverage(rf):
    session, ap1, _ap2, _wall, client = build_session()
    session.select(SelectionKind.AP, ap1.id)
    session.run_heatmap()
    cached = session.selected_ap_coverage()
    assert rf["calls"] > 0
    reset(rf)
    assert session.heatmap_dirty is False

    session.move_client(client.id, Point2D(6.0, 7.0))

    # Ni la capa del AP ni el fondo se recalculan: la posición de un
    # cliente no cambia paredes, APs, banda ni resolución.
    assert session.selected_ap_coverage() is cached
    assert rf["calls"] == 0
    assert session.heatmap_dirty is False


# ===========================================================================
# F/G/H/I) lo que SÍ debe invalidar
# ===========================================================================

def test_moving_an_ap_invalidates_the_cached_coverage(rf):
    session, ap1, _ap2, _wall, _client = build_session()
    session.select(SelectionKind.AP, ap1.id)
    session.run_heatmap()
    before = session.selected_ap_coverage()
    reset(rf)
    assert session.heatmap_dirty is False

    session.move_ap(ap1.id, Point2D(4.0, 7.0))

    assert session.heatmap_dirty is True  # el fondo, invalidado
    after = session.selected_ap_coverage()
    assert rf["calls"] == 1  # la capa, recalculada
    assert rf["points"] == POINTS_PER_PASS
    assert after is not before  # otra posición del AP, otro resultado
    assert [e.rx_power_dbm for e in after.evaluations] != [
        e.rx_power_dbm for e in before.evaluations
    ]


def test_moving_a_wall_invalidates_the_cached_coverage(rf):
    session, ap1, _ap2, wall, _client = build_session()
    session.select(SelectionKind.AP, ap1.id)
    session.run_heatmap()
    before = session.selected_ap_coverage()
    reset(rf)

    session.move_wall(wall.id, Point2D(2.0, 0.0))

    assert session.heatmap_dirty is True
    after = session.selected_ap_coverage()
    assert rf["calls"] == 1
    assert after is not before  # otra geometría, otro resultado


def test_changing_band_invalidates_the_cached_coverage(rf):
    session, ap1, _ap2, _wall, _client = build_session()
    session.select(SelectionKind.AP, ap1.id)
    session.run_heatmap()
    at_24 = session.selected_ap_coverage()
    reset(rf)

    session.set_band("band_5")

    assert session.heatmap_dirty is True
    at_5 = session.selected_ap_coverage()
    assert rf["calls"] == 1  # clave con banda distinta
    assert at_5.band_id == "band_5"
    assert at_5 is not at_24
    # La diferencia 2.4 → 5 GHz sigue existiendo en los RSSI.
    rssi_24 = [e.rx_power_dbm for e in at_24.evaluations]
    rssi_5 = [e.rx_power_dbm for e in at_5.evaluations]
    assert rssi_5 != rssi_24


def test_changing_resolution_invalidates_the_cached_coverage(rf):
    session, ap1, _ap2, _wall, _client = build_session()
    session.select(SelectionKind.AP, ap1.id)
    session.run_heatmap()
    session.selected_ap_coverage()
    reset(rf)

    session.set_grid_resolution(0.5)

    assert session.heatmap_dirty is True
    session.selected_ap_coverage()
    assert rf["calls"] == 1
    # 41 × 21 = 861 puntos: la clave incluye la resolución del grid.
    assert rf["points"] == 861


# ===========================================================================
# D + E) con la app real (Tk fuera de pantalla): heatmap y métrica
# ===========================================================================

@pytest.fixture
def tk_app(monkeypatch):
    counts = count_rf(monkeypatch)
    try:
        import tkinter  # noqa: F401
        from ui.app import WifiPlannerApp
    except Exception as exc:  # pragma: no cover - depende del sistema
        pytest.skip(f"Tkinter no disponible: {exc}")

    session, ap1, ap2, wall, client = build_session()
    # WifiPlannerApp ES la raíz de Tk: NO se crea otra (dos intérpretes
    # de Tk en el mismo proceso harían que las PhotoImage se crearan en
    # el intérpreter equivocado). Debounce enorme: los timer automáticos
    # no se disparan solos; nosotros llamamos a _run_heatmap_now().
    try:
        app = WifiPlannerApp(session=session, heatmap_debounce_ms=600_000)
    except Exception as exc:  # pragma: no cover - sin display
        pytest.skip(f"No hay display para Tk: {exc}")
    root = app  # misma raíz/intérprete para todo el test
    root.geometry("800x600+4000+4000")
    root.update_idletasks()
    root.update()
    time.sleep(0.25)
    root.update()  # dispara _initial_render y _schedule_heatmap
    if app._heatmap_after_id is not None:
        app.after_cancel(app._heatmap_after_id)
        app._heatmap_after_id = None

    try:
        yield root, app, session, counts, ap1, ap2, wall, client
    finally:
        root.destroy()


def _prime(tk_env):
    """Estado de trabajo normal: fondo + resaltado calculados."""
    root, app, session, counts, ap1, *_ = tk_env
    session.select(SelectionKind.AP, ap1.id)
    app._run_heatmap_now()
    root.update()
    assert session.heatmap_dirty is False
    reset(counts)
    return root, app, session, counts


def _run_deferred(root, app):
    """Ejecuta lo que el debounce habría ejecutado (y lo cancela)."""
    if app._heatmap_after_id is not None:
        app.after_cancel(app._heatmap_after_id)
        app._heatmap_after_id = None
        app._run_heatmap_now()
        root.update()
        return True
    return False


def test_selecting_an_ap_from_the_ui_runs_no_rf(tk_app):
    """Flujo real: canvas → select() → _on_model_changed → diferido."""
    root, app, session, counts, ap1, *_ = tk_app
    _prime(tk_app)

    # Selección del mismo AP (clic repetido / re-selección).
    session.select(SelectionKind.AP, ap1.id)
    app._on_model_changed()
    root.update()
    assert app._heatmap_after_id is not None  # solo agenda el refresco

    assert _run_deferred(root, app) is True
    assert counts["calls"] == 0  # ni la capa ni el fondo simularon
    assert session.heatmap_dirty is False


def test_moving_a_client_from_the_ui_runs_no_rf(tk_app):
    root, app, session, counts, _ap1, _ap2, _wall, client = tk_app
    _prime(tk_app)

    session.move_client(client.id, Point2D(7.0, 8.0))
    app._on_model_changed()
    root.update()
    ran = _run_deferred(root, app)

    assert ran is True
    assert counts["calls"] == 0
    assert session.heatmap_dirty is False
    # El estado del cliente sí se actualiza (caché de clientes aparte).
    state = session.client_state(
        next(c for c in session.project.clients if c.id == client.id)
    )
    assert state.rssi_dbm is not None


def test_deactivating_the_heatmap_runs_no_rf(tk_app):
    root, app, session, counts, *_ = tk_app
    _prime(tk_app)
    assert app.canvas._heatmap_image is not None

    app._on_heatmap_toggle(False)
    root.update()

    assert counts["calls"] == 0  # sin simulate_coverage
    assert app.canvas._heatmap_image is None  # heatmap oculto
    # El resaltado del AP sigue pintado (capa independiente).
    assert app.canvas._ap_coverage_image is not None
    assert app.canvas.find_withtag("ap_coverage")


def test_changing_the_metric_only_repaints(tk_app):
    root, app, session, counts, *_ = tk_app
    _prime(tk_app)
    image_before = app.canvas._heatmap_image

    app._on_heatmap_metric("snr")
    root.update()

    assert counts["calls"] == 0  # sin RF
    assert session.heatmap_metric == "snr"
    assert session.heatmap_dirty is False  # el fondo sigue válido
    assert session.last_heatmap is not None
    assert app.canvas._heatmap_image is not None
    assert app.canvas._heatmap_image is not image_before  # repintada
    assert app.canvas._heatmap_photo is not None

    app._on_heatmap_metric("rssi")
    root.update()
    assert counts["calls"] == 0
    assert session.heatmap_dirty is False


def test_changing_the_metric_without_result_schedules_the_normal_path(tk_app):
    """Sin heatmap calculado, la métrica agenda el cálculo normal."""
    root, app, session, counts, *_ = tk_app
    assert session.last_heatmap is None

    app._on_heatmap_metric("snr")
    root.update()

    assert counts["calls"] == 0  # el RF corre tras el debounce, no ya
    assert app._heatmap_after_id is not None  # queda programado
    if app._heatmap_after_id is not None:
        app.after_cancel(app._heatmap_after_id)
