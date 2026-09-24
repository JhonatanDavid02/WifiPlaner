"""Geometría 2D en unidades físicas (metros).

Los píxeles no existen en esta capa. La conversión metros → píxeles
pertenecerá exclusivamente a la futura capa de viewport/UI.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

# Tolerancia geométrica centralizada (metros / parámetros normalizados).
# Evita comparaciones exactas de float en intersecciones rayo ↔ pared.
# Usada por engine/intersection.py. Documentada en docs/decisions.md.
EPSILON_GEOMETRY = 1e-9


@dataclass(frozen=True)
class Point2D:
    """Punto físico. Unidades: metros."""

    x: float
    y: float

    def distance_to(self, other: "Point2D") -> float:
        return math.hypot(other.x - self.x, other.y - self.y)


@dataclass(frozen=True)
class Segment2D:
    """Segmento definido por dos puntos. Unidades: metros."""

    start: Point2D
    end: Point2D

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)


@dataclass(frozen=True)
class Rect:
    """Rectángulo alineado a ejes.

    Origen en la esquina inferior izquierda.
    Unidades: metros.
    """

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("Rect.width debe ser > 0 metros.")
        if self.height <= 0:
            raise ValueError("Rect.height debe ser > 0 metros.")

    @property
    def area(self) -> float:
        """Área en m²."""
        return self.width * self.height

    @property
    def min_corner(self) -> Point2D:
        return Point2D(self.x, self.y)

    @property
    def max_corner(self) -> Point2D:
        return Point2D(self.x + self.width, self.y + self.height)

    def contains(self, point: Point2D) -> bool:
        return (
            self.x <= point.x <= self.x + self.width
            and self.y <= point.y <= self.y + self.height
        )

    def center(self) -> Point2D:
        return Point2D(self.x + self.width / 2, self.y + self.height / 2)

    def edge_segments(self) -> tuple["Segment2D", ...]:
        """Los cuatro bordes del rectángulo en orden fijo (horario).

        Reutiliza ``Segment2D`` para que el motor de intersecciones
        (Fase 9) cruce trayectos contra obstáculos con la MISMA primitiva
        que contra las paredes: una sola arquitectura geométrica.
        """
        x1, y1 = self.x, self.y
        x2, y2 = self.x + self.width, self.y + self.height
        return (
            Segment2D(Point2D(x1, y1), Point2D(x2, y1)),
            Segment2D(Point2D(x2, y1), Point2D(x2, y2)),
            Segment2D(Point2D(x2, y2), Point2D(x1, y2)),
            Segment2D(Point2D(x1, y2), Point2D(x1, y1)),
        )
