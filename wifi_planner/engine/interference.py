"""Interacción espectral e interferencia Wi-Fi (Fase 11).

F11 añade INTERACCIÓN ENTRE EMISORES sin tocar la física histórica de
propagación: FSPL, link budget, RSSI, SOM, SNR, paredes, openings y
obstáculos siguen siendo exactamente los de F1–F10. La interferencia es
información **paralela** que F12 usará para el SINR; en F11 **NO se
calcula SINR** (frontera F11 → F12, decisión CD).

Modelo de ocupación espectral (simplificado, decisión BY):

    banda ocupada = centro ± ancho/2        (rectángulo ideal)

Es una aproximación de ingeniería para planificación: NO representa la
máscara espectral PHY real (sin lobulaciones, guard bands ni ruido
espectral). La frecuencia central se deriva del catálogo F10
(``core.channel``); este módulo no duplica tablas de frecuencias.

Solapamiento (decisión BY):

    overlap       = max(0, min(hi_a, hi_b) − max(lo_a, lo_b))
    overlap_ratio = overlap / min(width_a, width_b)

Los intervalos se tratan como **semiabiertos** [lo, hi): dos emisiones
que solo se tocan en un borde tienen solapamiento 0 (determinista).

Contribución efectiva de un interferente (decisión BZ, modelo con PSD
plano rectangular — fórmula derivada, no una penalización arbitraria):

    I_dBm = P_rx,i + 10·log10(overlap / W_i)      si overlap > 0

Supuestos: la densidad espectral de potencia del interferente es plana
sobre su ancho W_i, y el receptor desea solo el intervalo intersectado.
Propiedades: monótona en overlap, acotada arriba por P_rx,i
(overlap ≤ W_i ⇒ término ≤ 0 dB) y con límite físico: overlap = 0 ⇒ el
interferente **no contribuye** (no se usa −∞). La función está aislada
en ``effective_interference_dbm`` y puede reemplazarse en F12/F14.

Agregación (decisión CA): las potencias en dBm NO se suman; se convierten
a mW, se suman linealmente y se vuelve a dBm. Sin contribuidores ⇒
``None`` (decisión CA: representación explícita, sin inventar −∞).

Ámbito (decisión CB): solo interactúan APs **de la misma banda** y
**con canal configurado**; un AP sin canal queda fuera del modelo
espectral pero su RSSI histórico sigue funcionando.

Determinismo (decisión CA): los contribuidores se recorren y ordenan por
``access_point_id``; el dominante es la mayor contribución y en empate
gana el menor id. El orden del proyecto o del JSON no cambia el
resultado. Este módulo es puro, sin UI, sin estado y testeable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from core.band import FrequencyBand
from core.channel import channel_for_band
from core.result import LinkEvaluation, SimulationResult


def _finite(name: str, value) -> float:
    """Valida que ``value`` sea un número finito (no bool) y lo devuelve."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} debe ser un número (got {value!r}).")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} debe ser finita (got {value!r}).")
    return number


def _positive(name: str, value) -> float:
    """Valida número finito e > 0."""
    number = _finite(name, value)
    if number <= 0:
        raise ValueError(f"{name} debe ser > 0 (got {number}).")
    return number


# ---------------------------------------------------------------------------
# Dominio lineal de potencia (utilidad centralizada, decisión CA)
# ---------------------------------------------------------------------------


def dbm_to_mw(dbm: float) -> float:
    """Convierte dBm → mW: ``P_mW = 10^(P_dBm / 10)``.

    Raises:
        ValueError: si el valor no es finito.
    """
    return 10.0 ** (_finite("dbm", dbm) / 10.0)


def mw_to_dbm(mw: float) -> float:
    """Convierte mW → dBm: ``P_dBm = 10·log10(P_mW)``.

    Raises:
        ValueError: si el valor no es finito o no es > 0.
    """
    power = _positive("mw", mw)
    return 10.0 * math.log10(power)


def aggregate_dbm(powers_dbm: Sequence[float]) -> float | None:
    """Suma potencias en dBm pasando por el dominio lineal (decisión CA).

    ``dBm ≠ unidad aditiva``: se convierte cada potencia a mW, se suman
    y se vuelve a dBm (2 decimales, determinista).

    Args:
        powers_dbm: Potencias en dBm (pueden estar vacías).

    Returns:
        La potencia total en dBm, o ``None`` si no hay contribuidores
        (decisión CA: representación explícita, sin inventar −∞).

    Raises:
        ValueError: si alguna potencia no es finita.
    """
    total_mw = 0.0
    for power in powers_dbm:
        total_mw += dbm_to_mw(power)
    if not powers_dbm:
        return None
    return round(mw_to_dbm(total_mw), 2)


# ---------------------------------------------------------------------------
# Ocupación y solapamiento espectral (decisión BY)
# ---------------------------------------------------------------------------


def occupied_interval_mhz(
    center_frequency_mhz: float, width_mhz: float
) -> tuple[float, float]:
    """Intervalo ocupado simplificado: ``centro ± ancho/2`` (MHz).

    Raises:
        ValueError: si el centro no es finito y > 0 o el ancho no es
            finito y > 0.
    """
    center = _positive("center_frequency_mhz", center_frequency_mhz)
    width = _positive("width_mhz", width_mhz)
    return (center - width / 2.0, center + width / 2.0)


@dataclass(frozen=True)
class SpectralOverlap:
    """Solapamiento entre dos emisiones (decisión BY).

    Attributes:
        overlap_mhz: Intersección de los intervalos en MHz (≥ 0).
        overlap_ratio: ``overlap / min(width_a, width_b)`` en [0, 1].
            Coincidencia exacta ⇒ 1.0; un intervalo contenido en otro
            (el menor) ⇒ 1.0; disjuntos o tocados ⇒ 0.0.
    """

    overlap_mhz: float
    overlap_ratio: float

    def __post_init__(self) -> None:
        overlap = _finite("overlap_mhz", self.overlap_mhz)
        if overlap < 0:
            raise ValueError("overlap_mhz no puede ser negativo.")
        ratio = _finite("overlap_ratio", self.overlap_ratio)
        if not (0.0 <= ratio <= 1.0):
            raise ValueError(f"overlap_ratio debe estar en [0, 1] (got {ratio}).")
        object.__setattr__(self, "overlap_mhz", round(overlap, 6))
        object.__setattr__(self, "overlap_ratio", round(ratio, 6))


def spectral_overlap(
    center_a_mhz: float,
    width_a_mhz: float,
    center_b_mhz: float,
    width_b_mhz: float,
) -> SpectralOverlap:
    """Solapamiento espectral entre dos emisiones (simétrico).

    Trata los intervalos como semiabiertos: ``A termina exactamente
    donde empieza B`` ⇒ ``0 MHz / 0 %`` (determinista, decisión BY).

    Returns:
        ``SpectralOverlap`` con ``overlap_mhz`` y ``overlap_ratio``
        (fracción del ancho menor cubierta).

    Raises:
        ValueError: si centros/anchos no son válidos.
    """
    lo_a, hi_a = occupied_interval_mhz(center_a_mhz, width_a_mhz)
    lo_b, hi_b = occupied_interval_mhz(center_b_mhz, width_b_mhz)
    overlap = max(0.0, min(hi_a, hi_b) - max(lo_a, lo_b))
    narrowest = min(float(_positive("width_a_mhz", width_a_mhz)),
                    float(_positive("width_b_mhz", width_b_mhz)))
    ratio = overlap / narrowest if narrowest > 0 else 0.0
    return SpectralOverlap(overlap_mhz=overlap, overlap_ratio=ratio)


def effective_interference_dbm(
    interferer_rx_dbm: float,
    overlap_mhz: float,
    interferer_width_mhz: float,
) -> float | None:
    """Contribución efectiva de un interferente (modelo F11, decisión BZ).

    ``I = P_rx,i + 10·log10(overlap / W_i)`` con PSD plano rectangular
    (ver docstring del módulo). Es una **aproximación de ingeniería**,
    determinista, monótona y acotada: nunca supera la potencia
    recibida del interferente (``overlap ≤ W_i``).

    Args:
        interferer_rx_dbm: Potencia recibida del interferente en dBm
            (mismo pipeline de propagación F1–F10; sin física nueva).
        overlap_mhz: Intersección espectral en MHz (≥ 0).
        interferer_width_mhz: Ancho de canal del interferente en MHz.

    Returns:
        La contribución en dBm, o ``None`` si ``overlap == 0`` (sin
        solapamiento no hay contribución; no se usa −∞, decisión CA).

    Raises:
        ValueError: si los valores no son finitos o ``overlap`` excede
            el ancho del interferente (imposible con ``spectral_overlap``).
    """
    rx = _finite("interferer_rx_dbm", interferer_rx_dbm)
    overlap = _finite("overlap_mhz", overlap_mhz)
    width = _positive("interferer_width_mhz", interferer_width_mhz)
    if overlap < 0:
        raise ValueError("overlap_mhz no puede ser negativo.")
    if overlap > width:
        raise ValueError(
            f"overlap ({overlap:g} MHz) no puede exceder el ancho del "
            f"interferente ({width:g} MHz)."
        )
    if overlap <= 0:
        return None
    fraction = overlap / width
    return round(rx + 10.0 * math.log10(fraction), 2)


# ---------------------------------------------------------------------------
# Emisión espectral de un AP (información estructural del dominio)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpectralEmission:
    """Emisión espectral de un AP (centro derivado del catálogo F10).

    Attributes:
        ap_id: Id del AP emisor.
        center_frequency_mhz: Frecuencia central (derivada, decisión BR).
        width_mhz: Ancho de canal del AP (``radio.channel_width_mhz``).
    """

    ap_id: str
    center_frequency_mhz: float
    width_mhz: float

    def __post_init__(self) -> None:
        ap_id = self.ap_id
        if not isinstance(ap_id, str) or not ap_id:
            raise ValueError(f"SpectralEmission.ap_id inválido: {ap_id!r}.")
        object.__setattr__(
            self, "center_frequency_mhz",
            _positive("center_frequency_mhz", self.center_frequency_mhz),
        )
        object.__setattr__(
            self, "width_mhz", _positive("width_mhz", self.width_mhz)
        )

    @property
    def interval_mhz(self) -> tuple[float, float]:
        """Intervalo ocupado ``[centro − ancho/2, centro + ancho/2)``."""
        return occupied_interval_mhz(self.center_frequency_mhz, self.width_mhz)


def emission_for_ap(access_point, band: FrequencyBand) -> SpectralEmission | None:
    """Emisión espectral del AP en ``band``, o ``None`` sin canal.

    Un AP **sin canal configurado** no participa en el modelo espectral
    (decisión CB): su RSSI histórico continúa funcionando, pero no puede
    ser ni deseado ni interferente aquí.

    Raises:
        ValueError: si el canal del AP no pertenece a la banda (mismo
            error que el guard de ``engine.simulator``, decisión BT).
    """
    if access_point.channel is None:
        return None
    channel = channel_for_band(band, access_point.channel)
    return SpectralEmission(
        ap_id=access_point.id,
        center_frequency_mhz=channel.center_frequency_mhz,
        width_mhz=float(access_point.radio.channel_width_mhz),
    )


# ---------------------------------------------------------------------------
# Anotación de interferencia por punto (reutiliza los resultados existentes)
# ---------------------------------------------------------------------------


def annotate_interference(
    results: Sequence[SimulationResult],
    emissions: Mapping[str, SpectralEmission],
) -> list[SimulationResult]:
    """Anota la interferencia de cada evaluación con los otros APs (F11).

    No duplica física: la potencia recibida de cada interferente es la
    de su propia ``LinkEvaluation`` (mismo FSPL, mismas paredes,
    openings y obstáculos que F1–F10). Este módulo SOLO combina
    potencia recibida + relación espectral (parte conceptual de F12).

    Reglas:

    - Los resultados se agrupan por ``band_id``: jamás hay interacción
      entre bandas distintas (decisión CB; el contrato F5 de bandas
      mixtas no cambia).
    - Un AP sin emisión (sin canal) no participa: sus evaluaciones
      quedan **sin anotar** (campos por defecto, decisión CB).
    - Con emisión deseada: la evaluación queda marcada
      ``interference_evaluated=True`` aunque no haya contribuidores
      (resultado honesto: 0 interferentes).
    - Contribuidores: otros APs del mismo grupo con emisión y
      ``overlap > 0``. Sin contribuidores ⇒ ``interference_dbm=None``.
    - Determinismo (decisión CA): contribuciones ordenadas por
      (−potencia, id); dominante = mayor contribución, empate ⇒ menor
      ``access_point_id``; la suma lineal sigue ese orden canónico.

    Args:
        results: Resultados (habitualmente uno por AP) a anotar.
        emissions: ``{ap_id: SpectralEmission}`` solo para APs con canal.

    Returns:
        Nueva lista en el MISMO orden. Las evaluaciones sin cambios se
        reutilizan (mismo objeto); las anotadas se construyen con
        ``replace`` (no se muta nada).
    """
    results_list = list(results)
    if not results_list:
        return []

    # Índice de resultados por banda (solo dentro de cada banda, CB).
    indices_by_band: dict[str, list[int]] = {}
    for index, result in enumerate(results_list):
        indices_by_band.setdefault(result.band_id, []).append(index)

    annotated: list[SimulationResult | None] = [None] * len(results_list)

    for band_group in indices_by_band.values():
        # Evaluaciones por punto para todo el grupo de la banda.
        evals_by_point: dict[tuple[float, float], dict[str, LinkEvaluation]] = {}
        for index in band_group:
            for evaluation in results_list[index].evaluations:
                key = (evaluation.point.x, evaluation.point.y)
                evals_by_point.setdefault(key, {})[
                    evaluation.access_point_id
                ] = evaluation

        for index in band_group:
            result = results_list[index]
            if not result.evaluations:
                annotated[index] = result
                continue
            desired_id = result.evaluations[0].access_point_id
            desired_emission = emissions.get(desired_id)
            if desired_emission is None:
                # AP sin canal: fuera del modelo espectral (CB).
                annotated[index] = result
                continue

            new_evaluations: list[LinkEvaluation] = []
            for evaluation in result.evaluations:
                key = (evaluation.point.x, evaluation.point.y)
                at_point = evals_by_point.get(key, {})
                contributions: list[tuple[str, float]] = []
                for other_id in sorted(at_point):
                    if other_id == desired_id:
                        continue
                    other_emission = emissions.get(other_id)
                    if other_emission is None:
                        continue
                    overlap = spectral_overlap(
                        desired_emission.center_frequency_mhz,
                        desired_emission.width_mhz,
                        other_emission.center_frequency_mhz,
                        other_emission.width_mhz,
                    )
                    if overlap.overlap_mhz <= 0:
                        continue  # disjuntos o tocados: sin contribución
                    contribution = effective_interference_dbm(
                        at_point[other_id].rx_power_dbm,
                        overlap.overlap_mhz,
                        other_emission.width_mhz,
                    )
                    if contribution is None:
                        continue
                    contributions.append((other_id, contribution))

                if not contributions:
                    new_evaluations.append(
                        replace(evaluation, interference_evaluated=True)
                    )
                    continue
                # Orden canónico: mayor contribución primero, empate por id.
                contributions.sort(key=lambda item: (-item[1], item[0]))
                total = aggregate_dbm([c[1] for c in contributions])
                new_evaluations.append(
                    replace(
                        evaluation,
                        interference_evaluated=True,
                        interference_dbm=total,
                        interferer_count=len(contributions),
                        dominant_interferer_ap_id=contributions[0][0],
                    )
                )
            annotated[index] = replace(
                result, evaluations=tuple(new_evaluations)
            )

    return [item for item in annotated if item is not None]


# ---------------------------------------------------------------------------
# Resumen para UI (consumo de campos; sin fórmulas nuevas)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterferenceSummary:
    """Resumen de interferencia de las evaluaciones de un AP (F11).

    Attributes:
        point_count: Evaluaciones consideradas.
        evaluated_points: Evaluaciones anotadas por el modelo F11.
        interference_max_dbm: Mayor potencia agregada en dBm, o None.
        interferer_count_max: Máximo de interferentes en un punto.
        dominant_interferer_ap_id: Dominante en el punto de mayor
            agregado (empate ⇒ menor id), o None.
    """

    point_count: int
    evaluated_points: int
    interference_max_dbm: float | None
    interferer_count_max: int
    dominant_interferer_ap_id: str | None


def interference_summary(
    evaluations: Sequence[LinkEvaluation],
) -> InterferenceSummary | None:
    """Resume las evaluaciones de un AP para el panel (decisión CC).

    Returns:
        ``None`` si no hay evaluaciones; en caso contrario un resumen
        (con ``evaluated_points == 0`` si el modelo F11 no corrió, para
        que la UI distinga «sin datos» de «0 interferentes»).
    """
    evals = list(evaluations)
    if not evals:
        return None
    evaluated = [e for e in evals if e.interference_evaluated]
    if not evaluated:
        return InterferenceSummary(
            point_count=len(evals),
            evaluated_points=0,
            interference_max_dbm=None,
            interferer_count_max=0,
            dominant_interferer_ap_id=None,
        )
    with_power = [e for e in evaluated if e.interference_dbm is not None]
    max_dbm: float | None = None
    dominant: str | None = None
    if with_power:
        max_dbm = max(e.interference_dbm for e in with_power)
        tied = [e for e in with_power if e.interference_dbm == max_dbm]
        ids = sorted(
            e.dominant_interferer_ap_id
            for e in tied
            if e.dominant_interferer_ap_id is not None
        )
        dominant = ids[0] if ids else None
    return InterferenceSummary(
        point_count=len(evals),
        evaluated_points=len(evaluated),
        interference_max_dbm=max_dbm,
        interferer_count_max=max(e.interferer_count for e in evaluated),
        dominant_interferer_ap_id=dominant,
    )


__all__ = [
    "SpectralEmission",
    "SpectralOverlap",
    "InterferenceSummary",
    "aggregate_dbm",
    "annotate_interference",
    "dbm_to_mw",
    "effective_interference_dbm",
    "emission_for_ap",
    "interference_summary",
    "mw_to_dbm",
    "occupied_interval_mhz",
    "spectral_overlap",
]
