"""Entidad Project: contenedor raíz del dominio.

Un Project agrupa bandas, materiales, configuración de radio, umbrales
y (en fases posteriores) pisos con su geometría, APs y clientes.

V1: estructura mínima lista para recibir pisos y dispositivos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.band import DEFAULT_BANDS, FrequencyBand
from core.material import Material, default_materials
from core.radio import RadioConfiguration

# Objetivo de SNR por defecto (dB). Valor de referencia de diseño para
# datos; NO es una verdad universal (decisión AW en docs/decisions.md).
# Con los defaults (piso -95, RSSI objetivo -67) el punto en el umbral
# de RSSI tiene SNR = 28 dB, así que 25 dB mantiene la coherencia:
# cumplir RSSI implica cumplir SNR.
DEFAULT_SNR_TARGET_DB = 25.0

# Rango aceptado para el objetivo de SNR (dB):
# - mínimo -20: por debajo de 0 dB (señal bajo el ruido) ningún
#   objetivo de diseño tiene sentido.
# - máximo 60: por encima del SNR máximo que este modelo produce en
#   la práctica (RSSI típicamente >= -35 dBm con piso -95).
SNR_TARGET_MIN_DB = -20.0
SNR_TARGET_MAX_DB = 60.0

# Objetivo de SINR por defecto (dB, Fase 12). Valor de referencia de
# diseño; NO es una verdad universal (decisión CH en docs/decisions.md).
# Igual al objetivo de SNR (25 dB) para mantener la coherencia: como
# SINR <= SNR siempre (el denominador incluye el ruido), cumplir el
# objetivo de SINR implica cumplir el de SNR, y SINR sin interferencia
# modelada es exactamente SNR (ambos umbrales se cumplen juntos).
DEFAULT_SINR_TARGET_DB = 25.0

# Rango aceptado para el objetivo de SINR (dB). Mismo intervalo que el
# objetivo de SNR: SINR es la misma relación con un denominador >= ruido.
SINR_TARGET_MIN_DB = -20.0
SINR_TARGET_MAX_DB = 60.0


@dataclass(frozen=True)
class CoverageThresholds:
    """Umbrales de evaluación de cobertura.

    Están aquí (y en config/), NUNCA hardcodeados en componentes de UI.

    Attributes:
        rssi_target_dbm: RSSI objetivo mínimo en dBm. Comparación estricta: P_rx > umbral.
            Es el **coverage threshold** del proyecto (F7 lo mantiene
            con este nombre histórico; no se renombra).
        som_aprobado_min_db: SOM mínimo para APROBADO en dB.
        som_riesgo_min_db: SOM mínimo para RIESGO en dB (por debajo => FALLIDO).
        excellent_min_dbm: Piso de calidad "Excelente" en dBm.
        good_min_dbm: Piso de calidad "Buena" en dBm.
        regular_min_dbm: Piso de calidad "Regular" en dBm.
        weak_min_dbm: Piso de calidad "Débil" en dBm (por debajo => sin cobertura útil).
        snr_target_db: Objetivo de SNR en dB (F7). Comparación SNR >= umbral.
            Rango: [-20, 60] dB. No reemplaza al RSSI objetivo: son
            conceptos distintos (potencia vs relación señal/ruido).
        sinr_target_db: Objetivo de SINR en dB (F12). Comparación
            SINR >= umbral (misma semántica >= que el SNR, decisión CH).
            Rango: [-20, 60] dB. No reemplaza a SNR/interferencia: es
            el umbral de la relación señal/(ruido+interferencia).
    """

    rssi_target_dbm: float = -67.0
    som_aprobado_min_db: float = 20.0
    som_riesgo_min_db: float = 10.0
    excellent_min_dbm: float = -50.0
    good_min_dbm: float = -67.0
    regular_min_dbm: float = -75.0
    weak_min_dbm: float = -85.0
    snr_target_db: float = DEFAULT_SNR_TARGET_DB
    sinr_target_db: float = DEFAULT_SINR_TARGET_DB

    def __post_init__(self) -> None:
        for name in ("rssi_target_dbm", "snr_target_db", "sinr_target_db"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"CoverageThresholds.{name} debe ser un número."
                )
            if not math.isfinite(float(value)):
                raise ValueError(
                    f"CoverageThresholds.{name} debe ser finito."
                )
            object.__setattr__(self, name, float(value))
        if not (SNR_TARGET_MIN_DB <= self.snr_target_db <= SNR_TARGET_MAX_DB):
            raise ValueError(
                "CoverageThresholds.snr_target_db debe estar en "
                f"[{SNR_TARGET_MIN_DB:g}, {SNR_TARGET_MAX_DB:g}] dB "
                f"(got {self.snr_target_db:g})."
            )
        if not (SINR_TARGET_MIN_DB <= self.sinr_target_db <= SINR_TARGET_MAX_DB):
            raise ValueError(
                "CoverageThresholds.sinr_target_db debe estar en "
                f"[{SINR_TARGET_MIN_DB:g}, {SINR_TARGET_MAX_DB:g}] dB "
                f"(got {self.sinr_target_db:g})."
            )


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
