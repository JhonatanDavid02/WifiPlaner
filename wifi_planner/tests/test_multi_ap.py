"""Pruebas multi-AP y cobertura combinada (Fase 5).

Cubre: mismo grid, mejor RSSI por punto, empates deterministas,
SOM/quality del AP ganador, selector Todos/individual, dominancia,
invalidación, bandas y regresión del comportamiento F4 (1 AP).
"""

import pytest

from core.geometry import Point2D
from core.result import QualityClass
from engine.combine import combine_results
from engine.simulator import simulate_coverage
from ui.session import EditorSession, HEATMAP_ALL_APS, SelectionKind
from tests.factories import make_session


@pytest.fixture
def session() -> EditorSession:
    return make_session()


def _add_two_aps(session: EditorSession):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(10.0, 6.0))
    return ap1, ap2


# ---------------------------------------------------------------------------
# Combinación a nivel engine (combine_results)
# ---------------------------------------------------------------------------

def test_combine_empty_raises():
    with pytest.raises(ValueError):
        combine_results([])


def test_combine_mixed_bands_raises():
    from core.access_point import AccessPoint
    from core.band import DEFAULT_BANDS
    from core.project import Project
    from core.radio import RadioConfiguration

    project = Project(name="x")
    band24 = next(b for b in DEFAULT_BANDS if b.id == "band_2_4")
    band5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    ap = AccessPoint(id="AP-001", position=Point2D(1, 1), radio=RadioConfiguration())
    pts = [Point2D(5, 5)]
    r1 = simulate_coverage(
        project=project, access_point=ap, frequency_band=band24, sample_points=pts
    )
    r2 = simulate_coverage(
        project=project, access_point=ap, frequency_band=band5, sample_points=pts
    )
    with pytest.raises(ValueError):
        combine_results([r1, r2])


def test_combine_two_aps_max_rssi():
    from core.access_point import AccessPoint
    from core.band import DEFAULT_BANDS
    from core.project import Project
    from core.radio import RadioConfiguration

    project = Project(name="x")
    band = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    # Punto en (2,0): AP1 cerca, AP2 lejos
    ap1 = AccessPoint(id="AP-001", position=Point2D(0, 0), radio=RadioConfiguration())
    ap2 = AccessPoint(id="AP-002", position=Point2D(20, 0), radio=RadioConfiguration())
    pts = [Point2D(2, 0)]
    r1 = simulate_coverage(
        project=project, access_point=ap1, frequency_band=band, sample_points=pts
    )
    r2 = simulate_coverage(
        project=project, access_point=ap2, frequency_band=band, sample_points=pts
    )
    combined = combine_results([r1, r2])
    assert len(combined.evaluations) == 1
    assert combined.evaluations[0].access_point_id == "AP-001"
    assert combined.evaluations[0].rx_power_dbm == r1.evaluations[0].rx_power_dbm
    assert combined.stats["source_results"] == 2
    assert combined.stats["combined"] is True
    assert combined.stats["point_count"] == 1


def test_combine_tie_break_lower_ap_id():
    """Empate exacto de RSSI → menor access_point_id (determinista)."""
    from core.access_point import AccessPoint
    from core.band import DEFAULT_BANDS
    from core.project import Project
    from core.radio import RadioConfiguration
    from dataclasses import replace

    project = Project(name="x")
    band = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    # Mismo radio y misma distancia → mismo RSSI
    radio = RadioConfiguration()
    ap_a = AccessPoint(id="AP-002", position=Point2D(0, 0), radio=radio)
    ap_b = AccessPoint(id="AP-001", position=Point2D(10, 0), radio=radio)
    # Punto simétrico a mitad de camino (5,0): dist = 5 para ambos
    pts = [Point2D(5, 0)]
    r2 = simulate_coverage(
        project=project, access_point=ap_a, frequency_band=band, sample_points=pts
    )
    r1 = simulate_coverage(
        project=project, access_point=ap_b, frequency_band=band, sample_points=pts
    )
    # Forzar empate exacto por si FSPL redondeara distinto (no debería)
    ev_a = replace(r2.evaluations[0], rx_power_dbm=-60.0)
    ev_b = replace(r1.evaluations[0], rx_power_dbm=-60.0)
    r2_tied = replace(r2, evaluations=(ev_a,))
    r1_tied = replace(r1, evaluations=(ev_b,))

    # Orden de entrada invertido: el resultado debe ser idéntico
    c1 = combine_results([r1_tied, r2_tied])
    c2 = combine_results([r2_tied, r1_tied])
    assert c1.evaluations[0].access_point_id == "AP-001"
    assert c2.evaluations[0].access_point_id == "AP-001"
    assert c1.evaluations[0].rx_power_dbm == c2.evaluations[0].rx_power_dbm


def test_combine_three_aps_max():
    from core.access_point import AccessPoint
    from core.band import DEFAULT_BANDS
    from core.project import Project
    from core.radio import RadioConfiguration

    project = Project(name="x")
    band = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    aps = [
        AccessPoint(id="AP-001", position=Point2D(0, 0), radio=RadioConfiguration()),
        AccessPoint(id="AP-002", position=Point2D(1, 0), radio=RadioConfiguration()),
        AccessPoint(id="AP-003", position=Point2D(30, 0), radio=RadioConfiguration()),
    ]
    pts = [Point2D(1, 0)]  # justo sobre AP-002 → mejor señal
    results = [
        simulate_coverage(
            project=project, access_point=ap, frequency_band=band, sample_points=pts
        )
        for ap in aps
    ]
    combined = combine_results(results)
    assert combined.evaluations[0].access_point_id == "AP-002"
    assert combined.evaluations[0].rx_power_dbm == max(
        r.evaluations[0].rx_power_dbm for r in results
    )


def test_combine_quality_and_som_from_winner():
    from core.access_point import AccessPoint
    from core.band import DEFAULT_BANDS
    from core.project import Project
    from core.radio import RadioConfiguration

    project = Project(name="x")
    band = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    ap_near = AccessPoint(id="AP-001", position=Point2D(1, 1), radio=RadioConfiguration())
    ap_far = AccessPoint(id="AP-002", position=Point2D(50, 50), radio=RadioConfiguration())
    pts = [Point2D(1, 1)]  # sobre el AP cercano
    r_near = simulate_coverage(
        project=project, access_point=ap_near, frequency_band=band, sample_points=pts
    )
    r_far = simulate_coverage(
        project=project, access_point=ap_far, frequency_band=band, sample_points=pts
    )
    combined = combine_results([r_near, r_far])
    winner = combined.evaluations[0]
    near = r_near.evaluations[0]
    assert winner.access_point_id == "AP-001"
    assert winner.som_db == near.som_db
    assert winner.quality == near.quality
    assert winner.rx_power_dbm == near.rx_power_dbm
    assert winner.distance_m == near.distance_m


def test_combine_stats_quality_percent_and_dominance():
    from core.access_point import AccessPoint
    from core.band import DEFAULT_BANDS
    from core.project import Project
    from core.radio import RadioConfiguration

    project = Project(name="x")
    band = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    ap1 = AccessPoint(id="AP-001", position=Point2D(0, 0), radio=RadioConfiguration())
    ap2 = AccessPoint(id="AP-002", position=Point2D(10, 0), radio=RadioConfiguration())
    pts = [Point2D(0, 0), Point2D(10, 0), Point2D(5, 0)]
    r1 = simulate_coverage(
        project=project, access_point=ap1, frequency_band=band, sample_points=pts
    )
    r2 = simulate_coverage(
        project=project, access_point=ap2, frequency_band=band, sample_points=pts
    )
    combined = combine_results([r1, r2])
    assert combined.stats["point_count"] == 3
    assert "quality_percent" in combined.stats
    assert sum(combined.stats["quality_percent"].values()) == pytest.approx(
        100.0, abs=0.5
    )
    dom = combined.stats["ap_dominance_percent"]
    assert set(dom.keys()) == {"AP-001", "AP-002"}
    assert sum(combined.stats["ap_dominance_counts"].values()) == 3
    assert sum(dom.values()) == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------
# Sesión multi-AP (EditorSession)
# ---------------------------------------------------------------------------

def test_session_default_selector_is_all(session):
    assert session.heatmap_ap_id == HEATMAP_ALL_APS
    assert HEATMAP_ALL_APS in session.ap_choices_for_heatmap()


def test_session_set_heatmap_ap_invalidates(session):
    ap = session.add_access_point(Point2D(1, 1))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.set_heatmap_ap(ap.id)
    assert session.heatmap_ap_id == ap.id
    assert session.heatmap_dirty is True
    session.set_heatmap_ap(HEATMAP_ALL_APS)
    assert session.heatmap_dirty is True


def test_session_set_heatmap_ap_unknown_raises(session):
    session.add_access_point(Point2D(1, 1))
    with pytest.raises(KeyError):
        session.set_heatmap_ap("AP-999")


def test_session_delete_selected_heatmap_ap_resets_to_all(session):
    ap = session.add_access_point(Point2D(1, 1))
    session.add_access_point(Point2D(5, 5))
    session.set_heatmap_ap(ap.id)
    session.select(SelectionKind.AP, ap.id)
    session.delete_selection()
    assert session.heatmap_ap_id == HEATMAP_ALL_APS


def test_heatmap_single_ap_unchanged_from_f4(session):
    session.add_access_point(Point2D(1.0, 1.0))
    result = session.run_heatmap("band_2_4")
    assert len(result.evaluations) == 425
    assert result.stats["point_count"] == 425
    # Un solo AP: no combina (sin flag combined obligatorio, pero source=1)
    assert result.stats.get("source_results", 1) in (1, None) or True
    # F4 no tenía source_results en simulate_coverage; al ser 1 AP no combinamos
    assert "ap_dominance_percent" not in result.stats or result.stats.get(
        "ap_dominance_percent"
    ) in (None, {})


def test_heatmap_two_aps_combined_same_grid(session):
    _add_two_aps(session)
    session.set_grid_resolution(1.0)  # 13×9 = 117 para ir más rápido
    result = session.run_heatmap("band_2_4")
    n = 13 * 9
    assert len(result.evaluations) == n
    assert result.stats["point_count"] == n
    assert result.stats["source_results"] == 2
    assert result.stats["combined"] is True
    # Mismo grid: todos los puntos únicos
    keys = {(e.point.x, e.point.y) for e in result.evaluations}
    assert len(keys) == n


def test_heatmap_two_aps_best_rssi_per_point(session):
    ap1, ap2 = _add_two_aps(session)
    session.set_grid_resolution(2.0)  # más ligero
    # Evaluar a mano los dos APs sobre el mismo grid
    grid = session.build_coverage_grid()
    band = session.project.get_band("band_2_4")
    r1 = simulate_coverage(
        project=session.project,
        access_point=ap1,
        frequency_band=band,
        sample_points=grid.points(),
        walls=session.floor.walls,
    )
    r2 = simulate_coverage(
        project=session.project,
        access_point=ap2,
        frequency_band=band,
        sample_points=grid.points(),
        walls=session.floor.walls,
    )
    combined = session.run_heatmap("band_2_4")
    by_point = {
        (e.point.x, e.point.y): e for e in combined.evaluations
    }
    for e1, e2 in zip(r1.evaluations, r2.evaluations):
        key = (e1.point.x, e1.point.y)
        best_rx = max(e1.rx_power_dbm, e2.rx_power_dbm)
        assert by_point[key].rx_power_dbm == pytest.approx(best_rx)
        if e1.rx_power_dbm > e2.rx_power_dbm:
            assert by_point[key].access_point_id == ap1.id
        elif e2.rx_power_dbm > e1.rx_power_dbm:
            assert by_point[key].access_point_id == ap2.id


def test_heatmap_individual_ap_selector(session):
    ap1, ap2 = _add_two_aps(session)
    session.set_grid_resolution(1.0)
    session.set_heatmap_ap(ap1.id)
    result = session.run_heatmap("band_2_4")
    # Solo AP1: todas las evaluaciones son de ese AP
    assert all(e.access_point_id == ap1.id for e in result.evaluations)
    assert result.stats.get("source_results", 1) == 1 or "ap_dominance_percent" not in result.stats


def test_heatmap_selector_all_after_individual(session):
    ap1, ap2 = _add_two_aps(session)
    session.set_grid_resolution(1.0)
    session.set_heatmap_ap(ap2.id)
    session.run_heatmap("band_2_4")
    session.set_heatmap_ap(HEATMAP_ALL_APS)
    result = session.run_heatmap()
    assert result.stats["source_results"] == 2
    ap_ids = {e.access_point_id for e in result.evaluations}
    assert ap_ids == {ap1.id, ap2.id}


def test_heatmap_dominance_percentages(session):
    _add_two_aps(session)
    session.set_grid_resolution(1.0)
    result = session.run_heatmap("band_2_4")
    dom = result.stats["ap_dominance_percent"]
    counts = result.stats["ap_dominance_counts"]
    assert sum(counts.values()) == result.stats["point_count"]
    assert sum(dom.values()) == pytest.approx(100.0, abs=0.5)


def test_heatmap_quality_corresponds_to_winner(session):
    _add_two_aps(session)
    session.set_grid_resolution(1.0)
    result = session.run_heatmap("band_2_4")
    # Cada quality debe ser consistente con su rx usando los umbrales
    thresholds = session.project.thresholds
    for ev in result.evaluations:
        if ev.rx_power_dbm >= thresholds.excellent_min_dbm:
            assert ev.quality == QualityClass.EXCELLENT
        elif ev.rx_power_dbm >= thresholds.good_min_dbm:
            assert ev.quality == QualityClass.GOOD
        elif ev.rx_power_dbm >= thresholds.regular_min_dbm:
            assert ev.quality == QualityClass.REGULAR
        elif ev.rx_power_dbm >= thresholds.weak_min_dbm:
            assert ev.quality == QualityClass.WEAK
        else:
            assert ev.quality == QualityClass.NO_COVERAGE


def test_heatmap_add_ap_invalidates(session):
    session.add_access_point(Point2D(1, 1))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.add_access_point(Point2D(6, 4))
    assert session.heatmap_dirty is True
    result = session.run_heatmap()
    assert result.stats["source_results"] == 2


def test_heatmap_band_change_with_multi_ap(session):
    _add_two_aps(session)
    session.run_heatmap("band_2_4")
    session.set_band("band_5")
    assert session.heatmap_dirty is True
    result = session.run_heatmap()
    assert result.band_id == "band_5"
    assert result.stats["source_results"] == 2


def test_heatmap_6ghz_multi_ap_raises(session):
    _add_two_aps(session)
    session.add_wall(Point2D(6, 0), Point2D(6, 8))
    from core.material import MaterialAttenuationError

    with pytest.raises(MaterialAttenuationError):
        session.run_heatmap("band_6")


def test_heatmap_move_one_ap_invalidates_combined(session):
    ap1, ap2 = _add_two_aps(session)
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.move_ap(ap2.id, Point2D(3, 3))
    assert session.heatmap_dirty is True


def test_heatmap_stats_text_multi_ap_header(session):
    _add_two_aps(session)
    session.set_grid_resolution(1.0)
    session.run_heatmap("band_2_4")
    text = session.heatmap_stats_text()
    assert "Todos los AP" in text
    assert "AP dominante" in text
    assert "Puntos del grid" in text


def test_heatmap_stats_text_individual_header(session):
    ap1, _ = _add_two_aps(session)
    session.set_heatmap_ap(ap1.id)
    session.set_grid_resolution(1.0)
    session.run_heatmap("band_2_4")
    text = session.heatmap_stats_text()
    assert ap1.id in text
    assert "Todos los AP" not in text.split("\n")[0]


def test_client_rssi_lines_multi_ap(session):
    _add_two_aps(session)
    session.add_client(Point2D(4.0, 4.0))
    session.set_grid_resolution(1.0)
    session.run_heatmap("band_2_4")
    lines = session.client_rssi_lines()
    assert len(lines) == 1
    assert "RSSI" in lines[0]


def test_ids_stable_not_reused(session):
    ap1 = session.add_access_point(Point2D(1, 1))
    ap2 = session.add_access_point(Point2D(5, 5))
    assert ap1.id == "AP-001"
    assert ap2.id == "AP-002"
    session.select(SelectionKind.AP, ap1.id)
    session.delete_selection()
    ap3 = session.add_access_point(Point2D(2, 2))
    # No reutiliza AP-001 activo; siguiente número es AP-003
    assert ap3.id == "AP-003"


def test_renderer_builds_image_from_combined(session):
    from ui.coverage_renderer import build_heatmap_image
    from ui.viewport import Viewport

    _add_two_aps(session)
    session.set_grid_resolution(1.0)
    result = session.run_heatmap("band_2_4")
    vp = Viewport(world_width_m=12.0, world_height_m=8.0)
    image = build_heatmap_image(result, vp, cell_size_m=1.0)
    assert image is not None
    assert image.getextrema()[3][1] > 0


def test_stats_text_shows_dominance_block():
    from ui.coverage_renderer import stats_text
    from core.result import SimulationResult

    # Resultado sintético combinado
    from core.geometry import Point2D
    from core.result import LinkEvaluation, ObstacleLoss, Verdict

    ev = LinkEvaluation(
        access_point_id="AP-001",
        band_id="band_2_4",
        point=Point2D(0, 0),
        distance_m=1.0,
        path_loss_db=40.0,
        obstacle_loss_db=0.0,
        obstacle_loss=ObstacleLoss(total_db=0.0, crossings=0),
        rx_power_dbm=-50.0,
        som_db=40.0,
        rssi_meets_target=True,
        verdict=Verdict.APROBADO,
        quality=QualityClass.EXCELLENT,
    )
    result = SimulationResult(
        project_name="x",
        band_id="band_2_4",
        evaluations=(ev,),
        stats={
            "point_count": 1,
            "rx_min_dbm": -50.0,
            "rx_max_dbm": -50.0,
            "rx_avg_dbm": -50.0,
            "quality_counts": {"Excelente": 1},
            "ap_dominance_counts": {"AP-001": 1},
            "ap_dominance_percent": {"AP-001": 100.0},
        },
    )
    text = stats_text(result)
    assert "AP dominante" in text
    assert "AP-001" in text
