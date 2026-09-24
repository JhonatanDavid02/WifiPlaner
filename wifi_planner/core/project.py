"""Entidad Project: contenedor raíz del dominio.

Un Project agrupa bandas, materiales, configuración de radio, umbrales
y (en fases posteriores) pisos con su geometría, APs y clientes.

V1: estructura mínima lista para recibir pisos y dispositivos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.band import DEFAULT_BANDS, FrequencyBand
from core.material import Material, default_materials
from core.radio import RadioConfiguration


@dataclass(frozen=True)
class CoverageThresholds:
    """Umbrales de evaluación de cobertura.

    Están aquí (y en config/), NUNCA hardcodeados en componentes de UI.

    Attributes:
        rssi_target_dbm: RSSI objetivo mínimo en dBm. Comparación estricta: P_rx > umbral.
        som_aprobado_min_db: SOM mínimo para APROBADO en dB.
        som_riesgo_min_db: SOM mínimo para RIESGO en dB (por debajo => FALLIDO).
        excellent_min_dbm: Piso de calidad "Excelente" en dBm.
        good_min_dbm: Piso de calidad "Buena" en dBm.
        regular_min_dbm: Piso de calidad "Regular" en dBm.
        weak_min_dbm: Piso de calidad "Débil" en dBm (por debajo => sin cobertura útil).
    """

    rssi_target_dbm: float = -67.0
    som_aprobado_min_db: float = 20.0
    som_riesgo_min_db: float = 10.0
    excellent_min_dbm: float = -50.0
    good_min_dbm: float = -67.0
    regular_min_dbm: float = -75.0
    weak_min_dbm: float = -85.0


DEFAULT_THRESHOLDS = CoverageThresholds()


@dataclass
class Project:
    """Proyecto de diseño Wi-Fi.

    Attributes:
        name: Nombre del proyecto.
        units: Unidad de longitud del modelo. Siempre "m" (metros).
        bands: Bandas de frecuencia disponibles.
        materials: Catálogo de materiales del proyecto.
        radio: Configuración de radio por defecto para nuevos APs/clients.
        thresholds: Umbrales de clasificación de cobertura.
        access_points: Lista de APs (puede estar vacía en V1).
        clients: Lista de dispositivos cliente.
        floors: Pisos del proyecto (en V1 puede contener un único piso
            o estar vacío; la estructura permite crecer).
        metadata: Datos adicionales libres.
    """

    name: str = "Untitled Project"
    units: str = "m"
    bands: list[FrequencyBand] = field(default_factory=lambda: list(DEFAULT_BANDS))
    materials: list[Material] = field(default_factory=lambda: list(default_materials()))
    radio: RadioConfiguration = field(default_factory=RadioConfiguration)
    thresholds: CoverageThresholds = field(default_factory=CoverageThresholds)
    access_points: list = field(default_factory=list)
    clients: list = field(default_factory=list)
    floors: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.units != "m":
            raise ValueError(
                f"Unidad no soportada: {self.units!r}. "
                "El modelo físico utiliza exclusivamente metros."
            )

    def get_band(self, band_id: str) -> FrequencyBand:
        """Busca una banda por id.

        Raises:
            KeyError: si la banda no existe en el proyecto.
        """
        for band in self.bands:
            if band.id == band_id:
                return band
        raise KeyError(f"Banda no encontrada: {band_id!r}")

    def get_material(self, material_id: str) -> Material:
        """Busca un material por id.

        Raises:
            KeyError: si el material no existe en el proyecto.
        """
        for material in self.materials:
            if material.id == material_id:
                return material
        raise KeyError(f"Material no encontrado: {material_id!r}")

    @property
    def default_floor(self) -> "Floor | None":
        """Primer piso del proyecto o None si no hay pisos todavía."""
        if self.floors:
            return self.floors[0]
        return None
