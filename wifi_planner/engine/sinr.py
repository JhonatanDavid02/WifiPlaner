"""SINR — Signal to Interference plus Noise Ratio (Fase 12).

F12 convierte la interferencia que F11 anotó en una MÉTRICA DE CALIDAD
de enlace, sin tocar la física histórica: FSPL, link budget, RSSI, SOM,
SNR, calidad, veredicto, paredes, openings y obstáculos siguen siendo
exactamente los de F1–F11. El SINR es información **paralela** dentro
de ``LinkEvaluation`` (campos ``sinr_db``/``sinr_meets_target``).

Fórmula canónica (unica definición en todo el árbol):

    SINR = P_rx − 10·log10( 10^(NoiseFloor/10) + 10^(I_total/10) )   [dB]

Donde P_rx, NoiseFloor e I_total están en dBm e I_total es la
interferencia AGREGADA de F11 (``interference_dbm``). Los dBm **no se
suman**: el denominador se combina en el dominio lineal (mismas
utilidades dBm↔mW del modelo, decisión CA).

Sin interferencia modelada (decisión CG):

    interference_dbm is None  ⇒  denominador = NoiseFloor  ⇒  SINR = SNR

con igualdad EXACTA (misma aritmética redondeada a 2 decimales que
``signal_to_noise_ratio``): AP sin canal, canales sin solapamiento,
proyectos F1–F10, un solo AP o corridas sin contexto F11.

Estabilidad numérica (decisión CF): la suma ruido+interferencia usa la
forma basada en el máximo

    D = max(N, I)
    denominador = D + 10·log10( 1 + 10^((min(N, I) − D)/10) )

cuyo exponente es siempre ≤ 0: sin overflow (10^x ∈ (0, 1]), sin
división por cero y con underflow benigno (10^x → 0 ⇒ log10(1) = 0).
El resultado es finito siempre que lo sean N e I; los valores no finitos
se rechazan con ``ValueError`` (nunca se propaga ``nan``/``inf``).

Secuencia conceptual (decisión CF):

    simular propagación → RSSI → SNR → interferencia F11 → SINR F12
    → combinar multi-AP (sigue MAX RSSI)

La sesión invoca ``annotate_sinr`` DESPUÉS de
``engine.interference.annotate_interference`` y ANTES de
``engine.combine.combine_results``, de modo que la evaluación ganadora
transporta su SINR. Este módulo no calcula solapamiento, ocupación ni
potencia de interferentes (eso es F11): SOLO consume
``interference_dbm``. Sin caché, sin hilos, sin GPU (herencia CE).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Sequence

from core.result import LinkEvaluation, SimulationResult
from engine.classifier import meets_sinr_target


def _finite(name: str, value) -> float:
    """Valida que ``value`` sea un número finito (no bool) y lo devuelve."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} debe ser un número (got {value!r}).")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} debe ser finita (got {value!r}).")
    return number


def interference_plus_noise_dbm(
    noise_floor_dbm: float, interference_dbm: float | None
) -> float:
    """Denominador del SINR: ruido + interferencia combinados en dBm.

    Conversión correcta al dominio lineal (los dBm no se suman), con la
    forma estable basada en el máximo:

        D = max(N, I);  D + 10·log10(1 + 10^((min(N, I) − D)/10))

    Args:
        noise_floor_dbm: Piso de ruido en dBm (finito).
        interference_dbm: Interferencia agregada de F11 en dBm, o
            ``None`` = sin interferencia modelada ⇒ devuelve exactamente
            el piso de ruido (decisión CG).

    Returns:
        El denominador en dBm (finito).

    Raises:
        ValueError: si algún valor no es finito (nunca ``nan``/``inf``).
    """
    noise = _finite("noise_floor_dbm", noise_floor_dbm)
    if interference_dbm is None:
        return noise
    interference = _finite("interference_dbm", interference_dbm)
    high = max(noise, interference)
    low = min(noise, interference)
    # exponente <= 0 siempre: 10**x ∈ (0, 1]; underflow ⇒ 0 ⇒ log10(1)=0.
    return high + 10.0 * math.log10(1.0 + 10.0 ** ((low - high) / 10.0))


def signal_to_interference_noise_ratio(
    rx_power_dbm: float,
    noise_floor_dbm: float,
    interference_dbm: float | None = None,
) -> float:
    """SINR = P_rx − denominador(ruido + interferencia), en dB (2 decimales).

    Es la ÚNICA definición de la fórmula en el proyecto (decisión CF):
    la UI, el renderer, la sesión y los tests la consumen, nunca la
    replican.

    Args:
        rx_power_dbm: Potencia recibida de la señal deseada (RSSI) en dBm.
        noise_floor_dbm: Piso de ruido en dBm.
        interference_dbm: Interferencia agregada de F11 en dBm, o
            ``None`` (sin modelo / sin contribuidores).

    Returns:
        SINR en dB. Con ``interference_dbm=None`` devuelve exactamente
        ``round(P_rx − NoiseFloor, 2)``, idéntico al SNR (decisión CG).

    Raises:
        ValueError: si algún valor no es finito o no es numérico.
    """
    rx = _finite("rx_power_dbm", rx_power_dbm)
    denominator = interference_plus_noise_dbm(noise_floor_dbm, interference_dbm)
    return round(rx - denominator, 2)


# ---------------------------------------------------------------------------
# Anotación de resultados (reutiliza F11; patrón replace de BX)
# ---------------------------------------------------------------------------


def _with_sinr(evaluation: LinkEvaluation, thresholds) -> LinkEvaluation:
    """Nueva evaluación con ``sinr_db``/``sinr_meets_target`` calculados."""
    sinr = signal_to_interference_noise_ratio(
        evaluation.rx_power_dbm,
        evaluation.noise_floor_dbm,
        evaluation.interference_dbm,
    )
    return replace(
        evaluation,
        sinr_db=sinr,
        sinr_meets_target=meets_sinr_target(sinr, thresholds),
    )


def annotate_sinr(
    results: Sequence[SimulationResult], thresholds
) -> list[SimulationResult]:
    """Anota el SINR de cada evaluación con la interferencia ya modelada.

    Secuencia (decisión CF): la sesión llama a esta función DESPUÉS de
    ``annotate_interference`` (F11) y ANTES de ``combine_results`` (F5),
    de modo que cada resultado — y después la evaluación ganadora por
    RSSI — transporta su propio SINR. No se recalcula F11: se consume
    ``interference_dbm`` tal cual.

    Además refresca las claves ``sinr_*`` de ``result.stats`` para que
    las estadísticas nunca queden desfasadas respecto a los campos
    anotados (mismo denominador que SNR: puntos totales).

    Args:
        results: Resultados ya anotados con interferencia (o no).
        thresholds: ``CoverageThresholds`` (umbral ``sinr_target_db``).

    Returns:
        Nueva lista en el MISMO orden; evaluaciones y resultados se
        reconstruyen con ``replace`` (nada se muta).
    """
    annotated: list[SimulationResult] = []
    for result in results:
        new_evaluations = tuple(
            _with_sinr(evaluation, thresholds)
            for evaluation in result.evaluations
        )
        stats = dict(result.stats or {})
        stats.update(
            sinr_stats_block(new_evaluations, thresholds.sinr_target_db)
        )
        annotated.append(
            replace(result, evaluations=new_evaluations, stats=stats)
        )
    return annotated


def sinr_stats_block(evaluations: Sequence, sinr_target_db: float) -> dict:
    """Bloque de estadísticas de SINR (patrón del bloque SNR de F7).

    Args:
        evaluations: Evaluaciones (con ``sinr_db`` ya anotado).
        sinr_target_db: Objetivo de SINR en dB (para el conteo y el
            ratio ya vienen evaluados en ``sinr_meets_target``).

    Returns:
        Dict con ``sinr_min_db``, ``sinr_max_db``, ``sinr_avg_db``,
        ``sinr_target_db``, ``points_meeting_sinr_target`` y
        ``sinr_ratio``; ``{}`` si no hay evaluaciones ni SINR anotado
        (la UI distingue «sin datos» de «0 %»).
    """
    evals = list(evaluations)
    if not evals:
        return {}
    annotated = [e for e in evals if e.sinr_db is not None]
    if not annotated:
        return {}
    values = [e.sinr_db for e in annotated]
    total = len(evals)
    meets = sum(1 for e in annotated if e.sinr_meets_target)
    return {
        "sinr_min_db": min(values),
        "sinr_max_db": max(values),
        "sinr_avg_db": round(sum(values) / len(values), 2),
        "sinr_target_db": float(sinr_target_db),
        "points_meeting_sinr_target": meets,
        "sinr_ratio": round(meets / total, 4),
    }


__all__ = [
    "annotate_sinr",
    "interference_plus_noise_dbm",
    "signal_to_interference_noise_ratio",
    "sinr_stats_block",
]
