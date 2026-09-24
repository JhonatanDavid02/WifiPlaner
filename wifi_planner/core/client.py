"""Dispositivo cliente (laptop, teléfono, IoT...)."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.geometry import Point2D


@dataclass
class ClientDevice:
    """Dispositivo cliente.

    Attributes:
        id: Identificador estable (ej. "client_1").
        position: Posición física en metros.
        sensitivity_dbm: Sensibilidad del receptor en dBm.
        name: Nombre legible opcional.
        metadata: Datos adicionales libres.
    """

    id: str
    position: Point2D
    sensitivity_dbm: float = -75.0
    name: str = ""
    metadata: dict = field(default_factory=dict)
