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
        width_m: Ancho del área del piso en metros (> 0 si se define).
        height_m: Alto del área del piso en metros (> 0 si se define).
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
    width_m: float | None = None
    height_m: float | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.width_m is not None and self.width_m <= 0:
            raise ValueError(
                f"Floor.width_m debe ser > 0 metros (got {self.width_m})."
            )
        if self.height_m is not None and self.height_m <= 0:
            raise ValueError(
                f"Floor.height_m debe ser > 0 metros (got {self.height_m})."
            )

    def set_dimensions(self, width_m: float, height_m: float) -> None:
        """Actualiza las dimensiones físicas del piso con validación."""
        if width_m <= 0 or height_m <= 0:
            raise ValueError(
                f"Dimensiones inválidas: {width_m} x {height_m} m "
                "(ambas deben ser > 0)."
            )
        if width_m > 10_000 or height_m > 10_000:
            raise ValueError(
                f"Dimensiones no razonables: {width_m} x {height_m} m "
                "(máximo 10000 m por lado)."
            )
        self.width_m = float(width_m)
        self.height_m = float(height_m)
