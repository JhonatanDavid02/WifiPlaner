"""Punto de acceso (Access Point)."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.channel import MAX_CHANNEL_NUMBER
from core.geometry import Point2D
from core.radio import RadioConfiguration


@dataclass
class AccessPoint:
    """Access Point físico.

    Fase 10: configuración RF **por AP** (un radio → una banda, decisión
    BS). ``band_id`` + ``channel`` declaran en qué banda transmite el AP y
    en qué canal; ``radio.channel_width_mhz`` (F7) completa el triple. La
    pertenencia canal↔banda se valida donde existe el objeto banda
    (sesión, persistencia, engine — decisión BT); aquí solo se garantiza
    la coherencia estructural.

    Attributes:
        id: Identificador estable (ej. "AP1").
        position: Posición física en metros.
        radio: Configuración de radio del AP.
        band_id: Banda configurada del AP (Fase 10). ``None`` = sin banda
            propia: la simulación usa la banda activa del proyecto
            (compatibilidad F1–F9).
        channel: Canal asignado (Fase 10; identificador lógico). ``None``
            = sin configurar (proyectos F6–F9). Invariante: un canal
            explícito requiere ``band_id`` (decisión BS).
        name: Nombre legible opcional.
        enabled: Indica si participa en simulaciones.
        metadata: Datos adicionales libres.
    """

    id: str
    position: Point2D
    radio: RadioConfiguration = field(default_factory=RadioConfiguration)
    band_id: str | None = None
    channel: int | None = None
    name: str = ""
    enabled: bool = True
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        band_id = self.band_id
        if band_id is not None:
            if isinstance(band_id, bool) or not isinstance(band_id, str):
                raise ValueError(
                    f"AccessPoint.band_id debe ser una cadena o None (got {band_id!r})."
                )
            if not band_id:
                raise ValueError("AccessPoint.band_id no puede estar vacío.")
        channel = self.channel
        if channel is not None:
            if isinstance(channel, bool) or not isinstance(channel, int):
                raise ValueError(
                    f"AccessPoint.channel debe ser un entero o None (got {channel!r})."
                )
            # Invariante (decisión BS): sin banda no hay contexto para
            # validar el canal, así que un canal explícito exige banda.
            if band_id is None:
                raise ValueError(
                    "AccessPoint.channel requiere band_id (Fase 10): "
                    "el canal se valida siempre contra una banda."
                )
            if not (1 <= channel <= MAX_CHANNEL_NUMBER):
                raise ValueError(
                    f"AccessPoint.channel debe estar en [1, {MAX_CHANNEL_NUMBER}] "
                    f"(got {channel})."
                )
