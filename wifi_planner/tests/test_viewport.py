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
