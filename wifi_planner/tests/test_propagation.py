"""Pruebas de propagación: longitud de onda y FSPL."""

import math

import pytest

from engine.propagation import wavelength_m, path_loss_fspl_db


# ---------------------------------------------------------------------------
# Longitud de onda
# ---------------------------------------------------------------------------

def test_wavelength_2_4_ghz():
    # λ = 3e8 / 2.4e9 = 0.125 m = 12.5 cm
    assert wavelength_m(2_400_000_000) == pytest.approx(0.125, abs=1e-9)


def test_wavelength_5_ghz():
    # λ = 3e8 / 5e9 = 0.06 m = 6 cm
    assert wavelength_m(5_000_000_000) == pytest.approx(0.06, abs=1e-9)


def test_wavelength_rejects_zero():
    with pytest.raises(ValueError):
        wavelength_m(0)


def test_wavelength_rejects_negative():
    with pytest.raises(ValueError):
        wavelength_m(-1_000_000)


# ---------------------------------------------------------------------------
# FSPL
# ---------------------------------------------------------------------------

def test_fspl_known_value_10m_2437mhz():
    # 20*log10(10) + 20*log10(2437) - 27.55 = 60.19
    result = path_loss_fspl_db(10.0, 2437.0)
    assert result == pytest.approx(60.19, abs=0.01)


def test_fspl_known_value_10m_5180mhz():
    # 20*log10(10) + 20*log10(5180) - 27.55 = 66.74
    result = path_loss_fspl_db(10.0, 5180.0)
    assert result == pytest.approx(66.74, abs=0.01)


def test_fspl_increases_with_distance():
    assert path_loss_fspl_db(20.0, 2437.0) > path_loss_fspl_db(10.0, 2437.0)


def test_fspl_increases_with_frequency():
    assert path_loss_fspl_db(10.0, 5180.0) > path_loss_fspl_db(10.0, 2437.0)


def test_fspl_formula_exact():
    d, f = 7.5, 3000.0
    expected = 20 * math.log10(d) + 20 * math.log10(f) - 27.55
    assert path_loss_fspl_db(d, f) == pytest.approx(expected, abs=0.01)


def test_fspl_rejects_zero_distance():
    with pytest.raises(ValueError):
        path_loss_fspl_db(0.0, 2437.0)


def test_fspl_rejects_negative_distance():
    with pytest.raises(ValueError):
        path_loss_fspl_db(-5.0, 2437.0)


def test_fspl_rejects_zero_frequency():
    with pytest.raises(ValueError):
        path_loss_fspl_db(10.0, 0.0)


def test_fspl_rejects_negative_frequency():
    with pytest.raises(ValueError):
        path_loss_fspl_db(10.0, -2437.0)
