"""Pruebas del simulador (Fase 1: puntos individuales y combinación)."""

import pytest

from core.access_point import AccessPoint
from core.client import ClientDevice
from core.geometry import Point2D
from core.project import CoverageThresholds, Project
from core.radio import RadioConfiguration
from engine.simulator import simulate_coverage
from engine.combine import combine_results


@pytest.fixture
def project() -> Project:
    return Project(name="Test Project")


@pytest.fixture
def ap() -> AccessPoint:
    return AccessPoint(
        id="AP1",
        position=Point2D(0.0, 0.0),
        radio=RadioConfiguration(),
    )


def test_simulate_requires_points(project, ap):
    with pytest.raises(ValueError):
        simulate_coverage(project=project, access_point=ap, frequency_band=None)


def test_simulate_single_point(project, ap):
    from core.band import DEFAULT_BANDS

    band_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    point = Point2D(5.0, 0.0)

    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band_5,
        sample_points=[point],
    )

    assert len(result.evaluations) == 1
    ev = result.evaluations[0]
    assert ev.access_point_id == "AP1"
    assert ev.band_id == "band_5"
    assert ev.distance_m == pytest.approx(5.0)
    assert result.stats["point_count"] == 1


def test_simulate_with_client(project, ap):
    from core.band import DEFAULT_BANDS

    band_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    client = ClientDevice(id="c1", position=Point2D(3.0, 4.0), sensitivity_dbm=-75.0)

    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band_5,
        client=client,
    )

    assert len(result.evaluations) == 1
    assert result.evaluations[0].distance_m == pytest.approx(5.0)


def test_simulate_multiple_points_stats(project, ap):
    from core.band import DEFAULT_BANDS

    band_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")
    points = [
        Point2D(2.0, 0.0),
        Point2D(5.0, 0.0),
        Point2D(10.0, 0.0),
        Point2D(20.0, 0.0),
    ]

    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band_5,
        sample_points=points,
    )

    assert result.stats["point_count"] == 4
    assert result.stats["rx_max_dbm"] >= result.stats["rx_min_dbm"]
    assert 0.0 <= result.stats["coverage_ratio"] <= 1.0


def test_client_sensitivity_overrides_radio(project, ap):
    from core.band import DEFAULT_BANDS
    from dataclasses import replace

    band_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")

    # Cliente con sensibilidad peor que el AP
    client = ClientDevice(id="c1", position=Point2D(5.0, 0.0), sensitivity_dbm=-80.0)

    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band_5,
        client=client,
    )

    ev = result.evaluations[0]
    # SOM = P_rx - (-80) => mayor que con -75
    assert ev.som_db > 0


# ---------------------------------------------------------------------------
# Combinación multi-AP (estructura Fase 1)
# ---------------------------------------------------------------------------

def test_combine_two_aps(project):
    from core.band import DEFAULT_BANDS

    band_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")

    ap1 = AccessPoint(id="AP1", position=Point2D(0.0, 0.0), radio=RadioConfiguration())
    ap2 = AccessPoint(id="AP2", position=Point2D(10.0, 0.0), radio=RadioConfiguration())

    r1 = simulate_coverage(
        project=project,
        access_point=ap1,
        frequency_band=band_5,
        sample_points=[Point2D(2.0, 0.0)],
    )
    r2 = simulate_coverage(
        project=project,
        access_point=ap2,
        frequency_band=band_5,
        sample_points=[Point2D(2.0, 0.0)],
    )

    combined = combine_results([r1, r2])

    # Mismo punto: gana la señal más fuerte (AP más cercano => AP1 a 2m vs AP2 a 8m)
    assert len(combined.evaluations) == 1
    winner = combined.evaluations[0]
    assert winner.access_point_id == "AP1"
    assert combined.stats["source_results"] == 2


def test_combine_empty_raises(project):
    with pytest.raises(ValueError):
        combine_results([])


def test_combine_mixed_bands_raises(project):
    from core.band import DEFAULT_BANDS

    band_24 = next(b for b in DEFAULT_BANDS if b.id == "band_2_4")
    band_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")

    ap = AccessPoint(id="AP1", position=Point2D(0.0, 0.0), radio=RadioConfiguration())
    point = [Point2D(5.0, 0.0)]

    r1 = simulate_coverage(
        project=project, access_point=ap, frequency_band=band_24, sample_points=point
    )
    r2 = simulate_coverage(
        project=project, access_point=ap, frequency_band=band_5, sample_points=point
    )

    with pytest.raises(ValueError):
        combine_results([r1, r2])
