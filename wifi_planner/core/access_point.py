"""Punto de acceso (Access Point)."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.geometry import Point2D
from core.radio import RadioConfiguration


@dataclass
class AccessPoint:
    """Access Point físico.

    Attributes:
        id: Identificador estable (ej. "AP1").
        position: Posición física en metros.
        radio: Configuración de radio del AP.
        channel: Canal asignado (opcional; planificación de canales posterior).
        name: Nombre legible opcional.
        enabled: Indica si participa en simulaciones.
        metadata: Datos adicionales libres.
    """

    id: str
    position: Point2D
    radio: RadioConfiguration = field(default_factory=RadioConfiguration)
    channel: int | None = None
    name: str = ""
    enabled: bool = True
    metadata: dict = field(default_factory=dict)
