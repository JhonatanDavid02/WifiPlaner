"""Paredes, huecos y obstáculos.

Una pared es un segmento geométrico con material y espesor.
La geometría está en metros. La UI future solo dibujará esta información;
el motor la leerá para calcular atenuación por obstáculos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.geometry import Segment2D
from core.material import Material


class ObstacleKind(str, Enum):
    """Tipo de obstáculo relevante para el modelo de cobertura."""

    WALL = "wall"
    OPENING = "opening"
    FURNITURE = "furniture"
    COLUMN = "column"
    OTHER = "other"


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
    """Hueco en una pared (puerta, ventana).

    Un Opening reduce o elimina la atenuación de la pared que contiene.
    """

    id: str
    segment: Segment2D
    kind: str = "door"  # "door" | "window" | "pass_through"
    attenuation_override_db: dict[str, float] = field(default_factory=dict)
    blocks_signal: bool = False


@dataclass(frozen=True)
class Obstacle:
    """Obstáculo puntual o de mobiliario con atenuación propia.

    Attributes:
        id: Identificador estable.
        kind: Tipo (furniture, column, equipment...).
        segment: Geometría aproximada en metros.
        attenuation_db_by_band: {band_id: atenuación en dB}.
        blocks_signal: Si es False, se ignora en la simulación.
    """

    id: str
    kind: ObstacleKind
    segment: Segment2D
    attenuation_db_by_band: dict[str, float] = field(default_factory=dict)
    blocks_signal: bool = True
    material: Material | None = None
    thickness_m: float | None = None
