"""Presupuesto de enlace (link budget) y SOM.

Fórmula canónica V1:

    P_rx = P_tx + G_tx - L_tx - FSPL - L_m + G_rx - L_rx - L_obstacles

    SOM  = P_rx - Sensibilidad

Donde:
- L_m (fade margin) es configurable; por defecto 10 dB (decisión B).
  Usar 0 dB para reproducir el comportamiento de las versiones legacy
  v3/v4 que omitían el margen.
- L_obstacles es 0 en Fase 1 (aún no hay intersección rayo-pared);
  la estructura ya lo contempla para Fase 2.

Ninguna fórmula vive en la UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.geometry import Point2D
from core.radio import RadioConfiguration
from core.result import LinkEvaluation, ObstacleLoss, QualityClass, Verdict
from engine import classifier, propagation


@dataclass(frozen=True)
class LinkBudget:
    """Resultado numérico del presupuesto de enlace.

    Attributes:
        path_loss_db: FSPL en dB.
        obstacle_loss_db: Pérdida por obstáculos en dB.
        fade_margin_db: Lm aplicado en dB.
        rx_power_dbm: P_rx (RSSI estimado) en dBm.
        som_db: System Operating Margin en dB.
    """

    path_loss_db: float
    obstacle_loss_db: float
    fade_margin_db: float
    rx_power_dbm: float
    som_db: float


def link_budget(
    radio: RadioConfiguration,
    distance_m: float,
    frequency_mhz: float,
    obstacle_loss_db: float = 0.0,
) -> LinkBudget:
    """Calcula el presupuesto de enlace completo.

    Args:
        radio: Parámetros de radio (P_tx, ganancias, pérdidas, Lm, sensibilidad).
        distance_m: Distancia en metros (> 0).
        frequency_mhz: Frecuencia en MHz (> 0).
        obstacle_loss_db: Pérdida acumulada por obstáculos en dB (>= 0).

    Returns:
        LinkBudget con P_rx y SOM.

    Raises:
        ValueError: si distance_m <= 0, frequency_mhz <= 0 u obstacle_loss_db < 0.
    """
    if obstacle_loss_db < 0:
        raise ValueError("obstacle_loss_db no puede ser negativo.")

    path_loss = propagation.path_loss_fspl_db(distance_m, frequency_mhz)

    rx_power = (
        radio.p_tx_dbm
        + radio.g_tx_dbi
        - radio.l_tx_db
        - path_loss
        - radio.fade_margin_db
        + radio.g_rx_dbi
        - radio.l_rx_db
        - obstacle_loss_db
    )
    rx_power = round(rx_power, 2)

    som = system_operating_margin(rx_power, radio.sensitivity_dbm)

    return LinkBudget(
        path_loss_db=path_loss,
        obstacle_loss_db=round(obstacle_loss_db, 2),
        fade_margin_db=radio.fade_margin_db,
        rx_power_dbm=rx_power,
        som_db=som,
    )


def system_operating_margin(rx_power_dbm: float, sensitivity_dbm: float) -> float:
    """SOM = P_rx - sensibilidad, en dB (2 decimales)."""
    return round(rx_power_dbm - sensitivity_dbm, 2)


def evaluate_link(
    radio: RadioConfiguration,
    access_point_id: str,
    band_id: str,
    ap_position: Point2D,
    client_position: Point2D,
    frequency_mhz: float,
    thresholds,
    obstacle_loss: ObstacleLoss | None = None,
) -> LinkEvaluation:
    """Evalúa un enlace AP → cliente/punto y clasifica el resultado.

    Esta es la función atómica que la futura simulación de grid
    llamará para cada punto. La UI solo consumirá el resultado.

    Args:
        radio: Configuración de radio (puede ser la del AP o la del cliente
            con su sensibilidad sobrescrita).
        access_point_id: Id del AP.
        band_id: Id de la banda.
        ap_position: Posición del AP en metros.
        client_position: Posición del cliente/punto en metros.
        frequency_mhz: Frecuencia de la banda en MHz.
        thresholds: Umbrales de clasificación (CoverageThresholds).
        obstacle_loss: Pérdida por obstáculos (None => 0 dB, Fase 1).

    Returns:
        LinkEvaluation con distancias, pérdidas, P_rx, SOM, veredicto
        y clase de calidad.
    """
    if obstacle_loss is None:
        obstacle_loss = ObstacleLoss(total_db=0.0, crossings=0)

    distance = ap_position.distance_to(client_position)

    budget = link_budget(
        radio=radio,
        distance_m=distance,
        frequency_mhz=frequency_mhz,
        obstacle_loss_db=obstacle_loss.total_db,
    )

    quality = classifier.classify_quality(budget.rx_power_dbm, thresholds)
    verdict = classifier.classify_som(budget.som_db, thresholds)
    meets = classifier.meets_rssi_target(budget.rx_power_dbm, thresholds)

    return LinkEvaluation(
        access_point_id=access_point_id,
        band_id=band_id,
        point=client_position,
        distance_m=round(distance, 4),
        path_loss_db=budget.path_loss_db,
        obstacle_loss_db=budget.obstacle_loss_db,
        obstacle_loss=obstacle_loss,
        rx_power_dbm=budget.rx_power_dbm,
        som_db=budget.som_db,
        rssi_meets_target=meets,
        verdict=verdict,
        quality=quality,
    )
