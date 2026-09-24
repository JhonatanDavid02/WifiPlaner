"""Pruebas del modelo de dominio (core)."""

import pytest

from core.band import DEFAULT_BANDS, FrequencyBand
from core.geometry import Point2D, Rect, Segment2D
from core.material import Material, MaterialAttenuationError, default_materials
from core.project import CoverageThresholds, Project
from core.radio import RadioConfiguration
from core.result import QualityClass, Verdict


# ---------------------------------------------------------------------------
# Geometría (metros)
# ---------------------------------------------------------------------------

def test_point_distance():
    a = Point2D(0.0, 0.0)
    b = Point2D(3.0, 4.0)
    assert a.distance_to(b) == pytest.approx(5.0)


def test_segment_length():
    seg = Segment2D(Point2D(0.0, 0.0), Point2D(6.0, 8.0))
    assert seg.length == pytest.approx(10.0)


def test_rect_area_and_contains():
    rect = Rect(x=0.0, y=0.0, width=5.0, height=4.0)
    assert rect.area == pytest.approx(20.0)
    assert rect.contains(Point2D(2.5, 2.0))
    assert not rect.contains(Point2D(6.0, 2.0))


def test_rect_rejects_zero_width():
    with pytest.raises(ValueError):
        Rect(x=0.0, y=0.0, width=0.0, height=4.0)


def test_rect_rejects_negative_height():
    with pytest.raises(ValueError):
        Rect(x=0.0, y=0.0, width=5.0, height=-1.0)


# ---------------------------------------------------------------------------
# Bandas
# ---------------------------------------------------------------------------

def test_default_bands_contain_three():
    assert len(DEFAULT_BANDS) == 3
    ids = [b.id for b in DEFAULT_BANDS]
    assert ids == ["band_2_4", "band_5", "band_6"]


def test_band_frequency_hz():
    band = FrequencyBand(id="x", name="X", frequency_mhz=2437.0)
    assert band.frequency_hz == pytest.approx(2.437e9)


def test_band_rejects_non_positive_frequency():
    with pytest.raises(ValueError):
        FrequencyBand(id="x", name="X", frequency_mhz=0.0)


# ---------------------------------------------------------------------------
# Materiales
# ---------------------------------------------------------------------------

def test_default_materials_count():
    assert len(default_materials()) == 7


def test_material_attenuation_lookup():
    drywall = next(m for m in default_materials() if m.id == "drywall")
    assert drywall.attenuation_for("band_2_4") == pytest.approx(3.0)
    assert drywall.attenuation_for("band_5") == pytest.approx(4.0)


def test_material_missing_band_raises():
    drywall = next(m for m in default_materials() if m.id == "drywall")
    with pytest.raises(MaterialAttenuationError):
        drywall.attenuation_for("band_6")


def test_material_has_band():
    drywall = next(m for m in default_materials() if m.id == "drywall")
    assert drywall.has_band("band_2_4")
    assert not drywall.has_band("band_6")


# ---------------------------------------------------------------------------
# Radio
# ---------------------------------------------------------------------------

def test_radio_defaults_match_legacy():
    radio = RadioConfiguration()
    assert radio.p_tx_dbm == 20.0
    assert radio.g_tx_dbi == 3.0
    assert radio.l_tx_db == 1.0
    assert radio.g_rx_dbi == 0.0
    assert radio.l_rx_db == 1.0
    assert radio.sensitivity_dbm == -75.0
    assert radio.fade_margin_db == 10.0


def test_radio_rejects_negative_fade_margin():
    with pytest.raises(ValueError):
        RadioConfiguration(fade_margin_db=-1.0)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

def test_project_defaults():
    project = Project()
    assert project.units == "m"
    assert len(project.bands) == 3
    assert len(project.materials) == 7
    assert project.radio.fade_margin_db == 10.0


def test_project_rejects_non_meter_units():
    with pytest.raises(ValueError):
        Project(units="ft")


def test_project_get_band():
    project = Project()
    band = project.get_band("band_5")
    assert band.name == "5 GHz"


def test_project_get_band_missing():
    project = Project()
    with pytest.raises(KeyError):
        project.get_band("band_unknown")


def test_project_get_material():
    project = Project()
    material = project.get_material("concrete")
    assert material.name == "Concreto"


def test_project_get_material_missing():
    project = Project()
    with pytest.raises(KeyError):
        project.get_material("kryptonite")


def test_project_empty_by_default():
    project = Project()
    assert project.access_points == []
    assert project.clients == []
    assert project.floors == []
    assert project.default_floor is None


# ---------------------------------------------------------------------------
# Umbrales / enums
# ---------------------------------------------------------------------------

def test_threshold_defaults():
    t = CoverageThresholds()
    assert t.rssi_target_dbm == -67.0
    assert t.som_aprobado_min_db == 20.0
    assert t.som_riesgo_min_db == 10.0
    assert t.excellent_min_dbm == -50.0
    assert t.good_min_dbm == -67.0
    assert t.regular_min_dbm == -75.0
    assert t.weak_min_dbm == -85.0


def test_quality_class_values():
    assert QualityClass.EXCELLENT.value == "Excelente"
    assert QualityClass.NO_COVERAGE.value == "Sin cobertura util"


def test_verdict_values():
    assert Verdict.APROBADO.value == "APROBADO"
    assert Verdict.RIESGO.value == "RIESGO"
    assert Verdict.FALLIDO.value == "FALLIDO"
