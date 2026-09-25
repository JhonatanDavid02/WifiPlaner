"""Diálogo de configuración RF global (Fase 7 + Fase 12).

Reúne piso de ruido, objetivos de SNR/SINR/RSSI, estándar Wi-Fi y ancho
de canal. La validación real vive en ``core/`` (dataclasses): aquí solo
se parsea la entrada y se muestra el ``ValueError`` controlado. El ancho
de canal NO afecta a FSPL; se valida contra la banda al simular.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from core.radio import (
    CHANNEL_WIDTHS_MHZ,
    NOISE_FLOOR_MAX_DBM,
    NOISE_FLOOR_MIN_DBM,
    WIFI_STANDARDS,
)

# (noise_floor_dbm, snr_target_db, rssi_target_dbm, wifi_standard,
#  channel_width_mhz, sinr_target_db)
RFApplyCallback = Callable[[float, float, float, str, int, float], None]


class RFSettingsDialog(tk.Toplevel):
    """Pide la configuración RF global y la aplica de forma atómica."""

    def __init__(
        self,
        master,
        *,
        noise_floor_dbm: float,
        snr_target_db: float,
        rssi_target_dbm: float,
        wifi_standard: str,
        channel_width_mhz: int,
        sinr_target_db: float,
        on_apply: RFApplyCallback,
    ) -> None:
        super().__init__(master)
        self.title("Configuración RF")
        self.resizable(False, False)
        self.transient(master)
        self._on_apply = on_apply
        self._noise_var = tk.StringVar(value=f"{noise_floor_dbm:g}")
        self._snr_var = tk.StringVar(value=f"{snr_target_db:g}")
        self._rssi_var = tk.StringVar(value=f"{rssi_target_dbm:g}")
        self._standard_var = tk.StringVar(value=wifi_standard)
        self._width_var = tk.StringVar(value=str(int(channel_width_mhz)))
        self._sinr_var = tk.StringVar(value=f"{sinr_target_db:g}")
        self._build()
        self.grab_set()
        self._noise_entry.focus_set()

    def _build(self) -> None:
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Piso de ruido (dBm):").grid(
            row=0, column=0, sticky="w", pady=4
        )
        self._noise_entry = ttk.Entry(body, textvariable=self._noise_var, width=12)
        self._noise_entry.grid(row=0, column=1, pady=4, padx=(8, 0))

        ttk.Label(body, text="Objetivo SNR (dB):").grid(
            row=1, column=0, sticky="w", pady=4
        )
        ttk.Entry(body, textvariable=self._snr_var, width=12).grid(
            row=1, column=1, pady=4, padx=(8, 0)
        )

        ttk.Label(body, text="Objetivo SINR (dB):").grid(
            row=2, column=0, sticky="w", pady=4
        )
        ttk.Entry(body, textvariable=self._sinr_var, width=12).grid(
            row=2, column=1, pady=4, padx=(8, 0)
        )

        ttk.Label(body, text="Objetivo RSSI (dBm):").grid(
            row=3, column=0, sticky="w", pady=4
        )
        ttk.Entry(body, textvariable=self._rssi_var, width=12).grid(
            row=3, column=1, pady=4, padx=(8, 0)
        )

        ttk.Label(body, text="Estándar Wi-Fi:").grid(
            row=4, column=0, sticky="w", pady=4
        )
        ttk.Combobox(
            body,
            textvariable=self._standard_var,
            values=list(WIFI_STANDARDS),
            state="readonly",
            width=12,
        ).grid(row=4, column=1, pady=4, padx=(8, 0))

        ttk.Label(body, text="Ancho de canal (MHz):").grid(
            row=5, column=0, sticky="w", pady=4
        )
        ttk.Combobox(
            body,
            textvariable=self._width_var,
            values=[str(w) for w in CHANNEL_WIDTHS_MHZ],
            state="readonly",
            width=12,
        ).grid(row=5, column=1, pady=4, padx=(8, 0))

        ttk.Label(
            body,
            text=(
                f"Piso de ruido entre {NOISE_FLOOR_MIN_DBM:g} y "
                f"{NOISE_FLOOR_MAX_DBM:g} dBm. El SNR es P_rx − piso de "
                f"ruido; el SINR añade la interferencia al denominador y "
                f"complementa al RSSI. El ancho de canal no "
                f"modifica FSPL; 2.4 GHz admite 20/40 MHz."
            ),
            foreground="#9a9aa8",
            wraplength=320,
            justify="left",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = ttk.Frame(body)
        btns.grid(row=7, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(btns, text="Aplicar", command=self._apply).pack(side="right")

    def _apply(self) -> None:
        try:
            noise_floor = float(
                self._noise_var.get().strip().replace(",", ".")
            )
            snr_target = float(self._snr_var.get().strip().replace(",", "."))
            rssi_target = float(self._rssi_var.get().strip().replace(",", "."))
            standard = self._standard_var.get().strip()
            width = int(self._width_var.get().strip())
            sinr_target = float(self._sinr_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror(
                "Configuración RF",
                "Introduce valores numéricos válidos.",
                parent=self,
            )
            return

        try:
            self._on_apply(
                noise_floor, snr_target, rssi_target, standard, width, sinr_target
            )
        except ValueError as exc:
            messagebox.showerror("Configuración RF", str(exc), parent=self)
            return
        self.destroy()


__all__ = ["RFSettingsDialog"]
