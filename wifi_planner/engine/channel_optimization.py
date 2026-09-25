"""Optimización de canales Wi-Fi (Fase 13).

F13 es una CAPA DE OPTIMIZACIÓN sobre el modelo RF existente: NO toca la
propagación, el link budget, RSSI/SOM/SNR (F1–F10), la interferencia
espectral (F11) ni el SINR (F12). Todo el peso lo llevan las funciones
ya existentes:

    simulate_coverage (F4) → annotate_interference (F11)
        → annotate_sinr (F12) → combine_results (F5, MAX RSSI)

La pregunta que responde la fase es:

    dada la topología, sus bandas/canales y el modelo RF existente,
    ¿qué asignación de canales produce una configuración globalmente
    mejor según una función de coste explícita, determinista y
    reproducible?

Función de coste (decisión CJ) — una sola cantidad física, sin mezclar
unidades ni pesos arbitrarios:

    score(asignación) = sinr_avg_db del heatmap COMBINADO (ganador por
    MAX RSSI)  →  a MAXIMIZAR

secundario sinr_min_db (calidad del peor punto). El SINR de F12 ya
combina señal, ruido e interferencia en dB con la fórmula única del
modelo; añadir una penalización de interferencia aparte duplicaría la
misma física. Como el canal NO altera RSSI/SNR (decisión BR), el ganador
por punto es idéntico para cualquier asignación: los score son
comparables punto a punto.

Desempate (decisión CL) — clave total de ordenación, de menor a mejor:

    (-sinr_avg_db, -sinr_min_db, nº de cambios vs asignación actual,
     asignación lexicográfica por (ap_id, canal) con None → −1)

Todo es determinista: sin aleatoriedad, sin orden de hash, con los APs
ordenados por id. Si dos asignaciones empatan en las cuatro componentes
la clave es única (los ids son únicos), así que el resultado siempre es
el mismo.

Algoritmo (decisión CK):

1. Semilla = asignación ACTUAL (nunca empeora: solo se acepta una clave
   estrictamente mejor ⇒ una configuración ya óptima no cambia).
2. Si ∏ |candidatos| ≤ EXHAUSTIVE_LIMIT ⇒ BÚSQUEDA EXHAUSTIVA sobre el
   producto cartesiano (óptima respecto a ese espacio y esta función de
   coste; la asignación actual se evalúa siempre como cota).
3. Si no ⇒ DESCENSO COORDENADO acotado y determinista: pases de AP en
   AP (orden de id) probando todos los candidatos de cada AP con los
   demás fijos; se detiene en el primer pase sin mejora o a los
   len(targets) pases. Resultado: óptimo LOCAL no global (el campo
   ``search`` lo declara; nunca se afirma optimalidad que no se tiene).

Candidatos (decisión CN): por defecto el catálogo completo de la banda
válido con el ancho del AP (``core.channel``, fuente única F10); una
petición explícita se FILTRA contra ``validate_channel_config`` (canales
de otra banda, fuera de catálogo o no enteros se descartan). No se
inventa ningún conjunto «1, 6, 11» ni sistema de regulación.

Alcance de la sesión (decisión CM): una banda por corrida (la activa);
solo los APs CON CANAL son optimizables (los APs sin canal quedan fuera
del modelo espectral, decisión CB, y no se les asigna canal); la
evaluación incluye a todos los APs de esa banda para reflejar el
heatmap combinado real. El resultado es una PROPUESTA: los canales del
proyecto solo cambian cuando el llamador aplica la asignación.

Tratamiento de None (decisión CL/CM):

- Asignación con canal ``None`` ⇒ el AP no emite (fuera del modelo).
- Sin resultados base (0 APs) ⇒ score ``None``, sin excepción.
- Stats sin bloque SINR ⇒ score ``None``; en la clave ordena peor que
  cualquier número finito (nunca se convierte ``None`` en 0).

Límites honestos: es optimización de asignación de canales DENTRO del
modelo RF simulado (rectángulos espectrales ideales F11 + SINR F12).
No predice rendimiento real, capacidad ni comportamiento de clientes.
No modela CCA, CSMA, throughput, MCS, roaming, band steering, load
balancing, DFS, detección de hidden nodes, machine learning ni
optimización con datos externos (fuera de alcance de la fase; ver
``docs/decisions.md`` FASE 13). Sin caché, sin hilos, sin dependencias
nuevas (herencia CE).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Mapping, Sequence

from core.band import FrequencyBand
from core.channel import channel_numbers_for_frequency, validate_channel_config
from core.radio import allowed_channel_widths_mhz
from core.result import SimulationResult
from engine.combine import combine_results
from engine.interference import SpectralEmission, annotate_interference
from engine.sinr import annotate_sinr

# Máximo tamaño de espacio para BÚSQUEDA EXHAUSTIVA (decisión CK). Por
# encima se usa descenso coordenado acotado. Es una cota de CORRECTITUD
# de uso, no de física: con grids gruesos el exhaustive es barato, con
# grids finos caro; se prefiere una constante simple y testeable.
EXHAUSTIVE_LIMIT = 64

# Valores de OptimizationResult.search (documentación y tests).
SEARCH_EXHAUSTIVE = "exhaustive"
SEARCH_COORDINATE_DESCENT = "coordinate_descent"


# ---------------------------------------------------------------------------
# Modelo de entrada / salida
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizationTarget:
    """AP optimizable dentro de una banda (decisión CM).

    Attributes:
        ap_id: Id del AP (único dentro de una corrida).
        band: Banda contra la que se validan sus canales.
        width_mhz: Ancho de canal del AP (triple F10, decisión BT).
        current_channel: Canal actual, o ``None`` si no emite (CB).
    """

    ap_id: str
    band: FrequencyBand
    width_mhz: int
    current_channel: int | None


@dataclass(frozen=True)
class AssignmentEvaluation:
    """Evaluación de UNA asignación de canales contra el modelo (F13).

    Attributes:
        assignment: Tupla normalizada ``(ap_id, canal|None)`` ordenada
            por id (inmutable y determinista).
        score: ``sinr_avg_db`` del heatmap combinado (mayor = mejor), o
            ``None`` si no hay evaluación evaluable.
        sinr_min_db: ``sinr_min_db`` del heatmap combinado, o ``None``.
        stats: Copia de las estadísticas combinadas del heatmap (el
            bloque SINR de F12 + cobertura), para la comparación
            antes/después.
    """

    assignment: tuple[tuple[str, int | None], ...]
    score: float | None
    sinr_min_db: float | None
    stats: dict


@dataclass(frozen=True)
class OptimizationResult:
    """Resultado estructurado de la optimización de canales (F13).

    Attributes:
        original_assignment: Asignación actual de los APs optimizables.
        optimized_assignment: Mejor asignación encontrada (propuesta).
        original_score: ``sinr_avg_db`` de la actual, o ``None``.
        optimized_score: ``sinr_avg_db`` de la propuesta, o ``None``.
        improvement: ``optimized_score − original_score`` (dB, ≥ 0),
            o ``None`` si alguno de los score no es evaluable.
        changed: ``True`` si la propuesta difiere de la actual.
        search: ``"exhaustive"`` (óptima respecto al espacio evaluado)
            o ``"coordinate_descent"`` (óptimo local, no global).
        evaluation_count: Número de asignaciones evaluadas.
        original_stats: Estadísticas combinadas de la actual.
        optimized_stats: Estadísticas combinadas de la propuesta.
    """

    original_assignment: dict[str, int | None]
    optimized_assignment: dict[str, int | None]
    original_score: float | None
    optimized_score: float | None
    improvement: float | None
    changed: bool
    search: str
    evaluation_count: int
    original_stats: dict
    optimized_stats: dict


# ---------------------------------------------------------------------------
# Candidatos (decisión CN)
# ---------------------------------------------------------------------------


def candidate_channels(band: FrequencyBand, width_mhz: int) -> tuple[int, ...]:
    """Canales candidatos por defecto para ``(banda, ancho)``.

    Es el catálogo completo de la familia de la banda (fuente única F10,
    ``core.channel``) validado con el ancho del AP: no se inventa ningún
    subconjunto (1/6/11 ni similar) ni se modela regulación (§10 F13).

    Raises:
        ValueError: si el ancho no es un entero permitido para la banda.
    """
    allowed = allowed_channel_widths_mhz(band.frequency_mhz)
    if isinstance(width_mhz, bool) or not isinstance(width_mhz, int):
        raise ValueError(f"Ancho de canal inválido: {width_mhz!r}.")
    if width_mhz not in allowed:
        raise ValueError(
            f"Ancho de canal {width_mhz} MHz no permitido en {band.name}; "
            f"permitidos: {', '.join(str(w) for w in allowed)} MHz."
        )
    return channel_numbers_for_frequency(band.frequency_mhz)


def _is_valid_channel(band: FrequencyBand, channel, width_mhz: int) -> bool:
    """True si ``(banda, canal, ancho)`` pasa la validación única F10."""
    try:
        validate_channel_config(band, channel, width_mhz)
    except ValueError:
        return False
    return True


def _requested_candidates(
    targets: Sequence[OptimizationTarget],
    requested: Mapping[str, Sequence[int]] | None,
) -> dict[str, tuple[int, ...]]:
    """Candidatos por AP: petición explícita FILTRADA o catálogo (CN).

    Raises:
        ValueError: si ``requested`` menciona un AP que no es objetivo.
    """
    ids = {t.ap_id for t in targets}
    if requested is not None:
        unknown = sorted(set(requested) - ids)
        if unknown:
            raise ValueError(
                f"Candidatos pedidos para APs desconocidos: {', '.join(unknown)}."
            )
    out: dict[str, tuple[int, ...]] = {}
    for target in targets:
        raw = requested.get(target.ap_id) if requested is not None else None
        if raw is None:
            out[target.ap_id] = candidate_channels(target.band, target.width_mhz)
            continue
        valid = {
            channel
            for channel in raw
            if _is_valid_channel(target.band, channel, target.width_mhz)
        }
        out[target.ap_id] = tuple(sorted(valid))
    return out


# ---------------------------------------------------------------------------
# Validación de entrada
# ---------------------------------------------------------------------------


def _validate_targets(
    targets: Sequence[OptimizationTarget],
    base_results: Mapping[str, SimulationResult],
) -> list[OptimizationTarget]:
    """Valida los objetivos y devuelve la lista ordenada por ``ap_id``.

    Raises:
        ValueError: ids duplicados, ancho no permitido para la banda o
            un objetivo sin resultados base (no se puede anotar su
            emisión sin sus propias evaluaciones).
    """
    ordered = sorted(targets, key=lambda t: t.ap_id)
    ids = [t.ap_id for t in ordered]
    if len(set(ids)) != len(ids):
        raise ValueError(f"APs objetivos duplicados: {ids}.")
    for target in ordered:
        allowed = allowed_channel_widths_mhz(target.band.frequency_mhz)
        if target.width_mhz not in allowed:
            raise ValueError(
                f"Ancho de canal {target.width_mhz} MHz no permitido en "
                f"{target.band.name} para {target.ap_id}."
            )
        if target.ap_id not in base_results:
            raise ValueError(
                f"Sin resultados base para {target.ap_id}: no se puede "
                "evaluar su emisión espectral."
            )
    return ordered


def _normalize_assignment(
    targets: Sequence[OptimizationTarget],
    assignment: Mapping[str, int | None],
) -> dict[str, int | None]:
    """Copia validada de la asignación (``None`` = sin emisión).

    Cada canal entero se valida con el MISMO validador único F10
    (``validate_channel_config``): banda, catálogo y ancho.

    Raises:
        ValueError: si faltan o sobran APs o si algún canal no es
            válido para la banda/ancho del AP.
    """
    ids = {t.ap_id for t in targets}
    given = set(assignment)
    if given != ids:
        missing = sorted(ids - given)
        extra = sorted(given - ids)
        parts = []
        if missing:
            parts.append(f"faltan: {', '.join(missing)}")
        if extra:
            parts.append(f"sobran: {', '.join(extra)}")
        raise ValueError("Asignación incompleta (" + "; ".join(parts) + ").")
    normalized: dict[str, int | None] = {}
    for target in targets:
        channel = assignment[target.ap_id]
        if channel is None:
            normalized[target.ap_id] = None
            continue
        validate_channel_config(target.band, channel, target.width_mhz)
        normalized[target.ap_id] = channel
    return normalized


# ---------------------------------------------------------------------------
# Evaluación (reutiliza el pipeline F4→F11→F12→F5 sin replicar fórmulas)
# ---------------------------------------------------------------------------


def evaluate_channel_assignment(
    targets: Sequence[OptimizationTarget],
    assignment: Mapping[str, int | None],
    base_results: Mapping[str, SimulationResult],
    thresholds,
) -> AssignmentEvaluation:
    """Evalúa una asignación de canales con el modelo RF existente.

    Secuencia (sin duplicar física ni fórmulas; invariantes I2/I3):

        base_results (RSSI/SNR F1–F10, ya simulados) →
        annotate_interference (F11, emisiones de la asignación) →
        annotate_sinr (F12) → combine_results (F5, MAX RSSI intacto)

    El canal NO modifica RSSI/SNR (decisión BR): los resultados base se
    reutilizan tal cual y SOLO cambia la capa de interferencia/SINR.
    ``base_results`` debe contener al menos a todos los ``targets``; los
    resultados extra (p. ej. APs de la banda sin canal) entran en la
    combinación sin emisión (decisión CB). Nada se muta: anotación y
    combinación construyen objetos nuevos (propiedad «no mutación»).

    Args:
        targets: APs optimizables de la banda (se ordenan por id).
        assignment: ``{ap_id: canal | None}`` con EXACTAMENTE los ids de
            ``targets``.
        base_results: ``{ap_id: SimulationResult}`` ya simulados (crudos,
            sin anotar), mismo grid para todos.
        thresholds: ``CoverageThresholds`` (umbral ``sinr_target_db``).

    Returns:
        ``AssignmentEvaluation`` con score y stats combinados. Sin
        resultados base devuelve score ``None`` (0 APs, sin excepción).

    Raises:
        ValueError: objetivos inválidos o asignación que no coincide
            con los ids / canal fuera de la banda o ancho.
    """
    ordered = _validate_targets(targets, base_results)
    normalized = _normalize_assignment(ordered, assignment)
    if not base_results:
        return AssignmentEvaluation(
            assignment=tuple(sorted(normalized.items())),
            score=None,
            sinr_min_db=None,
            stats={},
        )

    emissions: dict[str, SpectralEmission] = {}
    for target in ordered:
        channel = normalized[target.ap_id]
        if channel is None:
            continue  # AP sin canal: fuera del modelo espectral (CB).
        validated = validate_channel_config(
            target.band, channel, target.width_mhz
        )
        emissions[target.ap_id] = SpectralEmission(
            ap_id=target.ap_id,
            center_frequency_mhz=validated.center_frequency_mhz,
            width_mhz=float(target.width_mhz),
        )

    # Orden estable por id de AP (la anotación y la combinación son
    # deterministas; el orden de entrada no cambia el resultado).
    results = [base_results[ap_id] for ap_id in sorted(base_results)]
    annotated = annotate_interference(results, emissions)
    annotated = annotate_sinr(annotated, thresholds)
    combined = (
        annotated[0] if len(annotated) == 1 else combine_results(annotated)
    )
    stats = dict(combined.stats or {})
    return AssignmentEvaluation(
        assignment=tuple(sorted(normalized.items())),
        score=stats.get("sinr_avg_db"),
        sinr_min_db=stats.get("sinr_min_db"),
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Coste y desempate (decisiones CJ / CL)
# ---------------------------------------------------------------------------


def _optimization_key(
    evaluation: AssignmentEvaluation,
    original: Mapping[str, int | None],
) -> tuple:
    """Clave total de ordenación de una asignación (mejor = menor).

    Componentas, en orden (decisión CL):

    1. ``-sinr_avg_db`` (score, a maximizar). ``None`` ⇒ ``+inf``
       (peor que cualquier score finito; jamás ``None → 0``).
    2. ``-sinr_min_db`` (peor punto; mismas reglas que 1).
    3. Nº de APs cuyo canal difiere de la ASIGNACIÓN ACTUAL (menos
       cambios ⇒ preferido en empates de score).
    4. La asignación ordenada por ``(ap_id, canal)`` con ``None → −1``
       (lexicográfica determinista; rompe empates restantes).
    """
    if evaluation.score is not None:
        primary: float = -evaluation.score
    else:
        primary = float("inf")
    if evaluation.sinr_min_db is not None:
        secondary: float = -evaluation.sinr_min_db
    else:
        secondary = float("inf")
    changes = sum(
        1
        for ap_id, channel in evaluation.assignment
        if original.get(ap_id) != channel
    )
    order = tuple(
        (ap_id, -1 if channel is None else channel)
        for ap_id, channel in evaluation.assignment
    )
    return (primary, secondary, changes, order)


# ---------------------------------------------------------------------------
# Optimización (decisión CK)
# ---------------------------------------------------------------------------


def optimize_channels(
    targets: Sequence[OptimizationTarget],
    base_results: Mapping[str, SimulationResult],
    thresholds,
    requested_candidates: Mapping[str, Sequence[int]] | None = None,
) -> OptimizationResult:
    """Propone la mejor asignación de canales según la función de coste.

    Determinista y no mutante (invariantes I4/I6/L): la semilla es la
    asignación actual y solo se aceptan claves estrictamente mejores, de
    modo que una configuración ya óptima devuelve ``changed=False`` y un
    empatado total conserva la actual (menor nº de cambios, decisión CL).

    Args:
        targets: APs optimizables (se ordenan por id; el orden de
            entrada no afecta al resultado).
        base_results: Resultados ya simulados por AP (crudos).
        thresholds: ``CoverageThresholds``.
        requested_candidates: Candidatos opcionales por ``ap_id``; se
            filtran contra el validador F10 y se ordenan. Ausente ⇒
            catálogo completo de la banda (``candidate_channels``).

    Returns:
        ``OptimizationResult`` con la asignación original y la
        propuesta, score y stats de ambas, ``improvement`` (≥ 0 o
        ``None``), ``changed``, ``search`` y ``evaluation_count``.
        Sin APs/objetivos devuelve la estructura vacía sin excepción.

    Raises:
        ValueError: objetivos o candidatos mal formados (AP desconocido,
            ancho no permitido, asignación inconsistente).
    """
    ordered = _validate_targets(targets, base_results)
    original = {t.ap_id: t.current_channel for t in ordered}
    candidates = _requested_candidates(ordered, requested_candidates)

    original_eval = evaluate_channel_assignment(ordered, original, base_results, thresholds)
    best_assignment = dict(original)
    best_eval = original_eval
    best_key = _optimization_key(original_eval, original)
    evaluation_count = 1

    # Un AP SIN candidatos alternativos queda fijo en su canal actual
    # dentro del producto (su semilla ya se evaluó aparte): no debe
    # anular las combinaciones de los demás APs.
    search_lists: list[list[int | None]] = []
    for target in ordered:
        options: Sequence[int | None] = candidates[target.ap_id]
        if not options:
            options = (
                [target.current_channel]
                if target.current_channel is not None
                else [None]
            )
        search_lists.append(list(options))

    space = 1
    for options in search_lists:
        space *= len(options)

    if space <= EXHAUSTIVE_LIMIT:
        search = SEARCH_EXHAUSTIVE
        ids = [t.ap_id for t in ordered]
        for combo in itertools.product(*search_lists):
            candidate = dict(zip(ids, combo))
            if candidate == original:
                continue  # ya evaluada como semilla
            evaluation = evaluate_channel_assignment(
                ordered, candidate, base_results, thresholds
            )
            evaluation_count += 1
            key = _optimization_key(evaluation, original)
            if key < best_key:
                best_key, best_eval, best_assignment = key, evaluation, candidate
    else:
        search = SEARCH_COORDINATE_DESCENT
        current = dict(original)
        # Pases acotados: como máximo uno por AP (mejora monótona en
        # clave estricta ⇒ en len(targets)+1 pases se repite estado).
        for _pass in range(max(1, len(ordered))):
            improved = False
            for target in ordered:
                for channel in candidates[target.ap_id]:
                    if current[target.ap_id] == channel:
                        continue
                    trial = dict(current)
                    trial[target.ap_id] = channel
                    evaluation = evaluate_channel_assignment(
                        ordered, trial, base_results, thresholds
                    )
                    evaluation_count += 1
                    key = _optimization_key(evaluation, original)
                    if key < best_key:
                        best_key, best_eval = key, evaluation
                        current = trial
                        improved = True
            if not improved:
                break
        best_assignment = current

    improvement: float | None = None
    if best_eval.score is not None and original_eval.score is not None:
        improvement = round(best_eval.score - original_eval.score, 2)

    return OptimizationResult(
        original_assignment=dict(original),
        optimized_assignment=dict(best_assignment),
        original_score=original_eval.score,
        optimized_score=best_eval.score,
        improvement=improvement,
        changed=best_assignment != original,
        search=search,
        evaluation_count=evaluation_count,
        original_stats=dict(original_eval.stats),
        optimized_stats=dict(best_eval.stats),
    )


__all__ = [
    "EXHAUSTIVE_LIMIT",
    "SEARCH_COORDINATE_DESCENT",
    "SEARCH_EXHAUSTIVE",
    "AssignmentEvaluation",
    "OptimizationResult",
    "OptimizationTarget",
    "candidate_channels",
    "evaluate_channel_assignment",
    "optimize_channels",
]
