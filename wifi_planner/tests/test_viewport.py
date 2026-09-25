"""Pruebas del Viewport (metros ↔ píxeles) — sin abrir Tk."""

import pytest

from core.geometry import Point2D
from ui.viewport import Viewport


def test_scale_is_isotropic():
    vp = Viewport(world_width_m=12.0, world_height_m=8.0,
                  canvas_width_px=800, canvas_height_px=600, margin_px=40)
    # Misma escala en X e Y por construcción (min de ambas)
    sx = (800 - 80) / 12.0
    sy = (600 - 80) / 8.0
    expected = min(sx, sy)
    assert vp.scale == pytest.approx(expected)
    # Verificación explícita: no hay escalado anisotrópico
    assert vp.scale > 0
    # Un metro desplaza lo mismo en X e Y
    p0 = vp.world_to_screen(Point2D(0, 0))
    p1 = vp.world_to_screen(Point2D(1, 0))
    p2 = vp.world_to_screen(Point2D(0, 1))
    dx = p1[0] - p0[0]
    dy = p2[1] - p0[1]
    assert dx == pytest.approx(dy)
    assert dx == pytest.approx(vp.scale)


def test_world_to_screen_maps_origin():
    vp = Viewport(world_width_m=12.0, world_height_m=8.0,
                  canvas_width_px=800, canvas_height_px=600, margin_px=40)
    sx, sy = vp.world_to_screen(Point2D(0.0, 0.0))
    assert sx == pytest.approx(vp.origin_x_px)
    assert sy == pytest.approx(vp.origin_y_px)


def test_round_trip_world_screen_world():
    vp = Viewport(world_width_m=12.0, world_height_m=8.0,
                  canvas_width_px=900, canvas_height_px=700, margin_px=30)
    original = Point2D(5.72, 3.41)
    sx, sy = vp.world_to_screen(original)
    back = vp.screen_to_world(sx, sy)
    assert back.x == pytest.approx(original.x, abs=1e-9)
    assert back.y == pytest.approx(original.y, abs=1e-9)


def test_round_trip_screen_world_screen():
    vp = Viewport(canvas_width_px=800, canvas_height_px=600)
    x_px, y_px = 123.456, 234.567
    world = vp.screen_to_world(x_px, y_px)
    sx, sy = vp.world_to_screen(world)
    assert sx == pytest.approx(x_px, abs=1e-6)
    assert sy == pytest.approx(y_px, abs=1e-6)


def test_floor_rect_has_world_aspect_ratio():
    vp = Viewport(world_width_m=12.0, world_height_m=8.0,
                  canvas_width_px=1000, canvas_height_px=1000, margin_px=20)
    x1, y1, x2, y2 = vp.floor_rect_px
    width_px = x2 - x1
    height_px = y2 - y1
    aspect_px = width_px / height_px
    aspect_m = 12.0 / 8.0
    assert aspect_px == pytest.approx(aspect_m, rel=1e-9)


def test_set_world_size_updates_scale():
    vp = Viewport(world_width_m=12.0, world_height_m=8.0,
                  canvas_width_px=800, canvas_height_px=600)
    scale_before = vp.scale
    vp.set_world_size(6.0, 4.0)
    assert vp.scale > scale_before  # mismo lienzo, espacio menor => más px/m


def test_set_world_size_rejects_invalid():
    vp = Viewport()
    with pytest.raises(ValueError):
        vp.set_world_size(0, 8)
    with pytest.raises(ValueError):
        vp.set_world_size(12, -1)


def test_constructor_rejects_invalid_world():
    with pytest.raises(ValueError):
        Viewport(world_width_m=0, world_height_m=8)
    with pytest.raises(ValueError):
        Viewport(world_width_m=12, world_height_m=0)


def test_set_canvas_size_rejects_invalid():
    vp = Viewport()
    with pytest.raises(ValueError):
        vp.set_canvas_size(0, 600)
    with pytest.raises(ValueError):
        vp.set_canvas_size(800, 0)


def test_world_to_screen_len_uses_same_scale():
    vp = Viewport(world_width_m=12.0, world_height_m=8.0,
                  canvas_width_px=800, canvas_height_px=600)
    assert vp.world_to_screen_len(2.0) == pytest.approx(2.0 * vp.scale)


def test_large_canvas_still_isotropic():
    vp = Viewport(world_width_m=12.0, world_height_m=8.0,
                  canvas_width_px=1600, canvas_height_px=400, margin_px=10)
    p0 = vp.world_to_screen(Point2D(0, 0))
    dx = vp.world_to_screen(Point2D(1, 0))[0] - p0[0]
    dy = vp.world_to_screen(Point2D(0, 1))[1] - p0[1]
    assert dx == pytest.approx(dy)
    assert dx == pytest.approx(vp.scale)


# ---------------------------------------------------------------------------
# Zoom / pan (Fase 14-E)
# ---------------------------------------------------------------------------

def _zoom_vp() -> Viewport:
    return Viewport(world_width_m=12.0, world_height_m=8.0,
                    canvas_width_px=800, canvas_height_px=600, margin_px=40)


def test_zoom_multiplies_scale():
    vp = _zoom_vp()
    base = vp.scale
    vp.zoom = 2.0
    assert vp.scale == pytest.approx(base * 2.0)


def test_zoom_at_keeps_world_point_under_cursor():
    vp = _zoom_vp()
    x_px, y_px = 321.0, 245.0
    world_before = vp.screen_to_world(x_px, y_px)
    vp.zoom_at(1.25, x_px, y_px)
    world_after = vp.screen_to_world(x_px, y_px)
    assert world_after.x == pytest.approx(world_before.x, abs=1e-9)
    assert world_after.y == pytest.approx(world_before.y, abs=1e-9)


def test_zoom_at_clamps_to_limits():
    from ui.viewport import MAX_ZOOM, MIN_ZOOM

    vp = _zoom_vp()
    vp.zoom_at(10.0 ** 9, 100.0, 100.0)
    assert vp.zoom == pytest.approx(MAX_ZOOM)
    vp.zoom_at(10.0 ** -9, 100.0, 100.0)
    assert vp.zoom == pytest.approx(MIN_ZOOM)


def test_zoom_at_rejects_invalid_factor():
    vp = _zoom_vp()
    for bad in (0.0, -1.5, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            vp.zoom_at(bad, 10.0, 10.0)


def test_constructor_rejects_invalid_zoom():
    with pytest.raises(ValueError):
        Viewport(zoom=0.0)
    with pytest.raises(ValueError):
        Viewport(zoom=float("nan"))


def test_pan_by_shifts_origins():
    vp = _zoom_vp()
    ox, oy = vp.origin_x_px, vp.origin_y_px
    vp.pan_by(25.0, -10.0)
    assert vp.origin_x_px == pytest.approx(ox + 25.0)
    assert vp.origin_y_px == pytest.approx(oy - 10.0)


def test_pan_rejects_non_finite():
    vp = _zoom_vp()
    with pytest.raises(ValueError):
        vp.pan_by(float("nan"), 0.0)
    with pytest.raises(ValueError):
        vp.pan_by(0.0, float("inf"))


def test_reset_view_restores_fit():
    vp = _zoom_vp()
    base_scale = vp.scale
    vp.zoom_at(3.0, 400.0, 300.0)
    vp.pan_by(50.0, 40.0)
    vp.reset_view()
    assert vp.zoom == pytest.approx(1.0)
    assert vp.pan_x_px == pytest.approx(0.0)
    assert vp.pan_y_px == pytest.approx(0.0)
    assert vp.scale == pytest.approx(base_scale)


def test_round_trip_still_holds_after_zoom_and_pan():
    vp = _zoom_vp()
    vp.zoom_at(1.6, 200.0, 150.0)
    vp.pan_by(-30.0, 20.0)
    original = Point2D(7.25, 2.5)
    sx, sy = vp.world_to_screen(original)
    back = vp.screen_to_world(sx, sy)
    assert back.x == pytest.approx(original.x, abs=1e-9)
    assert back.y == pytest.approx(original.y, abs=1e-9)
