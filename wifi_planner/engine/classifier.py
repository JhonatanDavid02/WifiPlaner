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

Fase 7: el SNR COMPLEMENTA a RSSI/SOM, no los reemplaza. La calidad
histórica (QualityClass), el veredicto SOM y el objetivo RSSI no
cambian; se añaden ``meets_snr_target`` y el diagnóstico básico por
cuadrantes ``rf_diagnostic`` (decisión AV/BC).
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


def meets_snr_target(snr_db: float, thresholds) -> bool:
    """True si el SNR alcanza el objetivo configurado (F7).

    Comparación SNR >= thresholds.snr_target_db (decisión AW): el
    objetivo de SNR es "alcanzar el objetivo", a diferencia del RSSI
    objetivo que usa comparación estricta (decisión C).
    """
    return snr_db >= thresholds.snr_target_db


def meets_sinr_target(sinr_db: float, thresholds) -> bool:
    """True si el SINR alcanza el objetivo configurado (F12).

    Comparación SINR >= thresholds.sinr_target_db (decisión CH): misma
    semántica >= que el objetivo de SNR (AW), distinta de la comparación
    estricta del RSSI objetivo (decisión C). Complementa a RSSI/SOM/SNR
    e interferencia; no los reemplaza.
    """
    return sinr_db >= thresholds.sinr_target_db


def sinr_diagnostic(sinr_db: float, thresholds) -> str:
    """Diagnóstico complementario de SINR en dos estados (F12).

    No modifica ``rf_diagnostic`` (que sigue describiendo RSSI/SNR en
    cuatro cuadrantes, con sus 4 salidas congeladas): añade una
    etiqueta de una sola dimensión para la línea de diagnóstico:

        SINR adecuado  si SINR >= umbral
        SINR bajo      si SINR <  umbral

    Args:
        sinr_db: SINR en dB.
        thresholds: CoverageThresholds (sinr_target_db).

    Returns:
        "SINR adecuado" o "SINR bajo".
    """
    return "SINR adecuado" if meets_sinr_target(sinr_db, thresholds) else "SINR bajo"


def rf_diagnostic(rx_power_dbm: float, snr_db: float, thresholds) -> str:
    """Diagnóstico RF básico en cuatro cuadrantes (F7, decisión BC).

    Combina el criterio histórico de RSSI con el objetivo de SNR sin
    inventar causas (no habla de interferencia, canales ni hidden node:
    F7 no los modela). Solo describe el estado medido:

        RSSI adecuado / SNR adecuado
        RSSI adecuado / SNR bajo
        RSSI bajo / SNR adecuado
        RSSI bajo / SNR bajo

    Args:
        rx_power_dbm: P_rx en dBm.
        snr_db: SNR en dB.
        thresholds: CoverageThresholds (rssi_target_dbm, snr_target_db).

    Returns:
        Etiqueta del cuadrante.
    """
    rssi_ok = meets_rssi_target(rx_power_dbm, thresholds)
    snr_ok = meets_snr_target(snr_db, thresholds)
    if rssi_ok and snr_ok:
        return "RSSI adecuado / SNR adecuado"
    if rssi_ok:
        return "RSSI adecuado / SNR bajo"
    if snr_ok:
        return "RSSI bajo / SNR adecuado"
    return "RSSI bajo / SNR bajo"


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
