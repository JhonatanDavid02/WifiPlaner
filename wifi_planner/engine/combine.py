"""Combinación de resultados de múltiples Access Points.

Fase 1: estructura preparada. La UI podrá evaluar varios APs y
combinar sus resultados (mejor señal por punto) sin que el motor
dependa de la interfaz.

La fusión por punto (best-RSSI / best-SINR) se implementará en Fase 5
cuando exista simulación sobre grid; aquí se deja la interfaz pública.
"""

from __future__ import annotations

from core.result import LinkEvaluation, SimulationResult


def combine_results(results: list[SimulationResult]) -> SimulationResult:
    """Combina varios SimulationResult (uno por AP) en uno solo.

    Estrategia V1: para cada punto se conserva la evaluación con
    mayor P_rx (mejor señal). Esta es la base para futuras combinaciones
    con interferencia (SINR) en fases posteriores.

    Args:
        results: Lista de SimulationResult (pueden ser de distinto AP
            pero deben compartir band_id; si no, se lanza ValueError).

    Returns:
        SimulationResult combinado con evaluaciones fusionadas por punto.

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
    for result in results:
        for evaluation in result.evaluations:
            key = (evaluation.point.x, evaluation.point.y)
            current = best_by_point.get(key)
            if current is None or evaluation.rx_power_dbm > current.rx_power_dbm:
                best_by_point[key] = evaluation

    evaluations = tuple(best_by_point.values())

    merged_stats = _merged_stats(results, evaluations)

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
) -> dict:
    """Estadísticas del resultado combinado."""
    if not evaluations:
        return {}

    rx_values = [e.rx_power_dbm for e in evaluations]
    quality_counts: dict[str, int] = {}
    for evaluation in evaluations:
        key = evaluation.quality.value
        quality_counts[key] = quality_counts.get(key, 0) + 1

    meets_count = sum(1 for e in evaluations if e.rssi_meets_target)
    sample_target = results[0].stats.get("rssi_target_dbm", -67.0)

    return {
        "point_count": len(evaluations),
        "source_results": len(results),
        "rx_min_dbm": min(rx_values),
        "rx_max_dbm": max(rx_values),
        "rx_avg_dbm": round(sum(rx_values) / len(rx_values), 2),
        "quality_counts": quality_counts,
        "rssi_target_dbm": sample_target,
        "points_meeting_target": meets_count,
        "coverage_ratio": round(meets_count / len(evaluations), 4),
    }
