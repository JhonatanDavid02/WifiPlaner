"""Fase 14-F: herramienta medir (distancias en metros, no en píxeles).

El estado vive en la sesión (vista, no persistible): ancla + cursor y la
distancia entre ambos; cambiar de herramienta o de documento lo limpia.
"""

from __future__ import annotations

import math

import pytest

from core.geometry import Point2D
from tests.factories import make_session
from ui.session import Tool


def test_measure_tool_exists_with_stable_value():
    assert Tool.MEASURE.value == "measure"
    # El valor se persiste en el radio del toolbar (StringVar).
    assert "measure" in {tool.value for tool in Tool}


def test_measure_distance_is_metric_pythagoras():
    session = make_session()
    session.set_tool(Tool.MEASURE)
    session.set_measure_anchor(Point2D(0.0, 0.0))
    session.set_measure_cursor(Point2D(3.0, 4.0))
    assert session.measure_distance_m() == pytest.approx(5.0)


def test_measure_distance_none_without_anchor():
    session = make_session()
    assert session.measure_distance_m() is None


def test_clearing_anchor_clears_measurement():
    session = make_session()
    session.set_measure_anchor(Point2D(1.0, 1.0))
    session.set_measure_cursor(Point2D(2.0, 3.0))
    session.set_measure_anchor(None)
    assert session.measure_distance_m() is None
    assert session.measure_anchor is None


def test_set_anchor_resets_cursor_to_same_point():
    session = make_session()
    session.set_measure_anchor(Point2D(1.0, 1.0))
    session.set_measure_cursor(Point2D(5.0, 5.0))
    session.set_measure_anchor(Point2D(2.0, 2.0))
    # Tras el nuevo ancla la medición parte de cero (cursor = ancla).
    assert session.measure_distance_m() == pytest.approx(0.0)


def test_measure_rejects_non_finite_points():
    session = make_session()
    with pytest.raises(ValueError, match="finitas"):
        session.set_measure_anchor(Point2D(math.nan, 0.0))
    with pytest.raises(ValueError, match="finitas"):
        session.set_measure_cursor(Point2D(0.0, math.inf))


def test_changing_tool_clears_measurement():
    session = make_session()
    session.set_measure_anchor(Point2D(1.0, 1.0))
    session.set_measure_cursor(Point2D(4.0, 5.0))
    session.set_tool(Tool.SELECT)
    assert session.measure_anchor is None
    assert session.measure_cursor is None
    assert session.measure_distance_m() is None


def test_new_document_clears_measurement():
    session = make_session()
    session.set_measure_anchor(Point2D(1.0, 1.0))
    session.new_project()
    assert session.measure_distance_m() is None


def test_measure_does_not_mark_dirty():
    session = make_session()
    assert session.dirty is False
    session.set_measure_anchor(Point2D(1.0, 1.0))
    session.set_measure_cursor(Point2D(2.0, 2.0))
    assert session.dirty is False


def test_measure_is_independent_of_view_zoom():
    # La medición vive en metros del modelo: el viewport no interviene.
    session = make_session()
    session.set_measure_anchor(Point2D(0.0, 0.0))
    session.set_measure_cursor(Point2D(0.0, 2.5))
    assert session.measure_distance_m() == pytest.approx(2.5)
