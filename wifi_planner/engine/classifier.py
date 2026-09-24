"""Clasificación de calidad de cobertura y veredictos.

Los umbrales NO están hardcodeados: llegan desde CoverageThresholds
(config/configuración del proyecto).

Clases de cobertura (valores por defecto configurables):

    Excelente >= -50 dBm
    Buena      >= -67 dBm
    Regular    >= -75 dBm
    Debil      >= -85 dBm
    Sin cobertura util < -85 dBm

Veredicto SOM:

    SOM >= 20 dB        -> APROBADO
    10 <= SOM < 20 dB   -> RIESGO
    SOM < 10 dB         -> FALLIDO

RSSI objetivo: P_rx > -67 dBm (comparación ESTRICTA, decisión C).
"""

from __future__ import annotations

from core.result import QualityClass, Verdict


def classify_quality(rx_power_dbm: float, thresholds) -> QualityClass:
    """Clasifica la potencia recibida en una clase de cobertura.

    Args:
        rx_power_dbm: P_rx en dBm.
        thresholds: Objeto con excellent/good/regular/weak_min_dbm.

    Returns:
        QualityClass correspondiente.
    """
    if rx_power_dbm >= thresholds.excellent_min_dbm:
        return QualityClass.EXCELLENT
    if rx_power_dbm >= thresholds.good_min_dbm:
        return QualityClass.GOOD
    if rx_power_dbm >= thresholds.regular_min_dbm:
        return QualityClass.REGULAR
    if rx_power_dbm >= thresholds.weak_min_dbm:
        return QualityClass.WEAK
    return QualityClass.NO_COVERAGE


def meets_rssi_target(rx_power_dbm: float, thresholds) -> bool:
    """True si P_rx supera estrictamente el RSSI objetivo.

    Comparación estricta: rx_power_dbm > thresholds.rssi_target_dbm
    (decisión C: no es >=).
    """
    return rx_power_dbm > thresholds.rssi_target_dbm


def classify_som(som_db: float, thresholds) -> Verdict:
    """Clasifica el SOM según los umbrales configurados.

    Decisión D:
        som >= som_aprobado_min_db -> APROBADO
        som >= som_riesgo_min_db   -> RIESGO
        en otro caso               -> FALLIDO
    """
    if som_db >= thresholds.som_aprobado_min_db:
        return Verdict.APROBADO
    if som_db >= thresholds.som_riesgo_min_db:
        return Verdict.RIESGO
    return Verdict.FALLIDO
