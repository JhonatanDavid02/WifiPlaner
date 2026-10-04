"""Estado RF de los clientes (clasificación + evaluación puntual).

Un cliente NO emite: su estado es la lectura del RSSI real que recibe en
SU posición exacta, obtenida con la MISMA ruta que usa el heatmap
(``engine.simulator.simulate_coverage``, Fase 4 → Fase 15).

No hay modelo RF nuevo, ni fórmulas propias, ni una simulación paralela,
ni lectura de píxeles/colores del heatmap: el color del heatmap es solo
pintura de un resultado; aquí se vuelve a pedir ese resultado al motor
para la posición del cliente (los nodos del ``CoverageGrid`` casi nunca
coinciden con la posición libre del cliente, además el heatmap puede
estar apagado o acotado a un solo AP).

Los límites de clasificación viven en este archivo (``*_MIN_DBM``): es el
único sitio a tocar para ajustarlos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.client import ClientDevice
from engine.simulator import simulate_coverage

if TYPE_CHECKING:  # solo anotaciones; evita el ciclo con ui.session
    from ui.session import EditorSession

# ---------------------------------------------------------------------------
# Límites de clasificación (única fuente de verdad; fácil de modificar)
# ---------------------------------------------------------------------------
#   RSSI >= -55 dBm ............ SEÑAL BUENA
#   -67 <= RSSI <  -55 dBm ..... SEÑAL FUERTE
#   -75 <= RSSI <  -67 dBm ..... SEÑAL DÉBIL
#   -85 <= RSSI <  -75 dBm ..... SEÑAL INESTABLE
#   RSSI < -85 dBm, sin evaluación o fuera de cobertura → SIN SEÑAL
BUENA_MIN_DBM = -55.0
FUERTE_MIN_DBM = -67.0
DEBIL_MIN_DBM = -75.0
INESTABLE_MIN_DBM = -85.0

STATE_BUENA = "SEÑAL BUENA"
STATE_FUERTE = "SEÑAL FUERTE"
STATE_DEBIL = "SEÑAL DÉBIL"
STATE_INESTABLE = "SEÑAL INESTABLE"
STATE_SIN_SENAL = "SIN SEÑAL"

STATE_SLUG: dict[str, str] = {
    STATE_BUENA: "buena",
    STATE_FUERTE: "fuerte",
    STATE_DEBIL: "debil",
    STATE_INESTABLE: "inestable",
    STATE_SIN_SENAL: "sin_senal",
}


def state_for_rssi(rssi_dbm: float | None) -> str:
    """Clasifica un RSSI en uno de los cinco estados del cliente.

    Args:
        rssi_dbm: RSSI en dBm, o None cuando no hay evaluación (sin AP,
            banda sin datos de atenuación, configuración inválida...).

    Returns:
        Uno de los ``STATE_*`` de este módulo.
    """
    if rssi_dbm is None or not math.isfinite(rssi_dbm):
        return STATE_SIN_SENAL
    if rssi_dbm >= BUENA_MIN_DBM:
        return STATE_BUENA
    if rssi_dbm >= FUERTE_MIN_DBM:
        return STATE_FUERTE
    if rssi_dbm >= DEBIL_MIN_DBM:
        return STATE_DEBIL
    if rssi_dbm >= INESTABLE_MIN_DBM:
        return STATE_INESTABLE
    return STATE_SIN_SENAL


def state_slug(state: str) -> str:
    """Slug corto del estado (tags del canvas, nombres de color...)."""
    return STATE_SLUG.get(state, "sin_senal")


@dataclass(frozen=True)
class ClientSignalState:
    """Lectura RF de un cliente en su posición exacta.

    Attributes:
        client_id: Id del cliente evaluado.
        state: Etiqueta de estado (``state_for_rssi``).
        ap_id: AP que mejor RSSI aporta en esa posición (None = no se
            pudo evaluar ninguno). Puede haber ap_id con ``state`` =
            SIN SEÑAL: hay un intento de medición pero por debajo del
            umbral no hay señal utilizable.
        band_id: Banda con la que se evaluó ese AP.
        band_name: Nombre legible de esa banda (ej. "2.4 GHz").
        rssi_dbm: RSSI del AP ganador (None si no hay evaluación).
        snr_db: SNR del AP ganador en ese punto.
        distance_m: Distancia AP → cliente en metros.
    """

    client_id: str
    state: str
    ap_id: str | None = None
    band_id: str | None = None
    band_name: str = ""
    rssi_dbm: float | None = None
    snr_db: float | None = None
    distance_m: float | None = None

    @property
    def measured(self) -> bool:
        """True si hubo al menos una evaluación (RSSI conocido)."""
        return self.rssi_dbm is not None

    @property
    def associated(self) -> bool:
        """True si hay un AP con señal utilizable (no SIN SEÑAL)."""
        return (
            self.ap_id is not None
            and self.rssi_dbm is not None
            and self.state != STATE_SIN_SENAL
        )


def evaluate_client_state(
    session: EditorSession, client: ClientDevice
) -> ClientSignalState:
    """Evalúa la señal real de un cliente en su posición exacta.

    Recorre TODOS los APs del proyecto con ``simulate_coverage`` (una
    sola muestra: la posición del cliente) y conserva el de mayor RSSI,
    con la misma regla de desempate que ``engine.combine`` (mayor P_rx;
    empate → menor id de AP). La asociación AP→cliente es ese ganador:
    el modelo no guarda una asociación propia.

    Cada AP se simula en su banda resuelta (decisión F10). Si un AP no
    puede evaluarse (banda sin datos de atenuación, ancho/canal
    incompatible), se omite ese AP y no rompe al resto; si no queda ninguno
    el resultado es ``SIN SEÑAL``.

    Args:
        session: Sesión del editor (proyecto, piso, banda activa).
        client: Cliente a evaluar.

    Returns:
        ``ClientSignalState`` con el estado clasificado.
    """
    best = None
    best_band = None
    for ap in session.project.access_points:
        try:
            band = session.resolve_band_for_ap(ap, session.band_id)
            result = simulate_coverage(
                project=session.project,
                access_point=ap,
                frequency_band=band,
                sample_points=[client.position],
                walls=session.floor.walls,
                openings=session.floor.openings,
                obstacles=session.floor.obstacles,
            )
        except (ValueError, KeyError):
            # ValueError: ancho/canal incompatible con la banda.
            # KeyError: banda desconocida o MaterialAttenuationError
            # (subclase de KeyError: banda sin datos de atenuación).
            continue
        for evaluation in result.evaluations:
            better_rssi = best is None or evaluation.rx_power_dbm > best.rx_power_dbm
            tie = (
                best is not None
                and evaluation.rx_power_dbm == best.rx_power_dbm
                and evaluation.access_point_id < best.access_point_id
            )
            if better_rssi or tie:
                best, best_band = evaluation, band

    if best is None or best_band is None:
        return ClientSignalState(client_id=client.id, state=STATE_SIN_SENAL)

    return ClientSignalState(
        client_id=client.id,
        state=state_for_rssi(best.rx_power_dbm),
        ap_id=best.access_point_id,
        band_id=best_band.id,
        band_name=best_band.name,
        rssi_dbm=best.rx_power_dbm,
        snr_db=best.snr_db,
        distance_m=best.distance_m,
    )
