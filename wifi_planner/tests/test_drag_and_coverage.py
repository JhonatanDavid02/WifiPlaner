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
APP_SRC = Path(__file__).resolve().parents[1] / "ui" / "app.py"


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
    # La imagen se coloca justo por encima del piso (tag "floor"): ni
    # debajo (quedaría tapada por el relleno opaco) ni encima de las
    # entidades.
    assert 'self.tag_raise("heatmap", "floor")' in source
    assert 'tags=("floor",)' in source
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


# ===========================================================================
# Regresión: la cobertura y la rejilla no pueden quedar tapadas por el
# relleno opaco del rect del piso (z-order del lienzo).
# ===========================================================================

def test_heatmap_is_above_the_floor_and_below_entities(tk_canvas):
    root, canvas, _viewport, session, _changes = tk_canvas
    session.add_access_point(Point2D(2.5, 2.5))
    session.set_grid_resolution(0.5)
    session.run_heatmap()
    canvas.draw_heatmap(_image(session))
    canvas.render_project()
    root.update()

    items = canvas.find_all()  # índice 0 = capa inferior
    floor = canvas.find_withtag("floor")
    heat = canvas.find_withtag("heatmap")
    assert floor, "el rect del piso debe estar etiquetado como 'floor'"
    assert heat, "la imagen de cobertura debe estar en el lienzo"

    i_floor = items.index(floor[0])
    i_heat = items.index(heat[0])

    # 1) Por ENCIMA del piso: si no, el relleno opaco la tapa entera.
    assert i_heat > i_floor, "la cobertura queda debajo del rect del piso"

    # 2) Por DEBAJO de las entidades: el AP (óvalos) se pinta después.
    ovals = [it for it in items if canvas.type(it) == "oval"]
    assert ovals, "el AP debe estar dibujado"
    assert min(items.index(o) for o in ovals) > i_heat, (
        "la cobertura no debe tapar las entidades"
    )


def test_grid_lines_are_above_the_floor_fill(tk_canvas):
    root, canvas, _viewport, session, _changes = tk_canvas
    # Plano vacío: los únicos items tipo "line" son las líneas de rejilla.
    canvas.render_project()
    root.update()

    items = canvas.find_all()
    floor = canvas.find_withtag("floor")
    assert floor
    i_floor = items.index(floor[0])

    lines = [it for it in items if canvas.type(it) == "line"]
    assert lines, "debería haber líneas de rejilla dibujadas"
    assert min(items.index(line) for line in lines) > i_floor, (
        "la rejilla queda debajo del relleno opaco del piso"
    )

# ===========================================================================
# Fase 15.1: capa de resaltado del AP seleccionado.
# El heatmap de fondo NO cambia ni se recalcula por seleccionar.
# ===========================================================================

def test_selected_ap_coverage_leaves_the_background_untouched():
    from ui.session import SelectionKind

    session = _ready_session()
    ap1 = session.add_access_point(Point2D(1.0, 5.0))
    session.add_access_point(Point2D(9.0, 5.0))
    session.run_heatmap()                      # fondo combinado
    background_result = session.last_heatmap
    background_scope = session.heatmap_ap_id
    background_pixels = _image(session).tobytes()

    session.select(SelectionKind.AP, ap1.id)
    coverage = session.selected_ap_coverage()

    assert coverage is not None
    # El fondo ni se sustituye ni cambia de ámbito.
    assert session.last_heatmap is background_result
    assert session.heatmap_ap_id == background_scope
    # Seleccionar NO invalida el heatmap: nada lo recalcula ni lo pinta
    # otra vez (el fondo es pasivo) y sus píxeles son los mismos.
    assert session.heatmap_dirty is False
    assert _image(session).tobytes() == background_pixels
    # Y los valores son los RSSI de ESE AP (distancias desde su posición).
    assert coverage.evaluations
    for ev in coverage.evaluations:
        assert ev.access_point_id == ap1.id
        assert ev.distance_m == pytest.approx(
            ev.point.distance_to(ap1.position), abs=1e-3
        )


def test_selected_ap_coverage_switches_between_aps():
    from ui.session import SelectionKind

    session = _ready_session()
    ap1 = session.add_access_point(Point2D(1.0, 5.0))
    ap2 = session.add_access_point(Point2D(9.0, 5.0))

    session.select(SelectionKind.AP, ap1.id)
    first = session.selected_ap_coverage()
    session.select(SelectionKind.AP, ap2.id)
    second = session.selected_ap_coverage()

    assert first is not None and second is not None
    assert first is not second
    assert first.evaluations != second.evaluations  # cambia el resaltado
    assert second.evaluations[0].access_point_id == ap2.id


def test_selected_ap_coverage_is_none_without_an_ap_selected():
    session = _ready_session()
    session.add_access_point(Point2D(1.0, 5.0))
    session.run_heatmap()
    background = session.last_heatmap

    session.select(None, None)

    assert session.selected_ap_coverage() is None
    assert session.last_heatmap is background  # el fondo sigue ahí


def test_selected_ap_coverage_follows_walls_and_band():
    from ui.session import SelectionKind

    session = _ready_session()
    ap = session.add_access_point(Point2D(1.0, 5.0))
    session.select(SelectionKind.AP, ap.id)
    clear = session.selected_ap_coverage()

    wall = session.add_wall(Point2D(6.0, 0.0), Point2D(6.0, 10.0))
    session.set_wall_material(wall.id, "concrete")
    # add_wall selecciona la pared: volvemos al AP para ver SU resaltado.
    session.select(SelectionKind.AP, ap.id)
    blocked = session.selected_ap_coverage()
    assert blocked is not None

    # La forma cambia: los puntos detrás de la pared pierden RSSI.
    behind = next(e for e in blocked.evaluations if e.point.x == 10.0)
    same_point = next(e for e in clear.evaluations if e.point == behind.point)
    assert behind.rx_power_dbm < same_point.rx_power_dbm

    # Cambio de banda: el resaltado usa la banda del AP (F10).
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=40)
    session.set_band("band_5")
    at_five = session.selected_ap_coverage()
    assert at_five.band_id == "band_5"
    assert at_five.evaluations[0].rx_power_dbm != same_point.rx_power_dbm


def test_ap_coverage_layer_is_separate_from_the_background(tk_canvas):
    from ui.session import SelectionKind

    root, canvas, _viewport, session, _changes = tk_canvas
    ap = session.add_access_point(Point2D(2.5, 2.5))
    session.select(SelectionKind.AP, ap.id)
    session.run_heatmap()

    background = _image(session)
    canvas.draw_heatmap(background)              # fondo
    canvas.draw_ap_coverage(_image(session))     # resaltado (capa aparte)
    canvas.render_project()
    root.update()

    assert canvas._heatmap_image is background   # el fondo no se sustituye
    items = canvas.find_all()
    i_floor = items.index(canvas.find_withtag("floor")[0])
    i_bg = items.index(canvas.find_withtag("heatmap")[0])
    i_hi = items.index(canvas.find_withtag("ap_coverage")[0])
    assert i_floor < i_bg < i_hi                 # piso < fondo < resaltado
    ovals = [it for it in items if canvas.type(it) == "oval"]
    assert min(items.index(o) for o in ovals) > i_hi  # el AP por encima

    # Quitar el resaltado no toca el fondo.
    canvas.clear_ap_coverage()
    canvas.render_project()
    root.update()
    assert canvas.find_withtag("ap_coverage") == ()
    assert canvas._heatmap_image is background


def test_app_does_not_rescope_the_background_on_selection():
    source = APP_SRC.read_text(encoding="utf-8")
    # El ámbito «AP:» del fondo ya no se sincroniza con la selección
    # (ese método de la Fase 15 se retiró).
    assert "_sync_heatmap_ap_with_selection" not in source
    assert "_last_selection_key" not in source
    # Solo se refresca la capa de resaltado cuando el fondo no cambió.
    assert "background=background_changed" in source
    assert "selected_ap_coverage()" in source
    # Flujo de render: cada refresco reconstruye la capa con los RSSI
    # actuales (selección, cambio de banda o de potencia).
    assert "def _refresh_ap_coverage" in source
    assert "self._refresh_ap_coverage()" in source


def test_coverage_zone_is_painted_only_where_the_rfi_reports_signal():
    """SELECTED_AP_COVERAGE: el color lo dicta el RSSI del motor.

    Con 6 paredes de ladrillo una parte del plano cae por debajo de
    ``weak_min_dbm``: esas celdas se pintan en **gris claro** (sin
    señal) y las que tienen señal con su banda de calidad. La forma de
    la zona sale de los RSSI del motor, no de un radio inventado.
    """
    from ui.app import (
        AP_COVERAGE_NO_SIGNAL_RGB,
        AP_COVERAGE_NO_SIGNAL_ALPHA,
        build_ap_coverage_overlay,
    )
    from ui.session import SelectionKind

    session = make_session()
    session.set_floor_dimensions(60.0, 40.0)
    session.set_grid_resolution(1.0)
    ap = session.add_access_point(Point2D(2.0, 2.0))
    for index in range(6):
        x = 60.0 * (index + 1) / 7.0
        wall = session.add_wall(Point2D(x, 0.0), Point2D(x, 40.0))
        session.set_wall_material(wall.id, "brick")
    session.select(SelectionKind.AP, ap.id)

    thresholds = session.project.thresholds
    result = session.selected_ap_coverage()
    viewport = Viewport(
        world_width_m=60.0,
        world_height_m=40.0,
        canvas_width_px=600,
        canvas_height_px=400,
    )
    overlay = build_ap_coverage_overlay(result, viewport, thresholds, 1.0)
    assert overlay is not None
    pixels = overlay.load()
    width, height = overlay.size
    x1f, y1f, _, _ = viewport.floor_rect_px

    def pixel_at(point):
        sx, sy = viewport.world_to_screen(point)
        x = int(round(sx - x1f))
        y = int(round(sy - y1f))
        return pixels[min(max(x, 0), width - 1), min(max(y, 0), height - 1)]

    outside = [
        ev for ev in result.evaluations
        if ev.rx_power_dbm < thresholds.weak_min_dbm
    ]
    strong = [
        ev for ev in result.evaluations
        if ev.rx_power_dbm >= thresholds.excellent_min_dbm
    ]
    assert outside, "el escenario necesita celdas sin cobertura"
    assert strong, "el escenario necesita celdas excelentes"

    # Sin señal (RSSI < débil): gris claro, nunca el color de una banda.
    for evaluation in outside[::7]:
        r, g, b, a = pixel_at(evaluation.point)
        assert (r, g, b) == AP_COVERAGE_NO_SIGNAL_RGB
        assert a > 0
    # Señal excelente: color de banda (verde), NUNCA gris.
    for evaluation in strong[::7]:
        r, g, b, a = pixel_at(evaluation.point)
        assert (r, g, b) != AP_COVERAGE_NO_SIGNAL_RGB
        assert a > 0
    assert AP_COVERAGE_NO_SIGNAL_ALPHA > 0

    # La zona se marca junto al AP y deja ver el heatmap de fondo lejos.
    from ui.app import AP_COVERAGE_ALPHA_MIN, AP_COVERAGE_ALPHA_MAX
    assert 40 <= AP_COVERAGE_ALPHA_MIN <= 110      # bordes: fondo visible
    assert 140 <= AP_COVERAGE_ALPHA_MAX <= 200     # junto al AP: marcado
    assert AP_COVERAGE_ALPHA_MIN < AP_COVERAGE_ALPHA_MAX


def test_overlay_is_built_from_the_coverage_grid_rssi_of_the_ap():
    """2.4 GHz → 5 GHz → 2.4 GHz: los RSSI del grid mandan en el overlay.

    Prueba fundamental: si los RSSI cambian, el overlay cambia; si los
    RSSI vuelven a ser los mismos, el overlay vuelve a ser el mismo. No
    hay radio, distancia ni forma predeterminada.
    """
    from ui.app import build_ap_coverage_overlay
    from ui.session import SelectionKind

    session = _ready_session()
    ap = session.add_access_point(Point2D(2.5, 2.5))
    session.select(SelectionKind.AP, ap.id)
    viewport = Viewport(
        world_width_m=session.floor_width_m,
        world_height_m=session.floor_height_m,
        canvas_width_px=400,
        canvas_height_px=400,
    )

    def snapshot():
        result = session.selected_ap_coverage()
        overlay = build_ap_coverage_overlay(
            result,
            viewport,
            session.project.thresholds,
            session.grid_resolution_m,
        )
        rssi = [round(ev.rx_power_dbm, 4) for ev in result.evaluations]
        return result.band_id, rssi, overlay.tobytes()

    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=20)
    at_24_first = snapshot()

    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=40)
    at_5 = snapshot()

    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=20)
    at_24_again = snapshot()

    # Cada banda usa SU simulación: los RSSI del CoverageGrid cambian.
    assert at_24_first[0] == "band_2_4"
    assert at_5[0] == "band_5"
    assert at_24_first[1] != at_5[1]

    # El overlay se construye con esos RSSI: cambia cuando cambian.
    assert at_24_first[2] != at_5[2]

    # Volviendo a 2.4 GHz, los RSSI y el overlay vuelven a ser idénticos
    # (determinista: no queda estado de la banda anterior).
    assert at_24_again[1] == at_24_first[1]
    assert at_24_again[2] == at_24_first[2]

    # El overlay es una función de los evaluations: otro AP ⇒ otra forma.
    other = session.add_access_point(Point2D(9.0, 9.0))
    session.select(SelectionKind.AP, other.id)
    at_other = snapshot()
    assert at_other[2] != at_24_first[2]


def test_selecting_an_ap_only_adds_the_coverage_layer(tk_canvas):
    """Click en AP → aparece SU zona; el fondo (píxel a píxel) no cambia."""
    from ui.app import build_ap_coverage_overlay
    from ui.session import SelectionKind

    root, canvas, viewport, session, _changes = tk_canvas
    ap1 = session.add_access_point(Point2D(2.5, 2.5))
    ap2 = session.add_access_point(Point2D(7.5, 7.5))
    session.run_heatmap()
    canvas.draw_heatmap(_image(session))
    canvas.render_project()
    root.update()
    background_pixels = canvas._heatmap_image.tobytes()
    background_image = canvas._heatmap_image
    background_dirty = session.heatmap_dirty

    def select(ap):
        session.select(SelectionKind.AP, ap.id)
        overlay = build_ap_coverage_overlay(
            session.selected_ap_coverage(),
            viewport,
            session.project.thresholds,
            session.grid_resolution_m,
        )
        assert overlay is not None
        canvas.draw_ap_coverage(overlay)
        root.update()
        # El fondo sigue intacto: mismo objeto y mismos píxeles.
        assert canvas._heatmap_image is background_image
        assert canvas._heatmap_image.tobytes() == background_pixels
        assert session.heatmap_dirty is background_dirty
        return overlay

    first = select(ap1)
    assert canvas.find_withtag("ap_coverage")

    # Click AP-002: cambia la zona, el fondo no.
    second = select(ap2)
    assert second.tobytes() != first.tobytes()

    # Click fuera: la zona desaparece, el fondo sigue intacto.
    session.select(None, None)
    canvas.clear_ap_coverage()
    root.update()
    assert canvas.find_withtag("ap_coverage") == ()
    assert canvas._heatmap_image.tobytes() == background_pixels


def test_left_drag_on_empty_space_pans_the_view(tk_canvas):
    """Arrastrar con el botón izquierdo sobre el vacío desplaza el plano.

    En planos grandes (100×100) moverse solo con zoom es incómodo: el
    gesto es «press en espacio libre → mover → release». Ni se crean ni
    se mueven objetos, y la selección sigue vacía.
    """
    root, canvas, viewport, session, _changes = tk_canvas

    before = (viewport.pan_x_px, viewport.pan_y_px)
    zoom_before = viewport.zoom
    objects_before = (
        len(session.project.access_points),
        len(session.floor.walls),
    )

    # Espacio libre (9,9): no hay objetos en la sesión del fixture.
    x, y = viewport.world_to_screen(Point2D(9.0, 9.0))
    canvas.event_generate("<ButtonPress-1>", x=int(x), y=int(y))
    root.update()
    for step in (1, 2, 3):
        canvas.event_generate("<Motion>", x=int(x - 12 * step),
                              y=int(y - 8 * step))
        root.update()
    # Tk entrega <B1-Motion> al arrastrar con el botón izquierdo: el pan
    # también tiene que responder a ese tipo de evento.
    canvas.event_generate("<B1-Motion>", x=int(x - 36), y=int(y - 24))
    root.update()
    canvas.event_generate("<ButtonRelease-1>", x=int(x - 36), y=int(y - 24))
    root.update()

    after = (viewport.pan_x_px, viewport.pan_y_px)
    assert after != before, "el arrastre sobre el vacío debe desplazar la vista"
    assert after[0] == before[0] - 36 and after[1] == before[1] - 24
    # No es zoom: la escala no cambia.
    assert viewport.zoom == zoom_before
    # Ni efectos en el modelo.
    assert objects_before == (
        len(session.project.access_points),
        len(session.floor.walls),
    )
    assert session.selection is None
