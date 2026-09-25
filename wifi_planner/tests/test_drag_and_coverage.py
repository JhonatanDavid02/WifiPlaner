"""Fase 15: arrastre en el editor 2D + cobertura visual por AP.

Comprueba sobre la arquitectura existente (sin motor RF paralelo):

* el editor mueve APs y paredes con el ratón y el modelo queda actualizado;
* la posición sobrevive a guardar/cargar (schema v1);
* el pipeline F10→F12 usa la posición nueva;
* la cobertura renderizada (Pillow) cambia con la posición, la pared y la banda;
* el overlay de cobertura no intercepta los eventos del lienzo.

Los tests de interacción real abren Tkinter **fuera de la pantalla**
(ventana mapeada en ``+4000+4000``) y se omiten si no hay display.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.geometry import Point2D
from tests.factories import make_session
from ui.viewport import Viewport

CANVAS_SRC = Path(__file__).resolve().parents[1] / "ui" / "editor_canvas.py"


# ---------------------------------------------------------------------------
# Helpers (sin Tk)
# ---------------------------------------------------------------------------

def _ready_session():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.set_grid_resolution(1.0)
    return session


def _rx_avg(session) -> float:
    result = session.run_heatmap()
    return result.stats["rx_avg_dbm"]


def _image(session):
    """Imagen Pillow de la cobertura actual (lo que se ve en el lienzo)."""
    from ui.coverage_renderer import build_heatmap_image

    viewport = Viewport(
        world_width_m=session.floor_width_m,
        world_height_m=session.floor_height_m,
        canvas_width_px=400,
        canvas_height_px=400,
    )
    result = session.last_heatmap or session.run_heatmap()
    image = build_heatmap_image(
        result, viewport, cell_size_m=session.grid_resolution_m,
        metric=session.heatmap_metric,
    )
    assert image is not None
    return image


@pytest.fixture
def tk_canvas():
    """Lienzo real de Tkinter sobre una sesión 10×10 (fuera de pantalla)."""
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - depende del sistema
        pytest.skip(f"Tkinter no disponible: {exc}")
    try:
        root = tk.Tk()
    except Exception as exc:  # pragma: no cover - sin display
        pytest.skip(f"No hay display para Tk: {exc}")

    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.set_grid_resolution(2.0)

    # La ventana queda MAPEADA (los eventos sintéticos de Tk solo se
    # entregan en ventanas visibles) pero FUERA de la pantalla, para que
    # la suite no abra una ventana en el escritorio del usuario.
    root.geometry("640x480+4000+4000")
    root.update_idletasks()
    root.update()

    from ui.editor_canvas import EditorCanvas

    changes: list[int] = []
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
        on_model_changed=lambda: changes.append(1),
        on_cursor=lambda _x, _y: None,
    )
    canvas.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, canvas, viewport, session, changes
    finally:
        root.destroy()


def _drag(canvas, root, viewport, from_world, to_world, steps: int = 3):
    """Press → Motion × N → Release en coordenadas de mundo (con snap)."""
    x0, y0 = viewport.world_to_screen(from_world)
    x1, y1 = viewport.world_to_screen(to_world)
    canvas.event_generate("<ButtonPress-1>", x=int(x0), y=int(y0))
    root.update()
    for step in range(1, steps + 1):
        x = int(x0 + (x1 - x0) * step / steps)
        y = int(y0 + (y1 - y0) * step / steps)
        canvas.event_generate("<Motion>", x=x, y=y)
        root.update()
    canvas.event_generate("<ButtonRelease-1>", x=int(x1), y=int(y1))
    root.update()


# ===========================================================================
# A y B — la interacción del editor mueve APs y paredes
# ===========================================================================

def test_a_ap_is_moved_by_editor_interaction(tk_canvas):
    root, canvas, viewport, session, changes = tk_canvas
    ap = session.add_access_point(Point2D(2.0, 5.0))
    canvas.render_project()
    root.update()

    _drag(canvas, root, viewport, ap.position, Point2D(6.0, 7.0))

    moved = session.project.access_points[0].position
    assert moved != Point2D(2.0, 5.0)
    assert moved.x == pytest.approx(6.0, abs=0.6)  # snap a rejilla 0.5
    assert moved.y == pytest.approx(7.0, abs=0.6)
    assert changes, "el lienzo notificó el cambio de modelo"
    # Un arrastre = UNA entrada de historial (Fase 14.1) y es reversible.
    assert session.undo() is True
    assert session.project.access_points[0].position == Point2D(2.0, 5.0)


def test_b_wall_is_moved_by_editor_interaction(tk_canvas):
    root, canvas, viewport, session, changes = tk_canvas
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(0.0, 10.0))
    canvas.render_project()
    root.update()

    _drag(canvas, root, viewport, Point2D(0.0, 5.0), Point2D(3.0, 5.0))

    moved = session.find_wall(wall.id).segment.start
    assert moved.x == pytest.approx(3.0, abs=0.6)
    assert session.find_wall(wall.id).segment.end.x == pytest.approx(3.0, abs=0.6)
    assert session.undo() is True
    assert session.find_wall(wall.id).segment.start == Point2D(0.0, 0.0)


def test_drag_does_not_create_new_objects(tk_canvas):
    """Arrastrar en modo «Seleccionar» jamás crea entidades nuevas."""
    root, canvas, viewport, session, _changes = tk_canvas
    session.add_access_point(Point2D(2.0, 5.0))
    wall_count = len(session.floor.walls)
    canvas.render_project()
    root.update()

    _drag(canvas, root, viewport, Point2D(2.0, 5.0), Point2D(7.0, 3.0))

    assert len(session.project.access_points) == 1
    assert len(session.floor.walls) == wall_count


# ===========================================================================
# C y D — persistencia y pipeline con la posición nueva
# ===========================================================================

def test_c_moved_ap_position_survives_save_and_load(tmp_path):
    session = _ready_session()
    ap = session.add_access_point(Point2D(1.0, 1.0))
    session.move_ap(ap.id, Point2D(8.5, 6.5))
    path = str(tmp_path / "movido.json")
    session.save_project(path)

    from ui.session import EditorSession

    loaded = EditorSession()
    loaded.open_project(path)
    assert loaded.project.access_points[0].position == Point2D(8.5, 6.5)


def test_d_rf_pipeline_uses_the_new_ap_position():
    session = _ready_session()
    ap = session.add_access_point(Point2D(1.0, 1.0))
    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=20)

    session.move_ap(ap.id, Point2D(9.0, 9.0))
    result = session.run_heatmap()

    # La distancia de cada evaluación se mide desde la posición NUEVA.
    farthest = max(result.evaluations, key=lambda e: e.distance_m)
    assert farthest.distance_m == pytest.approx(
        farthest.point.distance_to(Point2D(9.0, 9.0)), abs=1e-3
    )
    assert farthest.distance_m > 5.0  # ya no está en la esquina opuesta


# ===========================================================================
# E, F, G y H — la cobertura visual responde a posición, pared y banda
# ===========================================================================

def test_e_coverage_image_changes_when_the_ap_moves():
    session = _ready_session()
    ap = session.add_access_point(Point2D(1.0, 1.0))
    session.run_heatmap()
    before = _image(session)

    session.move_ap(ap.id, Point2D(9.0, 9.0))
    session.run_heatmap()
    after = _image(session)

    assert before.size == after.size
    assert before.tobytes() != after.tobytes()


def test_f_wall_between_ap_and_area_costs_signal():
    session = _ready_session()
    session.add_access_point(Point2D(1.0, 5.0))
    session.set_ap_rf_config(
        session.project.access_points[0].id,
        band_id="band_2_4", channel=6, width_mhz=20,
    )
    clear = _rx_avg(session)

    session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 10.0))
    blocked = _rx_avg(session)

    # La pérdida la pone el motor RF existente (F2/F8), no un adorno.
    assert blocked < clear


def test_g_moving_the_wall_changes_the_coverage_again():
    session = _ready_session()
    session.add_access_point(Point2D(1.0, 5.0))
    session.set_ap_rf_config(
        session.project.access_points[0].id,
        band_id="band_2_4", channel=6, width_mhz=20,
    )
    session.run_heatmap()
    clear = session.last_heatmap.stats["rx_avg_dbm"]

    wall = session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 10.0))
    blocked = _rx_avg(session)

    session.move_wall(wall.id, Point2D(4.0, 0.0))  # la aleja del AP
    farther = _rx_avg(session)

    assert blocked < clear       # la pared resta cobertura
    assert farther > blocked     # moverla libera cobertura otra vez
    assert session.heatmap_dirty is False  # la corrida recién calculada


def test_h_changing_the_band_recalculates_coverage():
    session = _ready_session()
    ap = session.add_access_point(Point2D(5.0, 5.0))
    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=20)
    session.run_heatmap()
    at_24 = session.last_heatmap
    image_24 = _image(session)

    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=40)
    session.set_band("band_5")
    session.run_heatmap()
    at_5 = session.last_heatmap
    image_5 = _image(session)

    assert at_24.band_id == "band_2_4"
    assert at_5.band_id == "band_5"  # el motor usó la banda nueva
    assert image_24.tobytes() != image_5.tobytes()


# ===========================================================================
# I — el overlay de cobertura no estorba la interacción
# ===========================================================================

def test_i_overlay_is_drawn_below_and_has_no_event_bindings():
    """La cobertura no captura ratón: los bindings viven en el widget."""
    source = CANVAS_SRC.read_text(encoding="utf-8")
    # Ningún binding a nivel de item de Canvas (tag_bind / item_bind).
    assert "tag_bind" not in source
    assert "item_bind" not in source
    # La imagen se rebaja siempre por debajo de las entidades.
    assert 'self.tag_lower("heatmap")' in source
    # El hit-test trabaja en coordenadas de MUNDO (viewport), no con ids
    # de Canvas: un item dibujado encima no puede "comer" el clic.
    assert "def _cursor_world(" in source
    assert "self.viewport.screen_to_world" in source
    assert "def _hit_test(" in source


def test_i_selection_and_drag_work_with_the_overlay_painted(tk_canvas):
    root, canvas, viewport, session, _changes = tk_canvas
    ap = session.add_access_point(Point2D(2.0, 5.0))
    session.run_heatmap()
    canvas.draw_heatmap(_image(session))
    canvas.render_project()
    root.update()
    assert canvas.find_withtag("heatmap"), "el overlay está pintado"

    # Clic encima de la imagen: la selección llega igual.
    x, y = viewport.world_to_screen(ap.position)
    canvas.event_generate("<ButtonPress-1>", x=int(x), y=int(y))
    root.update()
    assert session.selection is not None
    assert session.selection.entity_id == ap.id

    # Y el arrastre también, con la cobertura encima.
    _drag(canvas, root, viewport, ap.position, Point2D(7.0, 7.0))
    assert session.project.access_points[0].position != Point2D(2.0, 5.0)


def test_selected_ap_and_wall_are_visually_marked(tk_canvas):
    from ui.session import SelectionKind

    root, canvas, _viewport, session, _changes = tk_canvas
    session.add_access_point(Point2D(3.0, 3.0))
    session.add_wall(Point2D(0.0, 0.0), Point2D(6.0, 0.0))

    def count():
        canvas.render_project()
        root.update()
        return len(canvas.find_all())

    session.select(None, None)   # base sin selección (add_* deja selección)
    plain = count()
    session.select(SelectionKind.AP, "AP-001")
    with_ap = count()
    session.select(SelectionKind.WALL, "WALL-001")
    with_wall = count()
    session.select(None, None)
    deselected = count()

    assert with_ap > plain      # anillo de selección alrededor del AP
    assert with_wall > plain    # manijas en los extremos de la pared
    assert deselected == plain  # sin selección no queda nada residual
