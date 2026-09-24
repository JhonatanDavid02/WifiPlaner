"""Pruebas de Fase 8: espacios (spaces) y aperturas (openings).

Cobertura:

- Dominio: ``Opening`` (validación, límites BK), ``Space``,
  ``wall_point_at_offset`` / ``opening_segment`` / ``group_openings_by_wall``.
- Geometría de cruce (20 casos): semántica de reemplazo (decisión BG),
  intervalo cerrado, unión de huecos, orden canónico, 6 GHz, espurios.
- Sesión: CRUD, clamps, invalidación (BH: espacios no invalidan; los
  openings sí), cascada pared → openings, passthrough a simulate_coverage.
- Persistencia: round-trip, claves opcionales, validación estricta.
- Integración: ``simulate_coverage`` con openings (pérdida 0 dB en hueco).
"""

from __future__ import annotations

import json

import pytest

from core.access_point import AccessPoint
from core.band import DEFAULT_BANDS
from core.geometry import EPSILON_GEOMETRY, Point2D, Rect, Segment2D
from core.material import MaterialAttenuationError, default_materials
from core.project import Project
from core.radio import RadioConfiguration
from core.space import MIN_SPACE_SIZE_M, Space
from core.wall import (
    DEFAULT_OPENING_LENGTH_M,
    MAX_OPENING_ATTENUATION_DB,
    MAX_OPENING_LENGTH_M,
    MIN_OPENING_LENGTH_M,
    OPENING_KINDS,
    Opening,
    Wall,
    group_openings_by_wall,
    opening_segment,
    wall_point_at_offset,
)
from engine.obstacles import trace_to_obstacle_loss, trace_walls
from engine.simulator import simulate_coverage
from persistence import (
    SCHEMA_VERSION,
    ProjectFormatError,
    document_from_dict,
    document_to_dict,
    load_project,
    project_from_dict,
    project_to_dict,
    save_project,
)
from ui.session import EditorSession, SelectionKind, Tool

# ---------------------------------------------------------------------------
# Utilidades de dominio
# ---------------------------------------------------------------------------

BAND_24 = "band_2_4"
BAND_5 = "band_5"
BAND_6 = "band_6"


def _material(material_id: str = "drywall"):
    return next(m for m in default_materials() if m.id == material_id)


def _wall(
    wall_id: str = "W-001",
    start=(5.0, 0.0),
    end=(5.0, 10.0),
    material: str = "drywall",
    blocks_signal: bool = True,
) -> Wall:
    """Pared vertical por defecto: (5,0)→(5,10); un trayecto horizontal
    (0,y)→(10,y) cruza a distancia y desde el inicio de la pared."""
    return Wall(
        id=wall_id,
        segment=Segment2D(Point2D(*start), Point2D(*end)),
        material=_material(material),
        blocks_signal=blocks_signal,
    )


def _opening(
    opening_id: str = "O-001",
    wall_id: str = "W-001",
    start: float = 4.0,
    end: float = 6.0,
    kind: str = "door",
    overrides: dict | None = None,
) -> Opening:
    return Opening(
        id=opening_id,
        wall_id=wall_id,
        start_offset_m=start,
        end_offset_m=end,
        kind=kind,
        attenuation_override_db=overrides if overrides is not None else {},
    )


def _path(y: float) -> tuple[Point2D, Point2D]:
    return Point2D(0.0, y), Point2D(10.0, y)


def _trace(y: float, openings=(), walls=None, band_id: str = BAND_24):
    source, target = _path(y)
    return trace_walls(
        source,
        target,
        walls if walls is not None else [_wall()],
        band_id,
        openings=openings,
    )


# ===========================================================================
# A. Dominio: Opening (validación y constantes)
# ===========================================================================

def test_opening_kind_and_constants():
    assert OPENING_KINDS == ("door", "window", "pass_through")
    assert MIN_OPENING_LENGTH_M == 0.01
    assert MAX_OPENING_LENGTH_M == 1000.0
    assert MAX_OPENING_ATTENUATION_DB == 200.0
    assert DEFAULT_OPENING_LENGTH_M == {
        "door": 0.9,
        "window": 1.2,
        "pass_through": 1.0,
    }


def test_opening_valid_defaults_and_length():
    opening = _opening()
    assert opening.kind == "door"
    assert opening.attenuation_override_db == {}
    assert opening.length_m == pytest.approx(2.0)


def test_opening_rejects_bad_kind():
    with pytest.raises(ValueError):
        _opening(kind="arch")


def test_opening_rejects_negative_start():
    with pytest.raises(ValueError):
        _opening(start=-0.5, end=1.0)


def test_opening_rejects_too_short():
    with pytest.raises(ValueError):
        _opening(start=1.0, end=1.0 + MIN_OPENING_LENGTH_M / 2)


def test_opening_rejects_too_long():
    with pytest.raises(ValueError):
        _opening(start=0.0, end=MAX_OPENING_LENGTH_M + 1.0)


def test_opening_rejects_non_finite_and_bool():
    with pytest.raises(ValueError):
        _opening(start=float("nan"), end=2.0)
    with pytest.raises(ValueError):
        _opening(start=0.0, end=float("inf"))
    with pytest.raises(ValueError):
        Opening(
            id="O-bool",
            wall_id="W-001",
            start_offset_m=True,  # bool no es un número válido
            end_offset_m=1.0,
        )


def test_opening_rejects_bad_override_values():
    with pytest.raises(ValueError):
        _opening(overrides={BAND_24: -1.0})
    with pytest.raises(ValueError):
        _opening(overrides={BAND_24: MAX_OPENING_ATTENUATION_DB + 1.0})
    with pytest.raises(ValueError):
        _opening(overrides={BAND_24: float("nan")})
    with pytest.raises(ValueError):
        Opening(
            id="O-x",
            wall_id="W-001",
            start_offset_m=0.0,
            end_offset_m=1.0,
            attenuation_override_db="nope",
        )


def test_opening_rejects_empty_ids():
    with pytest.raises(ValueError):
        _opening(opening_id="  ")
    with pytest.raises(ValueError):
        _opening(wall_id="")


def test_space_domain_min_size_constant():
    assert MIN_SPACE_SIZE_M == 0.1
    space = Space(id="S-001", name="Sala", rect=Rect(x=0, y=0, width=3, height=2))
    assert space.area == pytest.approx(6.0)
    assert space.function == ""


# ===========================================================================
# B. Geometría: wall_point_at_offset / opening_segment / agrupación
# ===========================================================================

def test_wall_point_at_offset_clamps_and_endpoints():
    wall = _wall()
    start = wall_point_at_offset(wall, 0.0)
    assert (start.x, start.y) == pytest.approx((5.0, 0.0))
    mid = wall_point_at_offset(wall, 5.0)
    assert (mid.x, mid.y) == pytest.approx((5.0, 5.0))
    beyond = wall_point_at_offset(wall, 99.0)
    assert (beyond.x, beyond.y) == pytest.approx((5.0, 10.0))


def test_wall_point_at_offset_rejects_degenerate_wall():
    degenerate = Wall(
        id="W-deg",
        segment=Segment2D(Point2D(1, 1), Point2D(1, 1)),
        material=_material(),
    )
    with pytest.raises(ValueError):
        wall_point_at_offset(degenerate, 0.5)


def test_opening_segment_derives_world_geometry():
    wall = _wall()
    segment = opening_segment(wall, _opening(start=2.0, end=4.0))
    assert (segment.start.x, segment.start.y) == pytest.approx((5.0, 2.0))
    assert (segment.end.x, segment.end.y) == pytest.approx((5.0, 4.0))
    assert segment.length == pytest.approx(2.0)


def test_opening_segment_rejects_foreign_wall():
    wall = _wall("W-OTHER")
    with pytest.raises(ValueError):
        opening_segment(wall, _opening(wall_id="W-001"))


def test_group_openings_canonical_order_independent_of_insertion():
    a = _opening("O-002", start=4.0, end=6.0)
    b = _opening("O-001", start=3.0, end=5.0)
    forward = group_openings_by_wall([a, b])["W-001"]
    backward = group_openings_by_wall([b, a])["W-001"]
    assert [o.id for o in forward] == ["O-001", "O-002"]
    assert [o.id for o in backward] == ["O-001", "O-002"]


# ===========================================================================
# C. Los 20 casos geométricos de cruce (decisión BG)
# ===========================================================================

def test_g01_crossing_inside_opening_replaces_material_with_override():
    opening = _opening(start=4.0, end=6.0, overrides={BAND_24: 1.5})
    trace = _trace(5.0, openings=[opening])
    assert trace.crossings_count == 1
    crossing = trace.walls_crossed[0]
    assert crossing.opening_id == "O-001"
    assert crossing.loss_db == pytest.approx(1.5)
    # Reemplazo, nunca suma: drywall aporta 3.0 dB, no 3.0 + 1.5.
    assert trace.attenuation_db == pytest.approx(1.5)


def test_g02_crossing_inside_opening_without_override_is_zero_db():
    trace = _trace(5.0, openings=[_opening(start=4.0, end=6.0)])
    assert trace.walls_crossed[0].opening_id == "O-001"
    assert trace.attenuation_db == 0.0


def test_g03_crossing_outside_opening_keeps_material_loss():
    opening = _opening(start=6.0, end=8.0)  # hueco lejos del cruce (y=5)
    trace = _trace(5.0, openings=[opening])
    crossing = trace.walls_crossed[0]
    assert crossing.opening_id is None
    assert crossing.loss_db == pytest.approx(3.0)  # drywall band_2_4


def test_g04_crossing_at_opening_start_counts_as_opening():
    # Intervalo cerrado: el extremo inicial pertenece al hueco.
    opening = _opening(start=5.0, end=6.0, overrides={BAND_24: 2.0})
    trace = _trace(5.0, openings=[opening])
    assert trace.walls_crossed[0].opening_id == "O-001"
    assert trace.attenuation_db == pytest.approx(2.0)


def test_g05_crossing_at_opening_end_counts_as_opening():
    opening = _opening(start=4.0, end=5.0, overrides={BAND_24: 2.0})
    trace = _trace(5.0, openings=[opening])
    assert trace.walls_crossed[0].opening_id == "O-001"
    assert trace.attenuation_db == pytest.approx(2.0)


def test_g06_crossing_within_epsilon_before_start_counts_as_opening():
    # |d - start| <= EPSILON_GEOMETRY ⇒ dentro del hueco.
    opening = _opening(start=5.0, end=6.0)
    trace = _trace(5.0 - EPSILON_GEOMETRY / 2, openings=[opening])
    assert trace.walls_crossed[0].opening_id == "O-001"


def test_g07_crossing_clearly_before_start_is_solid():
    opening = _opening(start=6.0, end=7.0)
    trace = _trace(5.0, openings=[opening])  # 1 m fuera del hueco
    crossing = trace.walls_crossed[0]
    assert crossing.opening_id is None
    assert crossing.loss_db == pytest.approx(3.0)


def test_g08_crossing_in_gap_between_openings_is_solid():
    openings = [
        _opening("O-A", start=2.0, end=3.0),
        _opening("O-B", start=7.0, end=8.0),
    ]
    trace = _trace(5.0, openings=openings)  # hueco (3,7)
    assert trace.walls_crossed[0].opening_id is None
    assert trace.attenuation_db == pytest.approx(3.0)


def test_g09_union_of_openings_crossing_in_either():
    openings = [
        _opening("O-A", start=2.0, end=3.0),
        _opening("O-B", start=7.0, end=8.0),
    ]
    assert _trace(2.5, openings=openings).walls_crossed[0].opening_id == "O-A"
    assert _trace(7.5, openings=openings).walls_crossed[0].opening_id == "O-B"


def test_g10_overlapping_openings_pick_canonical_first():
    # Cubren y=5 ambos; gana el primero en orden (start, id) ⇒ O-001 (start 3).
    first = _opening("O-001", start=3.0, end=7.0, overrides={BAND_24: 1.0})
    second = _opening("O-002", start=4.0, end=8.0, overrides={BAND_24: 9.0})
    trace = _trace(5.0, openings=[second, first])
    crossing = trace.walls_crossed[0]
    assert crossing.opening_id == "O-001"
    assert crossing.loss_db == pytest.approx(1.0)


def test_g11_canonical_selection_independent_of_insertion_order():
    first = _opening("O-001", start=3.0, end=7.0, overrides={BAND_24: 1.0})
    second = _opening("O-002", start=4.0, end=8.0, overrides={BAND_24: 9.0})
    forward = _trace(5.0, openings=[first, second])
    backward = _trace(5.0, openings=[second, first])
    assert forward.attenuation_db == backward.attenuation_db
    assert forward.walls_crossed[0].opening_id == backward.walls_crossed[0].opening_id


def test_g12_opening_belonging_to_other_wall_is_ignored():
    foreign = _opening(wall_id="W-999", start=0.0, end=10.0)
    trace = _trace(5.0, openings=[foreign])
    assert trace.walls_crossed[0].opening_id is None
    assert trace.attenuation_db == pytest.approx(3.0)


def test_g13_no_crossing_means_no_effect():
    opening = _opening(start=4.0, end=6.0)
    source, target = Point2D(0.0, 20.0), Point2D(10.0, 20.0)  # por encima
    trace = trace_walls(source, target, [_wall()], BAND_24, openings=[opening])
    assert trace.crossings_count == 0
    assert trace.attenuation_db == 0.0


def test_g14_six_ghz_solid_raises_but_opening_gives_zero():
    with pytest.raises(MaterialAttenuationError):
        _trace(5.0, band_id=BAND_6)  # pared sólida: catálogo sin 6 GHz
    opening = _opening(start=4.0, end=6.0)  # hueco: no consulta materiales
    trace = _trace(5.0, openings=[opening], band_id=BAND_6)
    assert trace.attenuation_db == 0.0
    with_override = _opening(
        "O-002", start=4.0, end=6.0, overrides={BAND_6: 5.0}
    )
    trace2 = _trace(5.0, openings=[with_override], band_id=BAND_6)
    assert trace2.attenuation_db == pytest.approx(5.0)


def test_g15_replacement_never_addition():
    # override 2.0 sustituye al material (3.0); jamás 3.0 + 2.0 = 5.0.
    opening = _opening(start=4.0, end=6.0, overrides={BAND_24: 2.0})
    trace = _trace(5.0, openings=[opening])
    assert trace.attenuation_db == pytest.approx(2.0)
    assert trace.attenuation_db != pytest.approx(5.0)


def test_g16_two_walls_order_and_sum():
    solid = _wall("W-A", start=(3.0, 0.0), end=(3.0, 10.0))
    holed = _wall("W-B", start=(6.0, 0.0), end=(6.0, 10.0))
    opening = _opening("O-B1", wall_id="W-B", start=4.0, end=6.0)
    trace = _trace(5.0, openings=[opening], walls=[solid, holed])
    assert [c.wall.id for c in trace.walls_crossed] == ["W-A", "W-B"]
    assert trace.walls_crossed[0].opening_id is None
    assert trace.walls_crossed[1].opening_id == "O-B1"
    assert trace.attenuation_db == pytest.approx(3.0)  # 3.0 (sólida) + 0.0


def test_g17_blocks_signal_wall_skipped_even_with_opening():
    wall = _wall(blocks_signal=False)
    trace = _trace(5.0, openings=[_opening()], walls=[wall])
    assert trace.crossings_count == 0
    assert trace.attenuation_db == 0.0


def test_g18_trace_to_obstacle_loss_propagates_opening_id():
    opening = _opening(start=4.0, end=6.0, overrides={BAND_24: 1.5})
    trace = _trace(5.0, openings=[opening])
    loss = trace_to_obstacle_loss(trace)
    assert loss.crossings == 1
    assert loss.detail[0].opening_id == "O-001"
    assert loss.detail[0].loss_db == pytest.approx(1.5)
    assert loss.total_db == pytest.approx(1.5)


def test_g19_opening_at_far_end_of_wall():
    opening = _opening(start=9.0, end=10.0, overrides={BAND_24: 0.5})
    trace = _trace(9.5, openings=[opening])
    assert trace.walls_crossed[0].opening_id == "O-001"
    assert trace.attenuation_db == pytest.approx(0.5)


def test_g20_opening_covering_entire_wall():
    opening = _opening(start=0.0, end=10.0, overrides={BAND_24: 0.0})
    for y in (0.5, 5.0, 9.5):
        trace = _trace(y, openings=[opening])
        assert trace.walls_crossed[0].opening_id == "O-001"
        assert trace.attenuation_db == 0.0


def test_trace_is_deterministic_with_openings():
    opening = _opening(start=4.0, end=6.0, overrides={BAND_24: 1.0})
    a = _trace(5.0, openings=[opening])
    b = _trace(5.0, openings=[opening])
    assert a == b


def test_no_openings_result_identical_to_legacy_default():
    # Sin openings (default de Fase 2–7) == openings vacío: regresión F7.
    a = _trace(5.0)
    b = _trace(5.0, openings=())
    assert a == b
    assert a.attenuation_db == pytest.approx(3.0)


# ===========================================================================
# D. Sesión: CRUD de espacios y openings
# ===========================================================================

@pytest.fixture
def session() -> EditorSession:
    s = EditorSession()
    s.set_floor_dimensions(12.0, 8.0)
    s.heatmap_dirty = False  # para probar qué operaciones invalidan
    s.dirty = False
    return s


def test_tool_space_exists():
    assert Tool.SPACE.value == "space"
    assert SelectionKind.SPACE.value == "space"
    assert SelectionKind.OPENING.value == "opening"


def test_add_space_clamps_and_creates(session):
    space = session.add_space(Point2D(-5.0, -5.0), Point2D(4.0, 3.0))
    assert space.id.startswith("SPACE-")
    assert space.name.startswith("Espacio")
    assert space.rect.x == 0.0 and space.rect.y == 0.0
    assert space.rect.width == pytest.approx(4.0)
    assert space.rect.height == pytest.approx(3.0)
    assert space in session.floor.spaces
    assert session.selection.kind == SelectionKind.SPACE
    assert session.dirty is True


def test_add_space_never_invalidates_heatmap(session):
    # Decisión BH: los espacios no son RF ⇒ dirty sí, heatmap no.
    session.add_space(Point2D(1.0, 1.0), Point2D(3.0, 3.0))
    assert session.heatmap_dirty is False


def test_add_space_rejects_too_small(session):
    with pytest.raises(ValueError):
        session.add_space(Point2D(1.0, 1.0), Point2D(1.05, 3.0))
    with pytest.raises(ValueError):
        session.add_space(Point2D(1.0, 1.0), Point2D(3.0, 1.0))


def test_set_space_properties_validation(session):
    space = session.add_space(Point2D(1.0, 1.0), Point2D(3.0, 3.0))
    session.set_space_properties(space.id, "Sala 101", "lectura")
    stored = session.selected_space()
    assert stored.name == "Sala 101"
    assert stored.function == "lectura"
    with pytest.raises(ValueError):
        session.set_space_properties(space.id, "   ")
    with pytest.raises(KeyError):
        session.set_space_properties("SPACE-999", "X")


def test_delete_space_marks_dirty_without_heatmap(session):
    space = session.add_space(Point2D(1.0, 1.0), Point2D(3.0, 3.0))
    session.heatmap_dirty = False
    assert session.delete_selection() is True
    assert space not in session.floor.spaces
    assert session.heatmap_dirty is False


def test_add_opening_centered_default_length(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    session.heatmap_dirty = False
    opening = session.add_opening(wall.id, "door")
    assert opening.wall_id == wall.id
    assert opening.length_m == pytest.approx(DEFAULT_OPENING_LENGTH_M["door"])
    # Centrado: (5 - 0.9) / 2 = 2.05 … 2.95
    assert opening.start_offset_m == pytest.approx(2.05)
    assert opening.end_offset_m == pytest.approx(2.95)
    assert session.selection.kind == SelectionKind.OPENING
    # Los openings SÍ invalidan el heatmap (afectan la propagación).
    assert session.heatmap_dirty is True
    assert session.dirty is True


def test_add_opening_clamps_near_wall_end(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    opening = session.add_opening(wall.id, "door", center_offset_m=5.0)
    assert opening.end_offset_m == pytest.approx(5.0)
    assert opening.start_offset_m == pytest.approx(4.1)


def test_add_opening_validation(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    with pytest.raises(KeyError):
        session.add_opening("WALL-999", "door")
    with pytest.raises(ValueError):
        session.add_opening(wall.id, "arch")
    tiny = session.add_wall(Point2D(0.0, 2.0), Point2D(0.005, 2.0))
    with pytest.raises(ValueError):
        session.add_opening(tiny.id, "door")


def test_set_opening_offsets_clamps_to_wall(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    session.set_opening_offsets(opening.id, -10.0, 99.0)
    stored = session.selected_opening()
    assert stored.start_offset_m == 0.0
    assert stored.end_offset_m == pytest.approx(5.0)
    # La edición nunca produce un opening inválido.
    assert stored.length_m >= MIN_OPENING_LENGTH_M


def test_set_opening_offsets_rejects_too_small_result(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    with pytest.raises(ValueError):
        session.set_opening_offsets(opening.id, 4.999, 5.0)
    with pytest.raises(ValueError):
        session.set_opening_offsets(opening.id, float("nan"), 2.0)


def test_set_opening_kind_marks_dirty_without_invalidation(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    session.heatmap_dirty = False
    session.set_opening_kind(opening.id, "window")
    assert session.selected_opening().kind == "window"
    assert session.heatmap_dirty is False  # el tipo no cambia la pérdida (BG)
    assert session.dirty is True
    with pytest.raises(ValueError):
        session.set_opening_kind(opening.id, "arch")


def test_delete_opening_invalidates_heatmap(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    session.heatmap_dirty = False
    assert session.delete_selection() is True
    assert opening not in session.floor.openings
    assert session.heatmap_dirty is True


def test_delete_wall_cascades_its_openings(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    other = session.add_wall(Point2D(0.0, 2.0), Point2D(5.0, 2.0))
    session.add_opening(wall.id, "door")
    session.add_opening(wall.id, "window")
    session.add_opening(other.id, "door")
    session.select(SelectionKind.WALL, wall.id)
    assert session.delete_selection() is True
    remaining = session.floor.openings
    assert len(remaining) == 1
    assert remaining[0].wall_id == other.id


def test_openings_for_wall_canonical(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    b = session.add_opening(wall.id, "window", center_offset_m=4.0)  # OPEN-001
    a = session.add_opening(wall.id, "door", center_offset_m=1.0)  # OPEN-002
    ordered = session.openings_for_wall(wall.id)
    # Orden por (start, id): la puerta (start 0.55) antes que la ventana.
    assert [o.id for o in ordered] == [a.id, b.id]


def test_run_heatmap_passes_openings_to_simulator(session, monkeypatch):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    session.add_access_point(Point2D(2.0, 2.0))

    captured = {}

    def fake_simulate(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("ui.session.simulate_coverage", fake_simulate)
    session.run_heatmap()
    assert captured["openings"] == [opening]
    assert captured["walls"] == session.floor.walls


def test_run_simulation_passes_openings_to_simulator(session, monkeypatch):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    session.add_access_point(Point2D(2.0, 2.0))

    captured = {}

    def fake_simulate(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("ui.session.simulate_coverage", fake_simulate)
    session.run_simulation()
    assert captured["openings"] == [opening]


# ===========================================================================
# E. Integración: simulate_coverage con openings
# ===========================================================================

def _coverage_result(openings=()):
    project = Project(name="F8")
    ap = AccessPoint(
        id="AP-1", position=Point2D(0.0, 5.0), radio=RadioConfiguration()
    )
    band = next(b for b in DEFAULT_BANDS if b.id == BAND_5)
    return simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band,
        sample_points=[Point2D(10.0, 5.0)],
        walls=[_wall()],
        openings=openings,
    )


def test_opening_reduces_obstacle_loss_end_to_end():
    solid = _coverage_result()
    ev_solid = solid.evaluations[0]
    assert ev_solid.obstacle_loss.total_db == pytest.approx(4.0)  # drywall @5

    opened = _coverage_result(
        openings=[_opening(start=4.0, end=6.0)]
    )
    ev_open = opened.evaluations[0]
    assert ev_open.obstacle_loss.total_db == 0.0
    assert ev_open.obstacle_loss.detail[0].opening_id == "O-001"
    assert ev_open.rx_power_dbm > ev_solid.rx_power_dbm


def test_opening_override_shows_up_in_link_budget():
    opened = _coverage_result(
        openings=[_opening(start=4.0, end=6.0, overrides={BAND_5: 7.5})]
    )
    ev = opened.evaluations[0]
    assert ev.obstacle_loss.total_db == pytest.approx(7.5)
    assert ev.obstacle_loss.crossings == 1


# ===========================================================================
# F. Persistencia
# ===========================================================================

@pytest.fixture
def rich_session() -> EditorSession:
    s = EditorSession()
    s.set_floor_dimensions(12.0, 8.0)
    wall = s.add_wall(Point2D(0.0, 4.0), Point2D(12.0, 4.0))
    s.add_space(Point2D(1.0, 1.0), Point2D(5.0, 3.0))
    s.add_opening(wall.id, "door", center_offset_m=3.0)
    return s


def test_round_trip_preserves_spaces_and_openings(rich_session, tmp_path):
    path = save_project(rich_session.project, tmp_path / "f8.json")
    loaded, _state = load_project(path)
    assert project_to_dict(loaded) == project_to_dict(rich_session.project)
    floor = loaded.floors[0]
    assert len(floor.spaces) == 1
    assert floor.spaces[0].name == rich_session.floor.spaces[0].name
    assert len(floor.openings) == 1
    assert floor.openings[0].wall_id == rich_session.floor.walls[0].id
    assert floor.openings[0].kind == "door"


def test_schema_version_still_v1(rich_session, tmp_path):
    path = save_project(rich_session.project, tmp_path / "f8.json")
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["schema_version"] == SCHEMA_VERSION == 1
    floor_raw = raw["project"]["floors"][0]
    assert isinstance(floor_raw["spaces"], list)
    assert isinstance(floor_raw["openings"], list)
    opening_raw = floor_raw["openings"][0]
    for key in (
        "id",
        "wall_id",
        "start_offset_m",
        "end_offset_m",
        "kind",
        "attenuation_override_db",
    ):
        assert key in opening_raw


def test_legacy_document_without_spaces_openings_keys(rich_session):
    # Archivos F6/F7: sin claves spaces/openings ⇒ listas vacías (BE).
    raw = document_to_dict(rich_session.project, rich_session.editor_state())
    for floor_raw in raw["project"]["floors"]:
        floor_raw.pop("spaces", None)
        floor_raw.pop("openings", None)
    loaded, _state = document_from_dict(raw)
    floor = loaded.floors[0]
    assert floor.spaces == []
    assert floor.openings == []


def test_unknown_floor_keys_ignored_same_version(rich_session):
    raw = project_to_dict(rich_session.project)
    raw["floors"][0]["future_key"] = {"x": 1}
    loaded = project_from_dict(raw)
    assert len(loaded.floors[0].walls) == 1


def test_opening_with_unknown_wall_rejected(rich_session):
    raw = project_to_dict(rich_session.project)
    raw["floors"][0]["openings"][0]["wall_id"] = "WALL-NOPE"
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_opening_beyond_wall_length_rejected(rich_session):
    raw = project_to_dict(rich_session.project)
    raw["floors"][0]["openings"][0]["end_offset_m"] = 999.0
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_opening_non_numeric_offset_rejected(rich_session):
    raw = project_to_dict(rich_session.project)
    raw["floors"][0]["openings"][0]["start_offset_m"] = "abc"
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_opening_bad_kind_rejected(rich_session):
    raw = project_to_dict(rich_session.project)
    raw["floors"][0]["openings"][0]["kind"] = "arch"
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_opening_duplicate_ids_rejected(rich_session):
    raw = project_to_dict(rich_session.project)
    openings = raw["floors"][0]["openings"]
    openings.append(dict(openings[0]))
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_space_negative_width_rejected(rich_session):
    raw = project_to_dict(rich_session.project)
    raw["floors"][0]["spaces"][0]["rect"]["width_m"] = -1.0
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_openings_per_wall_cap(rich_session):
    raw = project_to_dict(rich_session.project)
    wall_id = raw["floors"][0]["openings"][0]["wall_id"]
    raw["floors"][0]["openings"] = [
        {
            "id": f"O-{i:03d}",
            "wall_id": wall_id,
            "start_offset_m": i * 0.01,
            "end_offset_m": i * 0.01 + 0.01,
            "kind": "door",
            "attenuation_override_db": {},
        }
        for i in range(33)  # MAX_OPENINGS_PER_WALL = 32
    ]
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_max_spaces_limit(rich_session, monkeypatch):
    import persistence.json_project_repository as jpr

    monkeypatch.setattr(jpr, "MAX_SPACES", 1)
    raw = project_to_dict(rich_session.project)
    raw["floors"][0]["spaces"].append(
        {
            "id": "SPACE-002",
            "name": "Otra",
            "function": "",
            "rect": {"x_m": 0.0, "y_m": 0.0, "width_m": 1.0, "height_m": 1.0},
            "metadata": {},
        }
    )
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_space_outside_floor_rect_is_tolerated(rich_session):
    # Decisión BJ: los espacios NO deben caer dentro del rect del piso.
    raw = project_to_dict(rich_session.project)
    rect = raw["floors"][0]["spaces"][0]["rect"]
    rect["x_m"] = 100.0
    rect["y_m"] = 100.0
    loaded = project_from_dict(raw)
    assert loaded.floors[0].spaces[0].rect.x == pytest.approx(100.0)
