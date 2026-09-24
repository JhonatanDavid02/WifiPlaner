"""Intersección trayecto (rayo) ↔ segmento de pared.

Convención determinista de "atravesar" (Fase 2, ver docs/decisions.md):

- Solo cuenta una intersección **interior estricta** de ambos segmentos:
  los parámetros normalizados ``t`` (trayecto) y ``u`` (pared) deben
  cumplir ``EPSILON < t < 1 - EPSILON`` e idem para ``u``.
- Tocar únicamente un extremo de la pared NO cuenta (evita doble conteo
  en esquinas compartidas por dos paredes).
- Tocar el origen o el destino del trayecto NO cuenta (AP o punto de
  evaluación exactamente sobre una pared).
- Segmentos paralelos o colineales/coincidentes NO cuentan (sin cruce
  propio único y determinista).
- Tolerancia: ``core.geometry.EPSILON_GEOMETRY`` (1e-9). No se usan
  comparaciones exactas de float.

Método: paráétrico con productos cruzados (estable para segmentos
finitos; los parámetros t/u son adimensionales en [0, 1]).
"""

from __future__ import annotations

from core.geometry import EPSILON_GEOMETRY, Point2D, Segment2D


def segment_crossing_parameters(
    path: Segment2D,
    wall: Segment2D,
    epsilon: float = EPSILON_GEOMETRY,
) -> tuple[float, float] | None:
    """Parámetros (t, u) del cruce interior estricto entre dos segmentos.

    El punto de cruce es ``path.start + t * (path.end - path.start)`` y
    también ``wall.start + u * (wall.end - wall.start)``.

    Args:
        path: Trayecto AP → punto (segmento).
        wall: Segmento de pared.
        epsilon: Tolerancia (por defecto EPSILON_GEOMETRY).

    Returns:
        ``(t, u)`` si hay cruce interior estricto de ambos segmentos;
        ``None`` si no hay cruce, son paralelos/coincidentes, o el cruce
        cae en un extremo (dentro de epsilon).
    """
    dx = path.end.x - path.start.x
    dy = path.end.y - path.start.y
    ex = wall.end.x - wall.start.x
    ey = wall.end.y - wall.start.y

    # Denominador = cruce 2D de los vectores dirección (path × wall).
    # ≈ 0 => paralelos o colineales (incluye segmentos degenerados).
    denom = dx * ey - dy * ex
    if abs(denom) <= epsilon:
        return None

    rx = wall.start.x - path.start.x
    ry = wall.start.y - path.start.y

    t = (rx * ey - ry * ex) / denom
    u = (rx * dy - ry * dx) / denom

    # Interior estricto con tolerancia: extremos excluidos.
    if epsilon < t < 1.0 - epsilon and epsilon < u < 1.0 - epsilon:
        return (t, u)
    return None


def segments_cross(
    path: Segment2D,
    wall: Segment2D,
    epsilon: float = EPSILON_GEOMETRY,
) -> bool:
    """True si el trayecto atraviesa la pared (cruce interior estricto)."""
    return segment_crossing_parameters(path, wall, epsilon) is not None


def crossing_distance_from_start(
    path: Segment2D,
    wall: Segment2D,
    epsilon: float = EPSILON_GEOMETRY,
) -> float | None:
    """Distancia en metros desde el inicio del trayecto hasta el cruce.

    Returns:
        Distancia (> 0) o ``None`` si no hay cruce interior.
    """
    params = segment_crossing_parameters(path, wall, epsilon)
    if params is None:
        return None
    t = params[0]
    return t * path.length


def crossing_point(
    path: Segment2D,
    wall: Segment2D,
    epsilon: float = EPSILON_GEOMETRY,
) -> Point2D | None:
    """Punto físico (metros) del cruce interior, o ``None``."""
    params = segment_crossing_parameters(path, wall, epsilon)
    if params is None:
        return None
    t = params[0]
    return Point2D(
        path.start.x + t * (path.end.x - path.start.x),
        path.start.y + t * (path.end.y - path.start.y),
    )
