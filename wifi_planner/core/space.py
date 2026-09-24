"""Espacios (salas/zonas) y pisos."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.geometry import Rect


@dataclass
class Space:
    """Espacio interior (sala, pasillo, almacén...).

    Attributes:
        id: Identificador estable.
        name: Nombre legible.
        rect: Rectángulo del espacio en metros.
        function: Función zonal opcional (ej. "lectura", "almacen").
        metadata: Datos adicionales libres.
    """

    id: str
    name: str
    rect: Rect
    function: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def area(self) -> float:
        """Área en m²."""
        return self.rect.area


@dataclass
class Floor:
    """Piso del edificio.

    V1 modela un solo piso por proyecto, pero la estructura permite
    múltiples pisos sin cambiar el dominio.

    Attributes:
        id: Identificador estable.
        name: Nombre legible.
        level: Índice del piso (0 = planta baja).
        spaces: Espacios del piso.
        walls: Paredes del piso.
        obstacles: Obstáculos del piso.
        openings: Huecos del piso.
        elevation_m: Cota vertical en metros (para futuros pisos/3D).
        metadata: Datos adicionales libres.
    """

    id: str
    name: str = ""
    level: int = 0
    spaces: list = field(default_factory=list)
    walls: list = field(default_factory=list)
    obstacles: list = field(default_factory=list)
    openings: list = field(default_factory=list)
    elevation_m: float = 0.0
    metadata: dict = field(default_factory=dict)
