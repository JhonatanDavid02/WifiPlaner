"""Fase 14-E: rejilla configurable y snap a rejilla (preferencias de vista).

La rejilla visible y el snap son estado del editor NO persistido: no
marcan ``dirty`` ni tocan el schema v1; la resolución del grid RF
(``grid_resolution_m``) es otra cosa y sigue intacta.
"""

from __future__ import annotations

import math

import pytest

from core.geometry import Point2D
from tests.factories import make_session
from ui.session import GRID_STEP_CHOICES, snap_point_to_grid


def test_grid_defaults():
    session = make_session()
    assert session.grid_step_m == pytest.approx(0.5)
    assert session.snap_to_grid is True
    assert GRID_STEP_CHOICES == (0.1, 0.25, 0.5, 1.0)
    assert session.grid_step_m in GRID_STEP_CHOICES


def test_set_grid_step_valid():
    session = make_session()
    session.set_grid_step(0.25)
    assert session.grid_step_m == pytest.approx(0.25)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, 1001.0])
def test_set_grid_step_invalid_rejected(bad):
    session = make_session()
    with pytest.raises(ValueError):
        session.set_grid_step(bad)
    # El valor anterior queda intacto.
    assert session.grid_step_m == pytest.approx(0.5)


def test_set_snap_to_grid_toggles():
    session = make_session()
    session.set_snap_to_grid(False)
    assert session.snap_to_grid is False
    session.set_snap_to_grid(True)
    assert session.snap_to_grid is True


def test_grid_prefs_do_not_mark_dirty():
    session = make_session()
    assert session.dirty is False
    session.set_grid_step(1.0)
    session.set_snap_to_grid(False)
    assert session.dirty is False


def test_grid_prefs_survive_new_document():
    session = make_session()
    session.set_grid_step(0.1)
    session.set_snap_to_grid(False)
    session.new_project()
    assert session.grid_step_m == pytest.approx(0.1)
    assert session.snap_to_grid is False


def test_snap_point_to_grid_math():
    snapped = snap_point_to_grid(Point2D(1.23, 4.56), 0.5)
    assert snapped.x == pytest.approx(1.0)
    assert snapped.y == pytest.approx(4.5)


def test_snap_point_to_grid_negative_coordinates():
    snapped = snap_point_to_grid(Point2D(-0.3, 2.7), 0.5)
    assert snapped.x == pytest.approx(-0.5)
    assert snapped.y == pytest.approx(2.5)


def test_snap_point_identity_when_already_on_grid():
    snapped = snap_point_to_grid(Point2D(2.0, 3.5), 0.5)
    assert snapped.x == pytest.approx(2.0)
    assert snapped.y == pytest.approx(3.5)


def test_snap_point_to_grid_fine_step():
    snapped = snap_point_to_grid(Point2D(0.13, 0.97), 0.1)
    assert snapped.x == pytest.approx(0.1)
    assert snapped.y == pytest.approx(1.0)


def test_snap_point_to_grid_invalid_step():
    for bad in (0.0, -0.5, math.nan):
        with pytest.raises(ValueError):
            snap_point_to_grid(Point2D(1.0, 1.0), bad)
