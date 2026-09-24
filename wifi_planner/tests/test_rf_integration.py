"""Pruebas de integración RF: paredes reales dentro del link budget.

Casos A–E de la Fase 2:
  A — sin paredes
  B — una pared
  C — dos paredes (suma)
  D — cambio de material
  E — cambio de banda (FSPL + atenuación de material)
"""

import pytest

from core.access_point import AccessPoint
from core.band import DEFAULT_BANDS
from core.geometry import Point2D, Segment2D
from core.material import default_materials
from core.project import Project
from core.radio import RadioConfiguration
from core.wall import Wall
from engine.link_budget import evaluate_link, link_budget
from engine.obstacles import trace_walls
from engine.simulator import simulate_coverage


def _band(band_id: str):
    return next(b for b in DEFAULT_BANDS if b.id == band_id)


def _material(material_id: str):
    return next(m for m in default_materials() if m.id == material_id)


def _vertical_wall(wall_id: str, x: float, material_id: str, thickness_m=None) -> Wall:
    """Pared vertical que un trayecto horizontal y=0 cruza en x."""
    return Wall(
        id=wall_id,
        segment=Segment2D(Point2D(x, -50.0), Point2D(x, 50.0)),
        material=_material(material_id),
        thickness_m=thickness_m,
    )


@pytest.fixture
def project() -> Project:
    return Project(name="RF Integration")


@pytest.fixture
def ap() -> AccessPoint:
    return AccessPoint(
        id="AP1",
        position=Point2D(0.0, 0.0),
        radio=RadioConfiguration(),
    )


# ---------------------------------------------------------------------------
# Caso A — sin paredes
# ---------------------------------------------------------------------------

def test_case_a_no_walls_matches_link_budget(project, ap):
    band = _band("band_2_4")
    point = Point2D(10.0, 0.0)

    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band,
        sample_points=[point],
        walls=[],
    )
    ev = result.evaluations[0]

    expected = link_budget(
        radio=ap.radio,
        distance_m=10.0,
        frequency_mhz=band.frequency_mhz,
        obstacle_loss_db=0.0,
    )
    assert ev.obstacle_loss_db == 0.0
    assert ev.obstacle_loss.crossings == 0
    assert ev.rx_power_dbm == expected.rx_power_dbm
    assert ev.som_db == expected.som_db
    # Golden DOCX: 10 m @ 2437 MHz con Lm=10 => P_rx = -49.19
    assert ev.rx_power_dbm == pytest.approx(-49.19, abs=0.05)


# ---------------------------------------------------------------------------
# Caso B — una pared
# ---------------------------------------------------------------------------

def test_case_b_one_wall_reduces_rssi_by_attenuation(project, ap):
    band = _band("band_2_4")
    point = Point2D(10.0, 0.0)

    result_free = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band,
        sample_points=[point],
        walls=[],
    )
    wall = _vertical_wall("w_drywall", x=5.0, material_id="drywall")
    result_wall = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band,
        sample_points=[point],
        walls=[wall],
    )

    free = result_free.evaluations[0]
    with_wall = result_wall.evaluations[0]

    assert with_wall.obstacle_loss_db == pytest.approx(3.0)  # drywall 2.4
    assert with_wall.obstacle_loss.crossings == 1
    assert with_wall.rx_power_dbm == pytest.approx(free.rx_power_dbm - 3.0, abs=0.02)
    assert with_wall.som_db == pytest.approx(free.som_db - 3.0, abs=0.02)


def test_case_b_detail_includes_wall_and_material(project, ap):
    band = _band("band_2_4")
    wall = _vertical_wall("w_drywall", x=5.0, material_id="drywall")
    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band,
        sample_points=[Point2D(10.0, 0.0)],
        walls=[wall],
    )
    detail = result.evaluations[0].obstacle_loss.detail
    assert len(detail) == 1
    assert detail[0].wall_id == "w_drywall"
    assert detail[0].material_id == "drywall"
    assert detail[0].loss_db == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Caso C — dos paredes (suma)
# ---------------------------------------------------------------------------

def test_case_c_two_walls_sum_attenuations(project, ap):
    band = _band("band_2_4")
    point = Point2D(15.0, 0.0)

    walls = [
        _vertical_wall("w_drywall", x=5.0, material_id="drywall"),
        _vertical_wall("w_concrete", x=10.0, material_id="concrete"),
    ]

    result_free = simulate_coverage(
        project=project, access_point=ap, frequency_band=band,
        sample_points=[point], walls=[],
    )
    result_walls = simulate_coverage(
        project=project, access_point=ap, frequency_band=band,
        sample_points=[point], walls=walls,
    )

    free = result_free.evaluations[0]
    with_walls = result_walls.evaluations[0]

    # drywall 3 + concrete 12 = 15 dB
    assert with_walls.obstacle_loss.crossings == 2
    assert with_walls.obstacle_loss_db == pytest.approx(15.0)
    assert with_walls.rx_power_dbm == pytest.approx(free.rx_power_dbm - 15.0, abs=0.02)

    # Orden: drywall (x=5) antes que concrete (x=10)
    trace = trace_walls(ap.position, point, walls, band.id)
    assert trace.wall_ids == ("w_drywall", "w_concrete")


# ---------------------------------------------------------------------------
# Caso D — cambio de material
# ---------------------------------------------------------------------------

def test_case_d_different_material_changes_result(project, ap):
    band = _band("band_2_4")
    point = Point2D(10.0, 0.0)

    wall_drywall = _vertical_wall("w_d", x=5.0, material_id="drywall")
    wall_concrete = _vertical_wall("w_c", x=5.0, material_id="concrete")

    r_drywall = simulate_coverage(
        project=project, access_point=ap, frequency_band=band,
        sample_points=[point], walls=[wall_drywall],
    )
    r_concrete = simulate_coverage(
        project=project, access_point=ap, frequency_band=band,
        sample_points=[point], walls=[wall_concrete],
    )

    ev_d = r_drywall.evaluations[0]
    ev_c = r_concrete.evaluations[0]

    assert ev_d.obstacle_loss_db == pytest.approx(3.0)
    assert ev_c.obstacle_loss_db == pytest.approx(12.0)
    # Misma distancia/FSPL: solo cambia L_obstacles
    assert ev_d.path_loss_db == ev_c.path_loss_db
    assert ev_c.rx_power_dbm == pytest.approx(ev_d.rx_power_dbm - 9.0, abs=0.02)


# ---------------------------------------------------------------------------
# Caso E — cambio de banda (FSPL + atenuación de material)
# ---------------------------------------------------------------------------

def test_case_e_band_change_alters_fspl_and_material_loss(project, ap):
    point = Point2D(10.0, 0.0)
    wall = _vertical_wall("w_drywall", x=5.0, material_id="drywall")

    r_24 = simulate_coverage(
        project=project, access_point=ap, frequency_band=_band("band_2_4"),
        sample_points=[point], walls=[wall],
    )
    r_5 = simulate_coverage(
        project=project, access_point=ap, frequency_band=_band("band_5"),
        sample_points=[point], walls=[wall],
    )

    ev_24 = r_24.evaluations[0]
    ev_5 = r_5.evaluations[0]

    # FSPL distinto (frecuencia distinta)
    assert ev_5.path_loss_db > ev_24.path_loss_db
    # Atenuación de material distinta: drywall 3 vs 4 dB
    assert ev_24.obstacle_loss_db == pytest.approx(3.0)
    assert ev_5.obstacle_loss_db == pytest.approx(4.0)
    # RSSI final distinto en ambos efectos
    assert ev_5.rx_power_dbm != ev_24.rx_power_dbm


# ---------------------------------------------------------------------------
# Compatibilidad Fase 1: ruta obstacle_materials_by_point sin walls
# ---------------------------------------------------------------------------

def test_phase1_materials_path_still_works(project, ap):
    band = _band("band_5")
    point = Point2D(5.0, 0.0)
    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band,
        sample_points=[point],
        obstacle_materials_by_point={point: [_material("drywall")]},
    )
    ev = result.evaluations[0]
    assert ev.obstacle_loss_db == pytest.approx(4.0)  # drywall @5 GHz


def test_walls_take_priority_over_materials_map(project, ap):
    band = _band("band_2_4")
    point = Point2D(10.0, 0.0)
    wall = _vertical_wall("w_concrete", x=5.0, material_id="concrete")

    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band,
        sample_points=[point],
        walls=[wall],
        obstacle_materials_by_point={point: [_material("drywall")]},
    )
    # Prioriza geometría real: concrete 12 dB, no drywall 3 dB del mapa
    assert result.evaluations[0].obstacle_loss_db == pytest.approx(12.0)


def test_multiple_sample_points_with_walls(project, ap):
    band = _band("band_2_4")
    walls = [
        _vertical_wall("w1", x=5.0, material_id="drywall"),
        _vertical_wall("w2", x=8.0, material_id="drywall"),
    ]
    points = [
        Point2D(3.0, 0.0),   # sin pared
        Point2D(6.0, 0.0),   # 1 pared
        Point2D(10.0, 0.0),  # 2 paredes
    ]
    result = simulate_coverage(
        project=project, access_point=ap, frequency_band=band,
        sample_points=points, walls=walls,
    )
    losses = [e.obstacle_loss_db for e in result.evaluations]
    assert losses == pytest.approx([0.0, 3.0, 6.0])
    crossings = [e.obstacle_loss.crossings for e in result.evaluations]
    assert crossings == [0, 1, 2]
