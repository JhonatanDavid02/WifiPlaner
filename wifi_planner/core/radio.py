"""Configuración de radio de un enlace (AP o dispositivo).

Todas las unidades son explícitas:
- potencia: dBm
- ganancia: dBi
- pérdidas: dB
- sensibilidad: dBm
- fade margin: dB
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RadioConfiguration:
    """Parámetros de presupuesto de enlace.

    Attributes:
        p_tx_dbm: Potencia de transmisión en dBm.
        g_tx_dbi: Ganancia de la antena TX en dBi.
        l_tx_db: Pérdidas TX en dB.
        g_rx_dbi: Ganancia de la antena RX en dBi.
        l_rx_db: Pérdidas RX en dB.
        sensitivity_dbm: Sensibilidad del receptor en dBm.
        fade_margin_db: Margen de desvanecimiento (Lm) en dB.
            Por defecto 10 dB (decisión B). Usar 0 para reproducir
            las versiones legacy v3/v4 que omitían Lm.
    """

    p_tx_dbm: float = 20.0
    g_tx_dbi: float = 3.0
    l_tx_db: float = 1.0
    g_rx_dbi: float = 0.0
    l_rx_db: float = 1.0
    sensitivity_dbm: float = -75.0
    fade_margin_db: float = 10.0

    def __post_init__(self) -> None:
        if self.fade_margin_db < 0:
            raise ValueError("RadioConfiguration.fade_margin_db no puede ser negativo.")
