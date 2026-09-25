"""Combinación de resultados de múltiples Access Points.

Fase 5: fusión por punto con **mejor RSSI disponible** (cobertura).
NO es interferencia (sin SINR, canal, ruido ni roaming).

Por cada coordenada (x, y) del grid se conserva la LinkEvaluation con
mayor ``rx_power_dbm``. En empate exacto de RSSI gana el AP con menor
``access_point_id`` lexicográfico (política determinista, decisión U).
El ``access_point_id`` de la evaluación ganadora es el ``best_ap_id``.
SOM / quality / veredicto son los del AP ganador (no se promedian).

Fase 11: la interferencia se anota ANTES de combinar (la sesión llama a
``engine.interference.annotate_interference``) y viaja dentro de la
evaluación ganadora; la regla de selección sigue siendo **mayor RSSI**
(contrato F5 intacto — decisión BX). Este módulo no calcula
interferencia ni cambia su firma.
"""

from __future__ import annotations

from core.project import CoverageThresholds
from core.result import LinkEvaluation, SimulationResult
from engine.sinr import sinr_stats_block


def _better(a: LinkEvaluation, b: LinkEvaluation) -> bool:
    """True si ``a`` gana a ``b`` para el mismo punto de muestreo."""
    if a.rx_power_dbm != b.rx_power_dbm:
        return a.rx_power_dbm > b.rx_power_dbm
    # Empate de RSSI → menor id estable (AP-001 antes que AP-002).
    return a.access_point_id < b.access_point_id


def combine_results(results: list[SimulationResult]) -> SimulationResult:
    """Combina varios SimulationResult (uno por AP) en uno solo.

    Estrategia V1: para cada punto se conserva la evaluación con
    mayor P_rx (mejor señal). Empates: menor ``access_point_id``.

    Args:
        results: Lista de SimulationResult (pueden ser de distinto AP
            pero deben compartir band_id; si no, se lanza ValueError).

    Returns:
        SimulationResult combinado: una evaluación por punto (mejor AP),
        con stats de cobertura + dominancia por AP.

    Raises:
        ValueError: si la lista está vacía o hay bandas distintas.
    """
    if not results:
        raise ValueError("No hay resultados que combinar.")

    band_ids = {r.band_id for r in results}
    if len(band_ids) > 1:
        raise ValueError(
            f"No se pueden combinar resultados de bandas distintas: {sorted(band_ids)}"
        )

    best_by_point: dict[tuple[float, float], LinkEvaluation] = {}
    # Orden de recorrido estable: por id de AP de cada resultado.
    ordered = sorted(
        results,
        key=lambda r: (
            r.evaluations[0].access_point_id if r.evaluations else ""
        ),
    )
    for result in ordered:
        for evaluation in result.evaluations:
            key = (evaluation.point.x, evaluation.point.y)
            current = best_by_point.get(key)
            if current is None or _better(evaluation, current):
                best_by_point[key] = evaluation

    # Mismo orden de puntos que el primer resultado de entrada (grid).
    ordered_points = [
        (e.point.x, e.point.y) for e in results[0].evaluations
    ]
    evaluations = tuple(
        best_by_point[key] for key in ordered_points if key in best_by_point
    )
    # Puntos solo presentes en otros resultados (por si acaso)
    seen = set(ordered_points)
    for key, ev in best_by_point.items():
        if key not in seen:
            evaluations = evaluations + (ev,)
            seen.add(key)

    all_ap_ids = sorted(
        {e.access_point_id for r in results for e in r.evaluations}
    )
    merged_stats = _merged_stats(results, evaluations, all_ap_ids)

    return SimulationResult(
        project_name=results[0].project_name,
        band_id=results[0].band_id,
        evaluations=evaluations,
        generated_at=max(
            (r.generated_at for r in results if r.generated_at is not None),
            default=None,
        ),
        stats=merged_stats,
    )


def _merged_stats(
    results: list[SimulationResult],
    evaluations: tuple[LinkEvaluation, ...],
    all_ap_ids: list[str],
) -> dict:
    """Estadísticas del resultado combinado (mismo contrato que F4)."""
    if not evaluations:
        return {}

    rx_values = [e.rx_power_dbm for e in evaluations]
    snr_values = [e.snr_db for e in evaluations]
    quality_counts: dict[str, int] = {}
    for evaluation in evaluations:
        key = evaluation.quality.value
        quality_counts[key] = quality_counts.get(key, 0) + 1

    meets_count = sum(1 for e in evaluations if e.rssi_meets_target)
    sample_target = results[0].stats.get("rssi_target_dbm", -67.0)
    snr_meets_count = sum(1 for e in evaluations if e.snr_meets_target)
    sample_snr_target = results[0].stats.get(
        "snr_target_db", CoverageThresholds().snr_target_db
    )
    sample_sinr_target = results[0].stats.get(
        "sinr_target_db", CoverageThresholds().sinr_target_db
    )
    total = len(evaluations)

    quality_percent = {
        key: round(100.0 * count / total, 2)
        for key, count in quality_counts.items()
    }

    # Dominancia: puntos cuyo best_ap_id es cada AP / total del grid.
    dominance_counts = {ap_id: 0 for ap_id in all_ap_ids}
    for evaluation in evaluations:
        ap_id = evaluation.access_point_id
        dominance_counts[ap_id] = dominance_counts.get(ap_id, 0) + 1
    dominance_percent = {
        ap_id: round(100.0 * count / total, 2)
        for ap_id, count in dominance_counts.items()
    }

    return {
        "point_count": total,
        "total": total,
        "source_results": len(results),
        "combined": len(results) > 1,
        "rx_min_dbm": min(rx_values),
        "rx_max_dbm": max(rx_values),
        "rx_avg_dbm": round(sum(rx_values) / total, 2),
        "quality_counts": quality_counts,
        "quality_percent": quality_percent,
        "rssi_target_dbm": sample_target,
        "points_meeting_target": meets_count,
        "coverage_ratio": round(meets_count / total, 4),
        # Fase 7: SNR del AP ganador por punto (nunca se promedia entre
        # APs; el ganador sigue siendo el de mejor RSSI, decisión U/BB).
        "snr_min_db": min(snr_values),
        "snr_max_db": max(snr_values),
        "snr_avg_db": round(sum(snr_values) / total, 2),
        "snr_target_db": sample_snr_target,
        "points_meeting_snr_target": snr_meets_count,
        "snr_ratio": round(snr_meets_count / total, 4),
        "ap_dominance_counts": dominance_counts,
        "ap_dominance_percent": dominance_percent,
        # Fase 12: SINR del ganador por punto (mismo criterio que SNR:
        # nunca se promedia entre APs; bloque definido en engine.sinr).
        **sinr_stats_block(evaluations, sample_sinr_target),
    }
