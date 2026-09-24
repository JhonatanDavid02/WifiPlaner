"""Resultados de simulación y clasificación de cobertura.

Estas estructuras son el contrato entre el motor y la futura UI.
La UI solo consume estos resultados; nunca recalcula fórmulas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.geometry import Point2D
from core.radio import DEFAULT_NOISE_FLOOR_DBM


class QualityClass(str, Enum):
    """Clases de cobertura configurables (no hardcodeadas en UI)."""

    EXCELLENT = "Excelente"
    GOOD = "Buena"
    REGULAR = "Regular"
    WEAK = "Debil"
    NO_COVERAGE = "Sin cobertura util"


class Verdict(str, Enum):
    """Veredicto SOM."""

    APROBADO = "APROBADO"
    RIESGO = "RIESGO"
    FALLIDO = "FALLIDO"


@dataclass(frozen=True)
class ObstacleLoss:
    """Pérdida por obstáculos de un trayecto.

    Attributes:
        total_db: Pérdida acumulada en dB.
        crossings: Número de materiales atravesados.
        detail: Desglose [{wall_id, material_id, band_id, loss_db}, ...].
    """

    total_db: float
    crossings: int
    detail: tuple = ()


@dataclass(frozen=True)
class LinkEvaluation:
    """Evaluación de enlace AP → punto/cliente.

    Attributes:
        access_point_id: Id del AP evaluado.
        band_id: Id de la banda evaluada.
        point: Punto receptor en metros.
        distance_m: Distancia en metros.
        path_loss_db: Pérdida en espacio libre (FSPL) en dB.
        obstacle_loss_db: Pérdida por obstáculos en dB.
        obstacle_loss: Detalle de pérdida por obstáculos.
        rx_power_dbm: Potencia recibida estimada (RSSI) en dBm.
        som_db: System Operating Margin en dB.
        rssi_meets_target: True si P_rx > umbral RSSI (comparación estricta).
        verdict: Veredicto SOM.
        quality: Clase de calidad estimada.
        noise_floor_dbm: Piso de ruido usado en el cálculo, en dBm (F7).
            Por defecto el default centralizado; evaluate_link lo toma
            de la radio.
        snr_db: SNR = P_rx − piso de ruido, en dB (F7).
            0.0 solo en constructores manuales; evaluate_link lo calcula.
        snr_meets_target: True si SNR >= objetivo de SNR (F7).
    """

    access_point_id: str
    band_id: str
    point: Point2D
    distance_m: float
    path_loss_db: float
    obstacle_loss_db: float
    obstacle_loss: ObstacleLoss
    rx_power_dbm: float
    som_db: float
    rssi_meets_target: bool
    verdict: Verdict
    quality: QualityClass
    noise_floor_dbm: float = DEFAULT_NOISE_FLOOR_DBM
    snr_db: float = 0.0
    snr_meets_target: bool = False


@dataclass(frozen=True)
class SimulationResult:
    """Resultado agregado de una simulación de cobertura.

    En V1 puede contener una única evaluación (un AP, un punto).
    Posteriormente el simulador de grid devolverá muchas evaluaciones
    y estadísticas agregadas.

    Attributes:
        project_name: Nombre del proyecto.
        band_id: Banda evaluada.
        evaluations: Evaluaciones individuales (una por punto/AP).
        generated_at: Marca temporal opcional (epoch seconds).
        stats: Estadísticas agregadas opcionales.
    """

    project_name: str
    band_id: str
    evaluations: tuple[LinkEvaluation, ...] = ()
    generated_at: float | None = None
    stats: dict = field(default_factory=dict)

    def best_at(self, point: Point2D) -> LinkEvaluation | None:
        """Mejor evaluación (mayor P_rx) para un punto dado."""
        candidates = [e for e in self.evaluations if e.point == point]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.rx_power_dbm)
