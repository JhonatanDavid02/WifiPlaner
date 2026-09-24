"""Pruebas de intersección trayecto ↔ pared (Fase 2, Tests 1–10)."""

import pytest

from core.geometry import EPSILON_GEOMETRY, Point2D, Segment2D
from core.material import default_materials
from core.wall import Wall
from engine.intersection import (
    crossing_distance_from_start,
    crossing_point,
    segment_crossing_parameters,
    segments_cross,
)
from engine.obstacles import trace_walls


def _wall(wall_id: str, start: Point2D, end: Point2D, material=None) -> Wall:
    drywall = material or next(m for m in default_materials() if m.id == "drywall")
    return Wall(id=wall_id, segment=Segment2D(start, end), material=drywall)


def _path(x0, y0, x1, y1) -> Segment2D:
    return Segment2D(Point2D(x0, y0), Point2D(x1, y1))


# ---------------------------------------------------------------------------
# Test 1 — Segmento que cruza una pared
# ---------------------------------------------------------------------------

def test_crosses_vertical_wall():
    path = _path(0, 0, 10, 0)
    wall = _wall("w1", Point2D(5, -5), Point2D(5, 5))
    assert segments_cross(path, wall.segment) is True
    params = segment_crossing_parameters(path, wall.segment)
    assert params is not None
    t, u = params
    assert t == pytest.approx(0.5)
    assert u == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test 2 — Segmento que no cruza una pared
# ---------------------------------------------------------------------------

def test_does_not_cross_disjoint_wall():
    path = _path(0, 0, 10, 0)
    wall = _wall("w1", Point2D(5, 5), Point2D(5, 10))  # por encima del trayecto
    assert segments_cross(path, wall.segment) is False
    assert segment_crossing_parameters(path, wall.segment) is None


# ---------------------------------------------------------------------------
# Test 3 — Segmentos paralelos
# ---------------------------------------------------------------------------

def test_parallel_segments_do_not_cross():
    path = _path(0, 0, 10, 0)
    wall = _wall("w1", Point2D(0, 5), Point2D(10, 5))
    assert segments_cross(path, wall.segment) is False

    # Paralelo vertical-vertical
    path_v = _path(0, 0, 0, 10)
    wall_v = _wall("wv", Point2D(5, 0), Point2D(5, 10))
    assert segments_cross(path_v, wall_v.segment) is False

    # Colineales (mismo eje y=0, solape)
    wall_col = _wall("wcol", Point2D(2, 0), Point2D(8, 0))
    assert segments_cross(path, wall_col.segment) is False


# ---------------------------------------------------------------------------
# Test 4 — Cruce vertical/horizontal
# ---------------------------------------------------------------------------

def test_cross_vertical_horizontal():
    path = _path(0, 0, 0, 10)  # vertical
    wall = _wall("w1", Point2D(-5, 5), Point2D(5, 5))  # horizontal
    assert segments_cross(path, wall.segment) is True
    point = crossing_point(path, wall.segment)
    assert point is not None
    assert point.x == pytest.approx(0.0)
    assert point.y == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Test 5 — Cruce diagonal
# ---------------------------------------------------------------------------

def test_cross_diagonal():
    path = _path(0, 0, 10, 10)
    wall = _wall("w1", Point2D(0, 10), Point2D(10, 0))
    assert segments_cross(path, wall.segment) is True
    point = crossing_point(path, wall.segment)
    assert point.x == pytest.approx(5.0)
    assert point.y == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Test 6 — Trayectoria tocando exactamente un extremo de la pared
# ---------------------------------------------------------------------------

def test_touching_wall_endpoint_does_not_count():
    # Extremo de la pared sobre el camino (u = 0 en la pared)
    path = _path(0, 0, 10, 0)
    wall = _wall("w1", Point2D(5, 0), Point2D(5, 5))  # cuelga desde el camino
    assert segments_cross(path, wall.segment) is False

    # Extremo operto de la pared
    wall2 = _wall("w2", Point2D(5, -5), Point2D(5, 0))
    assert segments_cross(path, wall2.segment) is False

    # Destino del trayecto exactamente sobre la pared (t = 1)
    path_to_wall = _path(0, 0, 5, 0)
    wall3 = _wall("w3", Point2D(5, -5), Point2D(5, 5))
    assert segments_cross(path_to_wall, wall3.segment) is False


# ---------------------------------------------------------------------------
# Test 7 — Dos paredes atravesadas
# ---------------------------------------------------------------------------

def test_two_walls_crossed_in_order():
    drywall = next(m for m in default_materials() if m.id == "drywall")
    concrete = next(m for m in default_materials() if m.id == "concrete")
    walls = [
        _wall("w_far", Point2D(7, -5), Point2D(7, 5), concrete),
        _wall("w_near", Point2D(3, -5), Point2D(3, 5), drywall),
    ]
    trace = trace_walls(Point2D(0, 0), Point2D(10, 0), walls, "band_2_4")
    assert trace.crossings_count == 2
    # Orden por distancia desde el origen: primero la de x=3, luego x=7
    assert trace.wall_ids == ("w_near", "w_far")
    assert trace.walls_crossed[0].distance_from_source_m == pytest.approx(3.0)
    assert trace.walls_crossed[1].distance_from_source_m == pytest.approx(7.0)
    # drywall 3 + concrete 12 = 15 dB (espesor por defecto)
    assert trace.attenuation_db == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Test 8 — Esquina: dos paredes sin doble conteo incorrecto
# ---------------------------------------------------------------------------

def test_corner_shared_endpoint_not_double_counted():
    """Paredes en L que comparten la esquina (5,5).

    Un trayecto que pasa exactamente por la esquina toca un extremo de
    cada pared => 0 cruces (convención: extremos no cuentan).
    Un trayecto que cruza el interior de ambas => 2 cruces.
    Un trayecto que cruza solo una => 1 cruce.
    """
    drywall = next(m for m in default_materials() if m.id == "drywall")
    wall_h = _wall("wh", Point2D(0, 5), Point2D(5, 5), drywall)
    wall_v = _wall("wv", Point2D(5, 0), Point2D(5, 5), drywall)

    # (a) Pasa exactamente por la esquina compartida => sin doble conteo
    trace_corner = trace_walls(
        Point2D(0, 0), Point2D(10, 10), [wall_h, wall_v], "band_2_4"
    )
    assert trace_corner.crossings_count == 0
    assert trace_corner.attenuation_db == 0.0

    # (b) Cruza el interior de ambas paredes de la L
    # Desde (1, 6) hasta (6, 1): cruza wh en y=5 y wv en x=5
    trace_both = trace_walls(
        Point2D(1, 6), Point2D(6, 1), [wall_h, wall_v], "band_2_4"
    )
    assert trace_both.crossings_count == 2
    assert trace_both.attenuation_db == pytest.approx(6.0)  # 3 + 3

    # (c) Cruza solo la horizontal
    trace_one = trace_walls(
        Point2D(1, 0), Point2D(1, 10), [wall_h, wall_v], "band_2_4"
    )
    assert trace_one.crossings_count == 1
    assert trace_one.wall_ids == ("wh",)


# ---------------------------------------------------------------------------
# Test 9 — AP o punto exactamente sobre una pared
# ---------------------------------------------------------------------------

def test_source_or_target_on_wall_does_not_count():
    drywall = next(m for m in default_materials() if m.id == "drywall")
    wall = _wall("w1", Point2D(0, 0), Point2D(10, 0), drywall)

    # AP sobre la pared: sale desde un extremo de la pared
    trace_from_wall = trace_walls(
        Point2D(5, 0), Point2D(5, 10), [wall], "band_2_4"
    )
    assert trace_from_wall.crossings_count == 0

    # Punto de evaluación sobre la pared
    trace_to_wall = trace_walls(
        Point2D(5, 10), Point2D(5, 0), [wall], "band_2_4"
    )
    assert trace_to_wall.crossings_count == 0

    # AP en un extremo del segmento pared
    trace_from_endpoint = trace_walls(
        Point2D(0, 0), Point2D(0, 10), [wall], "band_2_4"
    )
    assert trace_from_endpoint.crossings_count == 0


# ---------------------------------------------------------------------------
# Test 10 — Tolerancia numérica / floats cerca del límite
# ---------------------------------------------------------------------------

def test_epsilon_near_endpoint_treated_as_endpoint():
    path = _path(0, 0, 5, 0)
    # Pared en x=5 exacto: el destino toca la pared (t ≈ 1) => no cuenta
    wall_exact = _wall("w_exact", Point2D(5, -1), Point2D(5, 1))
    assert segments_cross(path, wall_exact.segment) is False

    # Destino con ruido within EPSILON de la pared: sigue tratándose como extremo
    noisy_end = 5.0 + EPSILON_GEOMETRY / 10.0
    path_noisy = _path(0, 0, noisy_end, 0)
    assert segments_cross(path_noisy, wall_exact.segment) is False

    # Cruce claramente interior con ruido de float => sí cuenta
    path_clear = _path(0, 0, 10, 0)
    wall_shifted = _wall(
        "w_shift", Point2D(5.0 + 1e-6, -1), Point2D(5.0 + 1e-6, 1)
    )
    assert segments_cross(path_clear, wall_shifted.segment) is True


def test_epsilon_parallel_within_tolerance():
    path = _path(0, 0, 10, 0)
    # Desplazamiento paralelo mucho menor que EPSILON => se trata como colineal/paralelo
    wall = _wall("w_col", Point2D(0, EPSILON_GEOMETRY / 10), Point2D(10, EPSILON_GEOMETRY / 10))
    # Denominador ≈ 0 (paralelo) => None siempre
    assert segments_cross(path, wall.segment) is False


def test_crossing_distance_returns_metric_distance():
    path = _path(0, 0, 10, 0)
    wall = _wall("w1", Point2D(4, -5), Point2D(4, 5))
    dist = crossing_distance_from_start(path, wall.segment)
    assert dist == pytest.approx(4.0)


def test_no_crossing_distance_is_none():
    path = _path(0, 0, 10, 0)
    wall = _wall("w1", Point2D(4, 5), Point2D(4, 10))
    assert crossing_distance_from_start(path, wall.segment) is None


def test_trace_empty_walls():
    trace = trace_walls(Point2D(0, 0), Point2D(5, 0), [], "band_2_4")
    assert trace.crossings_count == 0
    assert trace.attenuation_db == 0.0
    assert trace.walls_crossed == ()


def test_blocks_signal_false_walls_ignored():
    drywall = next(m for m in default_materials() if m.id == "drywall")
    decorative = Wall(
        id="deco",
        segment=Segment2D(Point2D(5, -5), Point2D(5, 5)),
        material=drywall,
        blocks_signal=False,
    )
    trace = trace_walls(Point2D(0, 0), Point2D(10, 0), [decorative], "band_2_4")
    assert trace.crossings_count == 0
    assert trace.attenuation_db == 0.0
