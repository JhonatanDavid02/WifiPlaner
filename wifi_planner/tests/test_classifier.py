"""Pruebas de clasificación: SOM, RSSI objetivo y calidad de cobertura."""

import pytest

from core.project import CoverageThresholds
from core.result import QualityClass, Verdict
from engine.classifier import classify_quality, classify_som, meets_rssi_target


@pytest.fixture
def thresholds() -> CoverageThresholds:
    return CoverageThresholds()


# ---------------------------------------------------------------------------
# Clasificación SOM (decisión D: >= 20 APROBADO, >= 10 RIESGO, si no FALLIDO)
# ---------------------------------------------------------------------------

def test_som_aprobado_at_20(thresholds):
    assert classify_som(20.0, thresholds) == Verdict.APROBADO


def test_som_aprobado_above_20(thresholds):
    assert classify_som(25.5, thresholds) == Verdict.APROBADO


def test_som_riesgo_just_below_20(thresholds):
    assert classify_som(19.99, thresholds) == Verdict.RIESGO


def test_som_riesgo_at_10(thresholds):
    assert classify_som(10.0, thresholds) == Verdict.RIESGO


def test_som_fallido_below_10(thresholds):
    assert classify_som(9.99, thresholds) == Verdict.FALLIDO


def test_som_fallido_negative(thresholds):
    assert classify_som(-5.0, thresholds) == Verdict.FALLIDO


# ---------------------------------------------------------------------------
# RSSI objetivo (decisión C: estrictamente > -67 dBm)
# ---------------------------------------------------------------------------

def test_rssi_at_target_is_false(thresholds):
    """En el umbral exacto -67 NO cumple (comparación estricta)."""
    assert meets_rssi_target(-67.0, thresholds) is False


def test_rssi_above_target_is_true(thresholds):
    assert meets_rssi_target(-66.99, thresholds) is True


def test_rssi_below_target_is_false(thresholds):
    assert meets_rssi_target(-67.01, thresholds) is False


def test_rssi_much_above_is_true(thresholds):
    assert meets_rssi_target(-43.17, thresholds) is True


# ---------------------------------------------------------------------------
# Clases de cobertura
# ---------------------------------------------------------------------------

def test_quality_excellent(thresholds):
    assert classify_quality(-50.0, thresholds) == QualityClass.EXCELLENT


def test_quality_excellent_higher(thresholds):
    assert classify_quality(-40.0, thresholds) == QualityClass.EXCELLENT


def test_quality_good_boundary(thresholds):
    assert classify_quality(-67.0, thresholds) == QualityClass.GOOD


def test_quality_regular_boundary(thresholds):
    assert classify_quality(-75.0, thresholds) == QualityClass.REGULAR


def test_quality_weak_boundary(thresholds):
    assert classify_quality(-85.0, thresholds) == QualityClass.WEAK


def test_quality_no_coverage_below_weak(thresholds):
    assert classify_quality(-85.01, thresholds) == QualityClass.NO_COVERAGE


def test_quality_no_coverage_very_low(thresholds):
    assert classify_quality(-100.0, thresholds) == QualityClass.NO_COVERAGE


# ---------------------------------------------------------------------------
# Umbrales configurables (no hardcodeados)
# ---------------------------------------------------------------------------

def test_custom_thresholds_are_respected():
    custom = CoverageThresholds(
        som_aprobado_min_db=15.0,
        som_riesgo_min_db=5.0,
        excellent_min_dbm=-45.0,
        rssi_target_dbm=-60.0,
    )
    assert classify_som(15.0, custom) == Verdict.APROBADO
    assert classify_som(5.0, custom) == Verdict.RIESGO
    assert classify_som(4.99, custom) == Verdict.FALLIDO
    assert classify_quality(-45.0, custom) == QualityClass.EXCELLENT
    assert meets_rssi_target(-60.0, custom) is False
    assert meets_rssi_target(-59.99, custom) is True
