"""Grid de cobertura espacial (metros).

Fase 4: muestreo regular sobre el rectángulo del Floor para el heatmap.

Criterio de puntos (decisión documentada en docs/decisions.md):

- Puntos en múltiplos enteros de ``resolution_m`` partiendo en 0:
  ``(0,0), (r,0), (2r,0), ...`` hasta cubrir el ancho/alto.
- Si la dimensión no es múltiplo exacto de la resolución, se añade un
  punto final en el borde exacto (``width_m`` o ``height_m``) para no
  dejar una franja sin muestrear.
- Todos los puntos cumplen ``0 <= x <= width_m`` e idem para y.
- Las coordenadas son SIEMPRE metros; los píxeles no existen aquí.

Límite de estabilidad:
- ``resolution_m > 0``
- ``resolution_m >= MIN_RESOLUTION_M`` (evita congelar la app)
- ``point_count <= MAX_GRID_POINTS``
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.geometry import Point2D

# Límites de estabilidad V1 (documentados; no son física).
MIN_RESOLUTION_M = 0.05
MAX_GRID_POINTS = 100_000

_EPS = 1e-9


def _axis_points(length_m: float, resolution_m: float) -> list[float]:
    """Puntos de muestreo en un eje [0, length_m]."""
    if length_m <= 0:
        raise ValueError(f"Longitud de eje debe ser > 0 (got {length_m}).")
    count = int(math.floor(length_m / resolution_m + _EPS))
    points = [min(i * resolution_m, length_m) for i in range(count + 1)]
    if points[-1] < length_m - _EPS:
        points.append(length_m)
    return points


@dataclass(frozen=True)
class CoverageGrid:
    """Malla regular de puntos de evaluación en metros.

    Attributes:
        width_m: Ancho del piso (> 0).
        height_m: Alto del piso (> 0).
        resolution_m: Separación entre muestras en metros (> 0).
    """

    width_m: float
    height_m: float
    resolution_m: float = 0.5

    def __post_init__(self) -> None:
        if self.width_m <= 0 or self.height_m <= 0:
            raise ValueError(
                f"Dimensiones del grid deben ser > 0 "
                f"(got {self.width_m} x {self.height_m})."
            )
        if self.resolution_m <= 0:
            raise ValueError(f"Resolución debe ser > 0 (got {self.resolution_m}).")
        if self.resolution_m < MIN_RESOLUTION_M:
            raise ValueError(
                f"Resolución mínima {MIN_RESOLUTION_M} m "
                f"(got {self.resolution_m})."
            )
        if self.point_count > MAX_GRID_POINTS:
            raise ValueError(
                f"Grid demasiado grande: {self.point_count} puntos "
                f"(máximo {MAX_GRID_POINTS}). Aumenta la resolución."
            )

    @property
    def xs(self) -> list[float]:
        return _axis_points(self.width_m, self.resolution_m)

    @property
    def ys(self) -> list[float]:
        return _axis_points(self.height_m, self.resolution_m)

    @property
    def cols(self) -> int:
        return len(self.xs)

    @property
    def rows(self) -> int:
        return len(self.ys)

    @property
    def point_count(self) -> int:
        """Número exacto de puntos que generará ``points()``."""
        return len(self.xs) * len(self.ys)

    def points(self) -> list[Point2D]:
        """Todos los puntos del grid en orden (fila y creciente, luego x)."""
        result: list[Point2D] = []
        for y in self.ys:
            for x in self.xs:
                result.append(Point2D(x, y))
        return result

    def contains(self, point: Point2D) -> bool:
        return (
            -_EPS <= point.x <= self.width_m + _EPS
            and -_EPS <= point.y <= self.height_m + _EPS
        )
