"""Paredes y huecos (openings).

Una pared es un segmento geométrico con material y espesor.
La geometría está en metros. La UI solo dibuja esta información;
el motor la lee para calcular atenuación por obstáculos.

Fase 8: los openings (puertas/ventanas) son muro-relativos
(decisión BF): viven en ``Floor.openings`` referenciando ``wall_id``
por offsets métricos desde ``wall.segment.start``.

Fase 9: los obstáculos de mobiliario NO viven aquí — son una entidad
independiente por piso en ``core/obstacle.py`` (decisión BL; el antiguo
scaffold ``Obstacle`` de esta fase 1 era código muerto sin consumidores).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from core.geometry import Point2D, Segment2D
from core.material import Material

# Tipos de apertura (metadato arquitectónico/visual). El tipo NO es una
# fórmula RF distinta: la pérdida de la sección la da el override por
# banda o 0 dB (decisión BG).
OPENING_KINDS: tuple[str, ...] = ("door", "window", "pass_through")

# Límites de una apertura (decisión BK; centralizados en core/).
MIN_OPENING_LENGTH_M = 0.01
MAX_OPENING_LENGTH_M = 1_000.0
MAX_OPENING_ATTENUATION_DB = 200.0

# Longitud por defecto al crear desde el editor (decisión BK).
DEFAULT_OPENING_LENGTH_M: dict[str, float] = {
    "door": 0.9,
    "window": 1.2,
    "pass_through": 1.0,
}


@dataclass(frozen=True)
class Wall:
    """Pared u obstáculo lineal.

    Attributes:
        id: Identificador estable.
        segment: Geometría del segmento en metros.
        material: Material de la pared.
        thickness_m: Espesor en metros. Si es None se usa el espesor
            por defecto del material.
        id_space_from / id_space_to: Espacios separados por la pared (opcional).
        blocks_signal: Si es False, el motor la ignora (ej. malla decorativa).
    """

    id: str
    segment: Segment2D
    material: Material
    thickness_m: float | None = None
    id_space_from: str | None = None
    id_space_to: str | None = None
    blocks_signal: bool = True

    @property
    def effective_thickness(self) -> float:
        if self.thickness_m is not None:
            return self.thickness_m
        return self.material.thickness_default_m


@dataclass(frozen=True)
class Opening:
    """Hueco en una pared (puerta, ventana, paso).

    Representación muro-relativa (Fase 8, decisión BF): la posición es
    la distancia métrica desde ``wall.segment.start`` hacia
    ``wall.segment.end``. La geometría en el mundo se deriva con
    ``opening_segment(wall, opening)`` — no se almacena dos veces.

    Semántica RF (decisión BG): un cruce del rayo dentro del hueco
    **sustituye** la atenuación de la pared por
    ``attenuation_override_db.get(band_id, 0.0)`` (sección abierta
    por defecto). Nunca se suma a la atenuación del material.

    Attributes:
        id: Identificador estable.
        wall_id: Id de la pared que contiene el hueco (referencia).
        start_offset_m: Distancia (m) del extremo inicial sobre la pared.
        end_offset_m: Distancia (m) del extremo final (> start).
        kind: "door" | "window" | "pass_through" (metadato visual).
        attenuation_override_db: {band_id: pérdida de la sección en dB}.
            Si la banda evaluada no está, la sección vale 0 dB.
    """

    id: str
    wall_id: str
    start_offset_m: float
    end_offset_m: float
    kind: str = "door"
    attenuation_override_db: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Opening.id debe ser un texto no vacío.")
        if not isinstance(self.wall_id, str) or not self.wall_id.strip():
            raise ValueError("Opening.wall_id debe ser un texto no vacío.")
        if self.kind not in OPENING_KINDS:
            raise ValueError(
                f"Opening.kind no soportado: {self.kind!r} "
                f"(permitidos: {', '.join(OPENING_KINDS)})."
            )
        for name in ("start_offset_m", "end_offset_m"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Opening.{name} debe ser un número.")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"Opening.{name} debe ser finito.")
            object.__setattr__(self, name, number)
        if self.start_offset_m < 0:
            raise ValueError(
                f"Opening.start_offset_m no puede ser negativo "
                f"(got {self.start_offset_m})."
            )
        length = self.end_offset_m - self.start_offset_m
        if length < MIN_OPENING_LENGTH_M:
            raise ValueError(
                f"Opening '{self.id}': la longitud debe ser ≥ "
                f"{MIN_OPENING_LENGTH_M:g} m (got {length:g})."
            )
        if length > MAX_OPENING_LENGTH_M:
            raise ValueError(
                f"Opening '{self.id}': la longitud debe ser ≤ "
                f"{MAX_OPENING_LENGTH_M:g} m (got {length:g})."
            )
        if not isinstance(self.attenuation_override_db, dict):
            raise ValueError("Opening.attenuation_override_db debe ser un dict.")
        overrides: dict[str, float] = {}
        for band_id, raw in self.attenuation_override_db.items():
            if not isinstance(band_id, str) or not band_id:
                raise ValueError(
                    "Opening.attenuation_override_db: las claves deben ser "
                    "band ids no vacíos."
                )
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(
                    f"Opening.attenuation_override_db[{band_id!r}] debe ser "
                    "un número."
                )
            loss = float(raw)
            if not math.isfinite(loss) or not (0.0 <= loss <= MAX_OPENING_ATTENUATION_DB):
                raise ValueError(
                    f"Opening.attenuation_override_db[{band_id!r}] debe estar "
                    f"en [0, {MAX_OPENING_ATTENUATION_DB:g}] dB (got {raw!r})."
                )
            overrides[band_id] = loss
        object.__setattr__(self, "attenuation_override_db", overrides)

    @property
    def length_m(self) -> float:
        """Longitud del hueco en metros."""
        return self.end_offset_m - self.start_offset_m


def wall_point_at_offset(wall: Wall, offset_m: float) -> Point2D:
    """Punto físico (m) a ``offset_m`` desde el inicio de la pared.

    El offset se recorta al intervalo ``[0, longitud]`` (defensivo:
    sesión y persistencia ya garantizan que el hueco cabe en la pared).
    """
    length = wall.segment.length
    if length <= 0:
        raise ValueError(f"Wall '{wall.id}': segmento degenerado (longitud 0).")
    clamped = min(max(float(offset_m), 0.0), length)
    ux = (wall.segment.end.x - wall.segment.start.x) / length
    uy = (wall.segment.end.y - wall.segment.start.y) / length
    return Point2D(
        wall.segment.start.x + ux * clamped,
        wall.segment.start.y + uy * clamped,
    )


def opening_segment(wall: Wall, opening: Opening) -> Segment2D:
    """Segmento (m en el mundo) de un hueco sobre su pared.

    Raises:
        ValueError: si el hueco no pertenece a la pared o el segmento
            de la pared es degenerado.
    """
    if opening.wall_id != wall.id:
        raise ValueError(
            f"Opening '{opening.id}' no pertenece a la pared '{wall.id}'."
        )
    return Segment2D(
        wall_point_at_offset(wall, opening.start_offset_m),
        wall_point_at_offset(wall, opening.end_offset_m),
    )


def group_openings_by_wall(
    openings: Iterable[Opening],
) -> dict[str, tuple[Opening, ...]]:
    """Agrupa openings por ``wall_id`` en orden canónico ``(start, id)``.

    El orden es independiente de la inserción (decisión BG): con él se
    determina qué override aplica cuando los openings se solapan.
    """
    grouped: dict[str, list[Opening]] = {}
    for opening in openings:
        grouped.setdefault(opening.wall_id, []).append(opening)
    return {
        wall_id: tuple(sorted(items, key=lambda o: (o.start_offset_m, o.id)))
        for wall_id, items in grouped.items()
    }
