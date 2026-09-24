"""Pruebas de Fase 9: obstáculos y mobiliario.

Cobertura:

- Dominio: ``Obstacle`` (validación BL, constantes, overrides BM),
  ``Rect.edge_segments``.
- Geometría de cruce (≥20 casos): semántica de un solo atravesamiento
  (decisión BN), tangencias/paralelos, orden canónico e invariante al
  orden de lista, ``trace_obstacles``, fusión pared+obstáculo.
- RF: override sustituye material (BM), 6 GHz con/sin override,
  ``simulate_coverage`` con/sin obstáculo (RSSI/SNR), multi-AP.
- Sesión: CRUD, clamps, invalidación (los obstáculos SÍ invalidan),
  herramientas/teclas, selección, borrado.
- Persistencia: round-trip ``floors[].obstacles`` (schema v1),
  claves opcionales ausentes, validación estricta.
- Determinismo: repetir un heatmap produce exactamente el mismo
  resultado (sin aleatoriedad ni orden dependiente de la lista).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.access_point import AccessPoint
from core.geometry import Point2D, Rect, Segment2D
from core.material import MaterialAttenuationError, default_materials
from core.obstacle import (
    DEFAULT_OBSTACLE_MATERIAL_ID,
    MAX_OBSTACLE_ATTENUATION_DB,
    MAX_OBSTACLE_SIZE_M,
    MIN_OBSTACLE_SIZE_M,
    OBSTACLE_KINDS,
    Obstacle,
)
from core.wall import Opening, Wall
from engine.obstacles import (
    obstacle_attenuation_db,
    trace_obstacles,
    trace_to_obstacle_loss,
    trace_walls,
)
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
# Utilidades
# ---------------------------------------------------------------------------

BAND_24 = "band_2_4"
BAND_5 = "band_5"
BAND_6 = "band_6"


def _material(material_id: str = "drywall"):
    return next(m for m in default_materials() if m.id == material_id)


def _obstacle(
    obstacle_id: str = "OBST-001",
    rect=(2.0, 4.0, 2.0, 2.0),
    material: str = "wood",
    name: str = "Mesa",
    **kwargs,
) -> Obstacle:
    """Obstáculo por defecto: footprint (2,4)+(2,2) — el trayecto
    horizontal (0,5)→(10,5) lo cruza en x=2 (distancia 2.0)."""
    return Obstacle(
        id=obstacle_id,
        name=name,
        rect=Rect(x=rect[0], y=rect[1], width=rect[2], height=rect[3]),
        material=_material(material),
        **kwargs,
    )


def _wall(
    wall_id: str = "WALL-001",
    start=(5.0, 0.0),
    end=(5.0, 10.0),
    material: str = "drywall",
    blocks_signal: bool = True,
) -> Wall:
    return Wall(
        id=wall_id,
        segment=Segment2D(Point2D(*start), Point2D(*end)),
        material=_material(material),
        blocks_signal=blocks_signal,
    )


def _opening(
    opening_id: str = "OPEN-001",
    wall_id: str = "WALL-001",
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


def _path(y: float = 5.0) -> tuple[Point2D, Point2D]:
    return Point2D(0.0, y), Point2D(10.0, y)


def _trace(
    y: float = 5.0,
    obstacles=(),
    walls=None,
    band_id: str = BAND_24,
    openings=(),
):
    source, target = _path(y)
    return trace_walls(
        source,
        target,
        [_wall()] if walls is None else walls,
        band_id,
        openings=openings,
        obstacles=obstacles,
    )


def _session_with_obstacle(**kwargs) -> tuple[EditorSession, Obstacle]:
    session = EditorSession()
    obstacle = session.add_obstacle(
        Point2D(2.0, 1.0), Point2D(4.0, 2.0), **kwargs
    )
    return session, obstacle


# ===========================================================================
# A. Dominio: Obstacle (validación y constantes — decisión BL)
# ===========================================================================


def test_obstacle_constants():
    assert OBSTACLE_KINDS == ("furniture", "equipment", "column", "other")
    assert MIN_OBSTACLE_SIZE_M == 0.1
    assert MAX_OBSTACLE_SIZE_M == 1000.0
    assert MAX_OBSTACLE_ATTENUATION_DB == 200.0
    assert DEFAULT_OBSTACLE_MATERIAL_ID == "wood"
    # El material por defecto existe en el catálogo V1.
    assert any(
        m.id == DEFAULT_OBSTACLE_MATERIAL_ID for m in default_materials()
    )


def test_obstacle_valid_defaults():
    obstacle = _obstacle()
    assert obstacle.kind == "furniture"
    assert obstacle.attenuation_override_db == {}
    assert obstacle.blocks_signal is True
    assert obstacle.metadata == {}
    assert obstacle.size_m == (2.0, 2.0)


def test_obstacle_accepts_all_kinds():
    for kind in OBSTACLE_KINDS:
        assert _obstacle(kind=kind).kind == kind


def test_obstacle_rejects_bad_kind():
    with pytest.raises(ValueError):
        _obstacle(kind="arch")


def test_obstacle_rejects_empty_id():
    with pytest.raises(ValueError):
        _obstacle(obstacle_id="   ")


def test_obstacle_rejects_non_str_name():
    with pytest.raises(ValueError):
        _obstacle(name=123)


def test_obstacle_rejects_non_rect():
    with pytest.raises(ValueError):
        Obstacle(
            id="OBST-001",
            name="X",
            rect=(2.0, 4.0, 2.0, 2.0),  # type: ignore[arg-type]
            material=_material(),
        )


def test_obstacle_rejects_non_finite_and_bool_rect():
    with pytest.raises(ValueError):
        _obstacle(rect=(float("nan"), 4.0, 2.0, 2.0))
    with pytest.raises(ValueError):
        _obstacle(rect=(0.0, 4.0, float("inf"), 2.0))
    with pytest.raises(ValueError):
        _obstacle(rect=(True, 4.0, 2.0, 2.0))


def test_obstacle_rejects_missing_material():
    with pytest.raises(ValueError):
        Obstacle(
            id="OBST-001",
            name="X",
            rect=Rect(0.0, 0.0, 1.0, 1.0),
            material=None,  # type: ignore[arg-type]
        )


def test_obstacle_rejects_non_dict_override():
    with pytest.raises(ValueError):
        _obstacle(attenuation_override_db=[("band_5", 6.0)])  # type: ignore[arg-type]


def test_obstacle_rejects_override_out_of_range():
    with pytest.raises(ValueError):
        _obstacle(attenuation_override_db={"band_5": -0.1})
    with pytest.raises(ValueError):
        _obstacle(
            attenuation_override_db={
                "band_5": MAX_OBSTACLE_ATTENUATION_DB + 1.0
            }
        )
    with pytest.raises(ValueError):
        _obstacle(attenuation_override_db={"band_5": float("nan")})
    with pytest.raises(ValueError):
        _obstacle(attenuation_override_db={"band_5": "6"})


def test_obstacle_rejects_empty_band_key_and_bool_value():
    with pytest.raises(ValueError):
        _obstacle(attenuation_override_db={"": 6.0})
    with pytest.raises(ValueError):
        _obstacle(attenuation_override_db={"band_5": True})


def test_obstacle_override_normalized_to_floats():
    obstacle = _obstacle(attenuation_override_db={"band_5": 6})
    assert obstacle.attenuation_override_db == {"band_5": 6.0}
    assert isinstance(obstacle.attenuation_override_db["band_5"], float)


def test_obstacle_is_frozen():
    obstacle = _obstacle()
    with pytest.raises(FrozenInstanceError):
        obstacle.name = "Otra"  # type: ignore[misc]


def test_rect_edge_segments_closed_loop():
    rect = Rect(x=1.0, y=2.0, width=3.0, height=4.0)
    edges = rect.edge_segments()
    assert len(edges) == 4
    # Cierre del contorno: el final de cada borde es el inicio del siguiente.
    for index in range(4):
        current = edges[index]
        following = edges[(index + 1) % 4]
        assert current.end == following.start
    # Área cubierta: el centro no está en ningún borde.
    center = Point2D(2.5, 4.0)
    for edge in edges:
        params = Segment2D(edge.start, edge.end)
        assert params.length > 0
    assert rect.contains(center)


# ===========================================================================
# B. Trazado: semántica de cruce (decisión BN) y orden canónico
# ===========================================================================


def test_trace_without_obstacles_is_empty():
    trace = _trace(obstacles=[])
    assert trace.walls_crossed[0].wall.id == "WALL-001"
    assert trace.obstacles_crossed == ()
    assert trace.obstacle_ids == ()
    assert trace.crossings_count == len(trace.walls_crossed)


def test_trace_default_obstacles_matches_explicit_empty():
    a = _trace(obstacles=())
    source, target = _path()
    b = trace_walls(source, target, [_wall()], BAND_24)
    assert a == b
    assert a.attenuation_db == b.attenuation_db


def test_single_crossing_counts_once_with_entry_distance():
    trace = _trace(obstacles=[_obstacle()])
    assert trace.obstacle_ids == ("OBST-001",)
    crossing = trace.obstacles_crossed[0]
    assert crossing.loss_db == pytest.approx(
        _material("wood").attenuation_for(BAND_24)
    )
    assert crossing.distance_from_source_m == pytest.approx(2.0)
    assert crossing.order == 0
    # pared (3.0) + obstáculo (3.0)
    assert trace.attenuation_db == pytest.approx(6.0)


def test_thin_obstacle_crossed_twice_counts_once():
    # Rect delgado: el rayo entra por x=5 y sale por x=5.5.
    thin = _obstacle(rect=(5.0, 4.5, 0.5, 1.0))
    trace = _trace(obstacles=[thin])
    assert trace.obstacle_ids == ("OBST-001",)
    assert len(trace.obstacles_crossed) == 1
    assert trace.obstacles_crossed[0].distance_from_source_m == pytest.approx(
        5.0
    )
    assert trace.attenuation_db == pytest.approx(6.0)


def test_exact_corner_touch_does_not_count():
    # Borde inferior del rect en y=5: el rayo lo toca exactamente.
    corner = _obstacle(rect=(4.0, 5.0, 1.0, 1.0))
    trace = _trace(y=5.0, obstacles=[corner], walls=[])
    assert trace.obstacle_ids == ()
    assert trace.attenuation_db == 0.0


def test_diagonal_exactly_through_corner_does_not_count():
    # Rect [4,5]-[5,6]; diagonal (0,4)→(8,8) toca SOLO el vértice
    # superior-izquierdo (4,6): en ambos lados el rayo queda fuera.
    corner = _obstacle(rect=(4.0, 5.0, 1.0, 1.0))
    source, target = Point2D(0.0, 4.0), Point2D(8.0, 8.0)
    trace = trace_walls(source, target, [], BAND_24, obstacles=[corner])
    assert trace.obstacle_ids == ()
    assert trace.attenuation_db == 0.0


def test_diagonal_exit_exactly_at_corner_keeps_entry():
    # Mismo rect: (0,4)→(10,8) entra por la arista izquierda (interior,
    # y=5.6) y sale exactamente por la esquina (5,6). La entrada cuenta.
    clipped = _obstacle(rect=(4.0, 5.0, 1.0, 1.0))
    source, target = Point2D(0.0, 4.0), Point2D(10.0, 8.0)
    trace = trace_walls(source, target, [], BAND_24, obstacles=[clipped])
    assert trace.obstacle_ids == ("OBST-001",)
    assert trace.attenuation_db == pytest.approx(3.0)


def test_path_entirely_inside_counts_zero():
    # Documentado (BN): un trayecto completamente dentro no cruza bordes.
    source, target = Point2D(2.5, 5.0), Point2D(3.5, 5.0)
    trace = trace_walls(
        source, target, [], BAND_24, obstacles=[_obstacle()]
    )
    assert trace.obstacle_ids == ()
    assert trace.attenuation_db == 0.0


def test_off_path_obstacle_ignored():
    far = _obstacle(rect=(2.0, 0.5, 2.0, 1.0))
    trace = _trace(obstacles=[far])
    assert trace.obstacle_ids == ()
    assert trace.attenuation_db == pytest.approx(3.0)  # solo la pared


def test_blocks_signal_false_ignored():
    ghost = _obstacle(blocks_signal=False)
    trace = _trace(obstacles=[ghost])
    assert trace.obstacle_ids == ()
    assert trace.attenuation_db == pytest.approx(3.0)


def test_two_obstacles_ordered_by_distance():
    first = _obstacle(obstacle_id="OBST-001", rect=(1.0, 4.0, 1.0, 2.0))
    second = _obstacle(obstacle_id="OBST-002", rect=(3.0, 4.0, 1.0, 2.0))
    trace = _trace(obstacles=[first, second])
    assert trace.obstacle_ids == ("OBST-001", "OBST-002")
    distances = [c.distance_from_source_m for c in trace.obstacles_crossed]
    assert distances == pytest.approx([1.0, 3.0])
    assert trace.attenuation_db == pytest.approx(3.0 + 3.0 + 3.0)


def test_order_invariant_to_input_list_order():
    a = _obstacle(obstacle_id="OBST-001", rect=(1.0, 4.0, 1.0, 2.0))
    b = _obstacle(obstacle_id="OBST-002", rect=(3.0, 4.0, 1.0, 2.0))
    direct = _trace(obstacles=[a, b])
    reversed_ = _trace(obstacles=[b, a])
    assert direct.obstacle_ids == reversed_.obstacle_ids
    assert direct.attenuation_db == reversed_.attenuation_db
    assert direct == reversed_


def test_tie_break_by_id_when_same_distance():
    # Dos rects con la MISMA entrada (x=2, distancia 2.0): orden por id.
    one = _obstacle(obstacle_id="OBST-002", rect=(2.0, 4.0, 1.0, 2.0))
    two = _obstacle(obstacle_id="OBST-001", rect=(2.0, 3.0, 1.0, 4.0))
    trace = _trace(obstacles=[one, two])
    assert trace.obstacle_ids == ("OBST-001", "OBST-002")
    distances = [c.distance_from_source_m for c in trace.obstacles_crossed]
    assert distances == pytest.approx([2.0, 2.0])


def test_determinism_repeated_trace_identical():
    obstacle = _obstacle()
    a = _trace(obstacles=[obstacle])
    b = _trace(obstacles=[obstacle])
    assert a == b


def test_trace_obstacles_matches_trace_walls():
    obstacles = [
        _obstacle(obstacle_id="OBST-001", rect=(1.0, 4.0, 1.0, 2.0)),
        _obstacle(obstacle_id="OBST-002", rect=(7.0, 4.0, 1.0, 2.0)),
    ]
    source, target = _path()
    only = trace_obstacles(source, target, obstacles, BAND_24)
    merged = trace_walls(source, target, [], BAND_24, obstacles=obstacles)
    assert [c.obstacle.id for c in only] == list(merged.obstacle_ids)
    assert [c.loss_db for c in only] == [
        c.loss_db for c in merged.obstacles_crossed
    ]
    assert only[0].distance_from_source_m == pytest.approx(1.0)


def test_trace_obstacles_empty_without_crossings():
    source, target = _path()
    assert trace_obstacles(source, target, [], BAND_24) == ()
    off = [_obstacle(rect=(2.0, 0.5, 2.0, 1.0))]
    assert trace_obstacles(source, target, off, BAND_24) == ()


def test_wall_and_obstacle_fusioned_by_distance():
    obstacle = _obstacle(rect=(2.0, 4.0, 1.0, 2.0))
    trace = _trace(obstacles=[obstacle])  # pared en x=5
    assert trace.obstacle_ids == ("OBST-001",)
    assert trace.wall_ids == ("WALL-001",)
    # El obstáculo (x=2) está antes que la pared (x=5).
    assert (
        trace.obstacles_crossed[0].distance_from_source_m
        < trace.walls_crossed[0].distance_from_source_m
    )
    # Cada lista indexa por su propio tipo (0-based).
    assert trace.walls_crossed[0].order == 0
    assert trace.obstacles_crossed[0].order == 0
    assert trace.attenuation_db == pytest.approx(6.0)


def test_wall_after_obstacle_sum_order_reproducible():
    # Pared CONCRETO (12) detrás de un obstáculo con override no entero.
    obstacle = _obstacle(
        attenuation_override_db={BAND_24: 3.5},
        material="metal",
    )
    a = _trace(obstacles=[obstacle], walls=[_wall(material="concrete")])
    b = _trace(obstacles=[obstacle][::-1], walls=[_wall(material="concrete")])
    assert a.attenuation_db == b.attenuation_db == pytest.approx(15.5)
    assert a.obstacle_ids == b.obstacle_ids == ("OBST-001",)


def test_opening_replaces_wall_but_obstacle_remains_independent():
    # Hueco en la pared (0 dB) + obstáculo en la misma trayectoria:
    # la pérdida total es SOLO la del obstáculo (sin doble atenuación).
    wall = _wall()
    opening = _opening(start=4.0, end=6.0)  # cruce en y=5
    obstacle = _obstacle(material="metal")  # 25 dB
    trace = _trace(obstacles=[obstacle], walls=[wall], openings=[opening])
    assert trace.walls_crossed[0].opening_id == "OPEN-001"
    assert trace.walls_crossed[0].loss_db == 0.0
    assert trace.obstacles_crossed[0].loss_db == pytest.approx(25.0)
    assert trace.attenuation_db == pytest.approx(25.0)


def test_trace_to_obstacle_loss_includes_obstacles():
    obstacle = _obstacle(material="metal")
    trace = _trace(obstacles=[obstacle])
    loss = trace_to_obstacle_loss(trace)
    assert loss.crossings == 2  # pared + obstáculo
    assert loss.total_db == pytest.approx(trace.attenuation_db)
    wall_entries = [d for d in loss.detail if d.wall_id is not None]
    obstacle_entries = [d for d in loss.detail if d.obstacle_id is not None]
    assert len(wall_entries) == 1 and len(obstacle_entries) == 1
    assert obstacle_entries[0].wall_id is None
    assert wall_entries[0].obstacle_id is None
    assert obstacle_entries[0].loss_db == pytest.approx(25.0)


def test_trace_to_obstacle_loss_without_obstacles_matches_f8():
    trace = _trace(obstacles=[])
    loss = trace_to_obstacle_loss(trace)
    assert loss.crossings == len(trace.walls_crossed)
    assert all(d.obstacle_id is None for d in loss.detail)
    assert loss.total_db == pytest.approx(trace.attenuation_db)


# ===========================================================================
# C. Atenuación por material/override (decisión BM) y 6 GHz
# ===========================================================================


def test_attenuation_uses_material_without_thickness_scaling():
    # El footprint NO es un espesor: se usa la referencia tal cual.
    obstacle = _obstacle(material="metal")
    assert obstacle_attenuation_db(obstacle, BAND_24) == pytest.approx(25.0)
    assert obstacle_attenuation_db(obstacle, BAND_5) == pytest.approx(30.0)


def test_override_substitutes_material_never_sums():
    # metal=25 dB pero override 7 ⇒ 7 (no 32, no 25).
    obstacle = _obstacle(material="metal", attenuation_override_db={BAND_24: 7.0})
    assert obstacle_attenuation_db(obstacle, BAND_24) == pytest.approx(7.0)
    # Otras bandas siguen usando el material.
    assert obstacle_attenuation_db(obstacle, BAND_5) == pytest.approx(30.0)


def test_wall_plus_obstacle_sum_is_independent_losses():
    # Pared drywall (3) + obstáculo override (7) = 10 exacto: las
    # pérdidas son independientes; el material del obstáculo no suma.
    obstacle = _obstacle(material="metal", attenuation_override_db={BAND_24: 7.0})
    trace = _trace(obstacles=[obstacle])
    assert trace.attenuation_db == pytest.approx(10.0)


def test_six_ghz_without_override_raises():
    obstacle = _obstacle()
    with pytest.raises(MaterialAttenuationError):
        obstacle_attenuation_db(obstacle, BAND_6)


def test_six_ghz_crossed_obstacle_raises_in_trace():
    with pytest.raises(MaterialAttenuationError):
        _trace(obstacles=[_obstacle()], walls=[], band_id=BAND_6)


def test_six_ghz_off_path_obstacle_does_not_raise():
    far = _obstacle(rect=(2.0, 0.5, 2.0, 1.0))
    trace = _trace(obstacles=[far], band_id=BAND_6, walls=[])
    assert trace.attenuation_db == 0.0
    assert trace.obstacle_ids == ()


def test_six_ghz_with_override_works():
    obstacle = _obstacle(attenuation_override_db={BAND_6: 5.0})
    trace = _trace(obstacles=[obstacle], band_id=BAND_6, walls=[])
    assert trace.attenuation_db == pytest.approx(5.0)
    assert trace.obstacles_crossed[0].loss_db == pytest.approx(5.0)


# ===========================================================================
# D. Simulación RF (simulate_coverage con obstáculos)
# ===========================================================================


def _rf_setup():
    session = EditorSession()
    project = session.project
    ap = AccessPoint(id="AP-001", position=Point2D(1.0, 4.0), radio=project.radio)
    target = Point2D(11.0, 4.0)
    return session, project, ap, target


def test_simulation_rssi_decreases_with_obstacle():
    _session, project, ap, target = _rf_setup()
    band = project.get_band(BAND_24)
    base = simulate_coverage(
        project, ap, band, [target], walls=[]
    ).evaluations[0]
    with_obs = simulate_coverage(
        project, ap, band, [target], walls=[],
        obstacles=[_obstacle(rect=(5.0, 3.0, 1.0, 2.0))],
    ).evaluations[0]
    # Wood = 3 dB en 2.4 GHz: estrictamente peor y exactamente 3 dB menos.
    assert with_obs.rx_power_dbm < base.rx_power_dbm
    assert with_obs.rx_power_dbm == pytest.approx(base.rx_power_dbm - 3.0)
    assert with_obs.snr_db == pytest.approx(base.snr_db - 3.0)


def test_simulation_unchanged_when_obstacle_off_path():
    _session, project, ap, target = _rf_setup()
    band = project.get_band(BAND_24)
    base = simulate_coverage(
        project, ap, band, [target], walls=[]
    ).evaluations[0]
    off = simulate_coverage(
        project, ap, band, [target], walls=[],
        obstacles=[_obstacle(rect=(5.0, 6.5, 1.0, 1.0))],
    ).evaluations[0]
    assert off.rx_power_dbm == base.rx_power_dbm
    assert off.snr_db == base.snr_db


def test_simulation_multi_ap_obstacle_only_affects_crossed_path():
    _session, project, ap, target = _rf_setup()
    band = project.get_band(BAND_24)
    ap_far = AccessPoint(
        id="AP-002", position=Point2D(11.0, 1.0), radio=project.radio
    )
    obstacle = _obstacle(rect=(5.0, 3.0, 1.0, 2.0))

    crossed_base = simulate_coverage(
        project, ap, band, [target], walls=[]
    ).evaluations[0]
    crossed_obs = simulate_coverage(
        project, ap, band, [target], walls=[], obstacles=[obstacle]
    ).evaluations[0]
    other_base = simulate_coverage(
        project, ap_far, band, [target], walls=[]
    ).evaluations[0]
    other_obs = simulate_coverage(
        project, ap_far, band, [target], walls=[], obstacles=[obstacle]
    ).evaluations[0]

    assert crossed_obs.rx_power_dbm < crossed_base.rx_power_dbm
    assert other_obs.rx_power_dbm == other_base.rx_power_dbm


def test_simulation_six_ghz_raises_without_override_and_works_with_it():
    _session, project, ap, target = _rf_setup()
    band = project.get_band(BAND_6)
    obstacle = _obstacle(rect=(5.0, 3.0, 1.0, 2.0))
    with pytest.raises(MaterialAttenuationError):
        simulate_coverage(
            project, ap, band, [target], walls=[], obstacles=[obstacle]
        )
    patched = Obstacle(
        id=obstacle.id,
        name=obstacle.name,
        rect=obstacle.rect,
        material=obstacle.material,
        attenuation_override_db={BAND_6: 4.0},
    )
    base = simulate_coverage(
        project, ap, band, [target], walls=[]
    ).evaluations[0]
    with_obs = simulate_coverage(
        project, ap, band, [target], walls=[], obstacles=[patched]
    ).evaluations[0]
    assert with_obs.rx_power_dbm == pytest.approx(base.rx_power_dbm - 4.0)


def test_simulation_determinism_same_input_same_output():
    session = EditorSession()
    project = session.project
    ap = AccessPoint(id="AP-001", position=Point2D(2.0, 2.0), radio=project.radio)
    band = project.get_band(BAND_24)
    points = [Point2D(x, y) for x in (1.0, 5.0, 9.0) for y in (1.0, 4.0, 7.0)]
    obstacle = _obstacle(rect=(4.0, 1.0, 2.0, 6.0))
    a = simulate_coverage(
        project, ap, band, points, walls=[], obstacles=[obstacle]
    )
    b = simulate_coverage(
        project, ap, band, points, walls=[], obstacles=[obstacle]
    )
    assert [e.rx_power_dbm for e in a.evaluations] == [
        e.rx_power_dbm for e in b.evaluations
    ]
    assert [e.obstacle_loss_db for e in a.evaluations] == [
        e.obstacle_loss_db for e in b.evaluations
    ]


# ===========================================================================
# E. Sesión del editor (CRUD + invalidación — decisión BP)
# ===========================================================================


def test_tool_and_selection_variants_exist():
    assert Tool.OBSTACLE.value == "obstacle"
    assert SelectionKind.OBSTACLE.value == "obstacle"


def test_add_obstacle_selects_and_marks_dirty():
    session = EditorSession()
    session.mark_saved(None)  # dirty = False explícitamente
    session.dirty = False
    session.heatmap_dirty = False
    obstacle = session.add_obstacle(Point2D(2.0, 1.0), Point2D(4.0, 2.0))
    assert obstacle.id == "OBST-001"
    assert session.selection.kind == SelectionKind.OBSTACLE
    assert session.selection.entity_id == obstacle.id
    assert session.selected_obstacle() == obstacle
    assert session.dirty is True
    assert session.heatmap_dirty is True  # SÍ invalida (a diferencia de Space)


def test_add_obstacle_clamps_to_floor():
    session = EditorSession()
    # Una esquina dentro y la otra fuera: se recorta sin perder tamaño.
    obstacle = session.add_obstacle(Point2D(10.0, 6.0), Point2D(60.0, 60.0))
    assert obstacle.rect.x == pytest.approx(10.0)
    assert obstacle.rect.y == pytest.approx(6.0)
    assert obstacle.rect.x + obstacle.rect.width == pytest.approx(
        session.floor_width_m
    )
    assert obstacle.rect.y + obstacle.rect.height == pytest.approx(
        session.floor_height_m
    )
    assert obstacle.rect.x >= 0.0 and obstacle.rect.y >= 0.0


def test_add_obstacle_rejects_too_small():
    session = EditorSession()
    with pytest.raises(ValueError):
        session.add_obstacle(
            Point2D(1.0, 1.0),
            Point2D(1.0 + MIN_OBSTACLE_SIZE_M / 2, 1.5),
        )
    assert session.floor.obstacles == []


def test_add_obstacle_default_material_and_name():
    session = EditorSession()
    obstacle = session.add_obstacle(Point2D(1.0, 1.0), Point2D(3.0, 2.0))
    assert obstacle.material.id == DEFAULT_OBSTACLE_MATERIAL_ID
    assert obstacle.name.startswith("Objeto ")
    assert obstacle.kind == "furniture"


def test_add_obstacle_ids_increment_uniquely():
    session = EditorSession()
    session.add_wall(Point2D(0.0, 0.0), Point2D(5.0, 0.0))
    a = session.add_obstacle(Point2D(1.0, 1.0), Point2D(2.0, 2.0))
    b = session.add_obstacle(Point2D(3.0, 1.0), Point2D(4.0, 2.0))
    assert a.id == "OBST-001"
    assert b.id == "OBST-002"
    assert len({a.id, b.id, "WALL-001"}) == 3


def test_set_obstacle_properties_updates_and_invalidates():
    session, obstacle = _session_with_obstacle()
    session.heatmap_dirty = False
    session.dirty = False
    session.set_obstacle_properties(
        obstacle.id,
        "Rack",
        kind="equipment",
        material_id="metal",
        attenuation_override_db={BAND_5: 6.0},
    )
    updated = session.selected_obstacle()
    assert updated.name == "Rack"
    assert updated.kind == "equipment"
    assert updated.material.id == "metal"
    assert updated.attenuation_override_db == {BAND_5: 6.0}
    assert session.heatmap_dirty is True
    assert session.dirty is True


def test_set_obstacle_properties_keeps_material_if_none():
    session, obstacle = _session_with_obstacle()
    session.set_obstacle_properties(obstacle.id, "Mesa 2", material_id=None)
    assert session.selected_obstacle().material.id == DEFAULT_OBSTACLE_MATERIAL_ID


def test_set_obstacle_properties_validation():
    session, obstacle = _session_with_obstacle()
    with pytest.raises(ValueError):
        session.set_obstacle_properties(obstacle.id, "   ")
    with pytest.raises(ValueError):
        session.set_obstacle_properties(obstacle.id, "X", kind="robot")
    with pytest.raises(KeyError):
        session.set_obstacle_properties(
            obstacle.id, "X", material_id="unobtainium"
        )
    with pytest.raises(ValueError):
        session.set_obstacle_properties(
            obstacle.id, "X", attenuation_override_db={"band_5": 500.0}
        )
    with pytest.raises(KeyError):
        session.set_obstacle_properties("OBST-999", "X")


def test_move_obstacle_clamps_and_keeps_size():
    session, obstacle = _session_with_obstacle()
    session.heatmap_dirty = False
    session.dirty = False
    session.move_obstacle(obstacle.id, Point2D(100.0, 100.0))
    moved = session.selected_obstacle()
    assert moved.rect.x == pytest.approx(session.floor_width_m - 2.0)
    assert moved.rect.y == pytest.approx(session.floor_height_m - 1.0)
    assert moved.size_m == obstacle.size_m
    assert session.heatmap_dirty is True and session.dirty is True


def test_move_obstacle_negative_clamps_to_zero():
    session, obstacle = _session_with_obstacle()
    session.move_obstacle(obstacle.id, Point2D(-50.0, -50.0))
    moved = session.selected_obstacle()
    assert moved.rect.x == 0.0 and moved.rect.y == 0.0


def test_move_obstacle_unknown_id():
    session, _ = _session_with_obstacle()
    with pytest.raises(KeyError):
        session.move_obstacle("OBST-999", Point2D(0.0, 0.0))


def test_delete_obstacle_invalidates_and_clears_selection():
    session, obstacle = _session_with_obstacle()
    session.heatmap_dirty = False
    session.dirty = False
    assert session.delete_selection() is True
    assert session.floor.obstacles == []
    assert session.selection is None
    assert session.heatmap_dirty is True and session.dirty is True
    assert session.delete_selection() is False


def test_set_tool_clears_obstacle_drag():
    session = EditorSession()
    session.obstacle_drag_start = Point2D(1.0, 1.0)
    session.set_tool(Tool.WALL)
    assert session.obstacle_drag_start is None


def test_new_project_resets_obstacle_drag():
    session = EditorSession()
    session.obstacle_drag_start = Point2D(1.0, 1.0)
    session.new_project()
    assert session.obstacle_drag_start is None
    assert session.floor.obstacles == []


def test_run_simulation_summary_counts_objects():
    session, _ = _session_with_obstacle()
    session.add_access_point(Point2D(2.0, 2.0))
    session.run_simulation(BAND_24)
    text = session.simulation_summary_text()
    assert "Objetos: 1" in text
    assert "Paredes:" in text


def test_run_heatmap_uses_obstacles_and_is_deterministic():
    session, obstacle = _session_with_obstacle()
    session.add_access_point(Point2D(1.0, 1.0))

    # Determinismo: dos ejecuciones con el mismo documento ⇒ idénticas.
    first = session.run_heatmap(BAND_24)
    again = session.run_heatmap(BAND_24)
    assert [e.rx_power_dbm for e in first.evaluations] == [
        e.rx_power_dbm for e in again.evaluations
    ]

    # Efecto A/B: quitar el obstáculo (seleccionado) y re-ejecutar.
    session.select(SelectionKind.OBSTACLE, obstacle.id)
    assert session.delete_selection() is True
    second = session.run_heatmap(BAND_24)
    with_obs = [e.rx_power_dbm for e in first.evaluations]
    without = [e.rx_power_dbm for e in second.evaluations]
    assert len(with_obs) == len(without)
    deltas = [a - b for a, b in zip(with_obs, without)]
    # Ninguna celda puede MEJORAR al añadir el obstáculo…
    assert all(d <= 1e-9 for d in deltas)
    # …y al menos una celda cruza el footprint (wood = 3 dB peor).
    assert min(deltas) <= -3.0 + 1e-6


def test_space_addition_does_not_invalidate_but_obstacle_does():
    # Contraste explícito BH vs F9 (BP).
    session = EditorSession()
    session.heatmap_dirty = False
    session.add_space(Point2D(1.0, 1.0), Point2D(3.0, 3.0))
    assert session.heatmap_dirty is False
    session.heatmap_dirty = False
    session.add_obstacle(Point2D(4.0, 1.0), Point2D(6.0, 3.0))
    assert session.heatmap_dirty is True


# ===========================================================================
# F. Persistencia: floors[].obstacles (schema v1, decisión BO)
# ===========================================================================


def _rich_session() -> EditorSession:
    session = EditorSession()
    session.add_access_point(Point2D(1.0, 1.0))
    obstacle = session.add_obstacle(Point2D(2.0, 1.0), Point2D(4.0, 3.0))
    session.set_obstacle_properties(
        obstacle.id,
        "Servidor",
        kind="equipment",
        material_id="metal",
        attenuation_override_db={BAND_24: 12.0, BAND_5: 18.0},
    )
    return session


def test_document_roundtrip_preserves_obstacles():
    session = _rich_session()
    raw = document_to_dict(session.project, session.editor_state())
    loaded, state = document_from_dict(raw)
    obstacles = loaded.floors[0].obstacles
    assert len(obstacles) == 1
    obstacle = obstacles[0]
    assert obstacle.id == "OBST-001"
    assert obstacle.name == "Servidor"
    assert obstacle.kind == "equipment"
    assert obstacle.material.id == "metal"
    assert obstacle.rect == Rect(x=2.0, y=1.0, width=2.0, height=2.0)
    assert obstacle.attenuation_override_db == {
        BAND_24: 12.0,
        BAND_5: 18.0,
    }
    assert state.band_id == session.band_id


def test_project_roundtrip_preserves_obstacles():
    session = _rich_session()
    raw = project_to_dict(session.project)
    assert "obstacles" in raw["floors"][0]
    loaded = project_from_dict(raw)
    assert len(loaded.floors[0].obstacles) == 1


def test_schema_version_still_one():
    session = _rich_session()
    raw = document_to_dict(session.project, session.editor_state())
    assert raw["schema_version"] == SCHEMA_VERSION == 1


def test_file_without_obstacles_key_opens_with_empty_list():
    session = _rich_session()
    raw = project_to_dict(session.project)
    del raw["floors"][0]["obstacles"]
    loaded = project_from_dict(raw)
    assert loaded.floors[0].obstacles == []


def test_save_and_load_file_roundtrip(tmp_path):
    session = _rich_session()
    path = save_project(
        session.project, tmp_path / "f9.json", session.editor_state()
    )
    loaded, _state = load_project(path)
    assert len(loaded.floors[0].obstacles) == 1
    assert loaded.floors[0].obstacles[0].name == "Servidor"


def test_blocks_signal_false_roundtrip():
    session = EditorSession()
    session.add_obstacle(Point2D(1.0, 1.0), Point2D(2.0, 2.0))
    session.floor.obstacles[0] = Obstacle(
        id=session.floor.obstacles[0].id,
        name="Fantasma",
        rect=session.floor.obstacles[0].rect,
        material=session.floor.obstacles[0].material,
        blocks_signal=False,
    )
    raw = project_to_dict(session.project)
    loaded = project_from_dict(raw)
    assert loaded.floors[0].obstacles[0].blocks_signal is False


def test_rejects_unknown_material():
    session = _rich_session()
    raw = project_to_dict(session.project)

    def mutate(item):
        item["material_id"] = "unobtainium"

    mutate(raw["floors"][0]["obstacles"][0])
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_rejects_unknown_kind():
    session = _rich_session()
    raw = project_to_dict(session.project)
    raw["floors"][0]["obstacles"][0]["kind"] = "spaceship"
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_rejects_override_out_of_range():
    session = _rich_session()
    raw = project_to_dict(session.project)
    raw["floors"][0]["obstacles"][0]["attenuation_override_db"] = {
        BAND_5: MAX_OBSTACLE_ATTENUATION_DB + 1.0
    }
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_rejects_negative_override():
    session = _rich_session()
    raw = project_to_dict(session.project)
    raw["floors"][0]["obstacles"][0]["attenuation_override_db"] = {
        BAND_5: -1.0
    }
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_rejects_missing_rect_and_material():
    session = _rich_session()
    raw = project_to_dict(session.project)
    del raw["floors"][0]["obstacles"][0]["rect"]
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)

    raw = project_to_dict(session.project)
    del raw["floors"][0]["obstacles"][0]["material_id"]
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_rejects_zero_and_oversized_rect():
    session = _rich_session()
    raw = project_to_dict(session.project)
    raw["floors"][0]["obstacles"][0]["rect"]["width_m"] = 0.0
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)

    raw = project_to_dict(session.project)
    raw["floors"][0]["obstacles"][0]["rect"]["width_m"] = (
        MAX_OBSTACLE_SIZE_M + 1.0
    )
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_rejects_non_finite_rect_coordinate():
    session = _rich_session()
    raw = project_to_dict(session.project)
    raw["floors"][0]["obstacles"][0]["rect"]["x_m"] = float("nan")
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_rejects_duplicate_obstacle_ids():
    session = EditorSession()
    session.add_obstacle(Point2D(1.0, 1.0), Point2D(2.0, 2.0))
    session.add_obstacle(Point2D(3.0, 1.0), Point2D(4.0, 2.0))
    raw = project_to_dict(session.project)
    raw["floors"][0]["obstacles"][1]["id"] = "OBST-001"
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_rejects_too_many_obstacles():
    from persistence.json_project_repository import MAX_OBSTACLES

    session = EditorSession()
    raw = project_to_dict(session.project)
    template = {
        "id": "OBST-001",
        "name": "X",
        "kind": "furniture",
        "rect": {"x_m": 1.0, "y_m": 1.0, "width_m": 1.0, "height_m": 1.0},
        "material_id": "wood",
        "blocks_signal": True,
        "attenuation_override_db": {},
        "metadata": {},
    }
    raw["floors"][0]["obstacles"] = [
        dict(template, id=f"OBST-{index:05d}")
        for index in range(MAX_OBSTACLES + 1)
    ]
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)

    raw["floors"][0]["obstacles"] = [
        dict(template, id=f"OBST-{index:05d}")
        for index in range(MAX_OBSTACLES)
    ]
    assert len(project_from_dict(raw).floors[0].obstacles) == MAX_OBSTACLES


def test_rejects_non_dict_metadata():
    session = _rich_session()
    raw = project_to_dict(session.project)
    raw["floors"][0]["obstacles"][0]["metadata"] = ["nope"]
    with pytest.raises(ProjectFormatError):
        project_from_dict(raw)


def test_metadata_roundtrip():
    session = EditorSession()
    obstacle = session.add_obstacle(Point2D(1.0, 1.0), Point2D(2.0, 2.0))
    session.floor.obstacles[0] = Obstacle(
        id=obstacle.id,
        name=obstacle.name,
        rect=obstacle.rect,
        material=obstacle.material,
        metadata={"color": "gris", "peso_kg": 12},
    )
    loaded = project_from_dict(project_to_dict(session.project))
    assert loaded.floors[0].obstacles[0].metadata == {
        "color": "gris",
        "peso_kg": 12,
    }


def test_legacy_minimal_floor_dict_still_parses():
    # Piso "a la antigua" (F2–F7): ni spaces ni openings ni obstacles.
    session = EditorSession()
    raw = project_to_dict(session.project)
    floor = raw["floors"][0]
    floor.pop("spaces", None)
    floor.pop("openings", None)
    floor.pop("obstacles", None)
    loaded = project_from_dict(raw)
    assert loaded.floors[0].obstacles == []
    assert loaded.floors[0].spaces == []
    assert loaded.floors[0].openings == []
