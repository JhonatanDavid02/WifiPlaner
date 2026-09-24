"""Barra de herramientas del editor."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ui.session import HEATMAP_ALL_APS, Tool

# Etiquetas visibles ↔ ids de banda (una sola tabla en la toolbar).
BAND_LABEL_BY_ID = {"band_2_4": "2.4 GHz", "band_5": "5 GHz", "band_6": "6 GHz"}
BAND_ID_BY_LABEL = {label: band_id for band_id, label in BAND_LABEL_BY_ID.items()}

# Etiquetas visibles ↔ métricas del heatmap (Fase 7).
METRIC_LABEL_BY_ID = {"rssi": "RSSI", "snr": "SNR"}
METRIC_ID_BY_LABEL = {label: metric_id for metric_id, label in METRIC_LABEL_BY_ID.items()}


class Toolbar(ttk.Frame):
    """Herramientas, banda, resolución, heatmap, dimensiones y simulación."""

    RESOLUTION_CHOICES = ("1.00", "0.50", "0.25")

    def __init__(
        self,
        master,
        on_tool: Callable[[Tool], None],
        on_band: Callable[[str], None],
        on_simulate: Callable[[], None],
        on_dimensions: Callable[[], None],
        on_delete: Callable[[], None],
        on_resolution: Callable[[float], None] | None = None,
        on_heatmap_toggle: Callable[[bool], None] | None = None,
        on_heatmap_ap: Callable[[str], None] | None = None,
        on_heatmap_metric: Callable[[str], None] | None = None,
        on_rf_settings: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_tool = on_tool
        self._on_band = on_band
        self._on_simulate = on_simulate
        self._on_dimensions = on_dimensions
        self._on_delete = on_delete
        self._on_resolution = on_resolution or (lambda _r: None)
        self._on_heatmap_toggle = on_heatmap_toggle or (lambda _e: None)
        self._on_heatmap_ap = on_heatmap_ap or (lambda _a: None)
        self._on_heatmap_metric = on_heatmap_metric or (lambda _m: None)
        self._on_rf_settings = on_rf_settings or (lambda: None)
        self._tool_var = tk.StringVar(value=Tool.SELECT.value)
        self._band_var = tk.StringVar(value="2.4 GHz")
        self._res_var = tk.StringVar(value="0.50")
        self._heatmap_var = tk.BooleanVar(value=True)
        self._ap_var = tk.StringVar(value=HEATMAP_ALL_APS)
        self._metric_var = tk.StringVar(value=METRIC_LABEL_BY_ID["rssi"])
        self._ap_combo = None
        self._build()

    def _build(self) -> None:
        pad = {"padx": 4, "pady": 4}

        ttk.Label(self, text="Herramienta:").grid(row=0, column=0, **pad)

        tools = [
            (Tool.SELECT, "Seleccionar"),
            (Tool.WALL, "Pared"),
            (Tool.AP, "AP"),
            (Tool.CLIENT, "Cliente"),
            (Tool.SPACE, "Zona"),
        ]
        for col, (tool, label) in enumerate(tools, start=1):
            ttk.Radiobutton(
                self,
                text=label,
                value=tool.value,
                variable=self._tool_var,
                command=self._tool_changed,
            ).grid(row=0, column=col, padx=3, pady=4)

        ttk.Separator(self, orient="vertical").grid(
            row=0, column=6, sticky="ns", padx=8, pady=4
        )

        ttk.Label(self, text="Banda:").grid(row=0, column=7, **pad)
        band_combo = ttk.Combobox(
            self,
            textvariable=self._band_var,
            values=["2.4 GHz", "5 GHz", "6 GHz"],
            state="readonly",
            width=8,
        )
        band_combo.grid(row=0, column=8, **pad)
        band_combo.bind("<<ComboboxSelected>>", self._band_changed)

        ttk.Label(self, text="AP:").grid(row=0, column=9, **pad)
        self._ap_combo = ttk.Combobox(
            self,
            textvariable=self._ap_var,
            values=[HEATMAP_ALL_APS],
            state="readonly",
            width=14,
        )
        self._ap_combo.grid(row=0, column=10, **pad)
        self._ap_combo.bind("<<ComboboxSelected>>", self._ap_changed)

        ttk.Label(self, text="Res.:").grid(row=0, column=11, **pad)
        res_combo = ttk.Combobox(
            self,
            textvariable=self._res_var,
            values=list(self.RESOLUTION_CHOICES),
            state="readonly",
            width=6,
        )
        res_combo.grid(row=0, column=12, **pad)
        res_combo.bind("<<ComboboxSelected>>", self._resolution_changed)

        ttk.Checkbutton(
            self,
            text="Heatmap",
            variable=self._heatmap_var,
            command=self._heatmap_changed,
        ).grid(row=0, column=13, padx=4, pady=4)

        # Fase 7: métrica del heatmap (vista: RSSI / SNR).
        ttk.Label(self, text="Métrica:").grid(row=0, column=14, **pad)
        metric_combo = ttk.Combobox(
            self,
            textvariable=self._metric_var,
            values=list(METRIC_LABEL_BY_ID.values()),
            state="readonly",
            width=7,
        )
        metric_combo.grid(row=0, column=15, **pad)
        metric_combo.bind("<<ComboboxSelected>>", self._metric_changed)

        ttk.Button(self, text="Eliminar", command=self._on_delete).grid(
            row=0, column=16, padx=4, pady=4
        )
        ttk.Button(self, text="Dimensiones…", command=self._on_dimensions).grid(
            row=0, column=17, padx=4, pady=4
        )
        ttk.Button(self, text="Config RF…", command=self._on_rf_settings).grid(
            row=0, column=18, padx=4, pady=4
        )
        ttk.Button(self, text="Simular", command=self._on_simulate).grid(
            row=0, column=19, padx=4, pady=4
        )
        self.columnconfigure(20, weight=1)

    def set_ap_choices(self, choices: list[str], current: str | None = None) -> None:
        """Actualiza el selector de AP.

        ``choices`` son **etiquetas** visibles (p. ej. "Todos los AP", "AP-001").
        El var interno guarda la etiqueta; ``get_selected_ap_id`` la mapea.
        """
        if self._ap_combo is None:
            return
        if not choices:
            choices = ["Todos los AP"]
        self._ap_combo["values"] = list(choices)
        value = current if current is not None else self._ap_var.get()
        if value in choices:
            self._ap_var.set(value)
        elif value == HEATMAP_ALL_APS:
            self._ap_var.set("Todos los AP")
        else:
            self._ap_var.set(choices[0])

    def get_selected_ap_id(self) -> str:
        """Devuelve el id interno del AP seleccionado (o HEATMAP_ALL_APS)."""
        shown = self._ap_var.get()
        if shown in ("Todos los AP", HEATMAP_ALL_APS, ""):
            return HEATMAP_ALL_APS
        return shown

    def set_band_label(self, label: str) -> None:
        """Sincroniza el combo de banda con una etiqueta conocida."""
        if label in BAND_ID_BY_LABEL:
            self._band_var.set(label)

    def set_resolution_value(self, resolution_m: float) -> None:
        """Sincroniza el combo de resolución con un valor del modelo."""
        pretty = f"{resolution_m:.2f}"
        self._res_var.set(
            pretty if pretty in self.RESOLUTION_CHOICES else f"{resolution_m:g}"
        )

    def set_heatmap_enabled(self, enabled: bool) -> None:
        """Sincroniza el checkbox del heatmap con el modelo."""
        self._heatmap_var.set(bool(enabled))

    def set_metric(self, metric_id: str) -> None:
        """Sincroniza el combo de métrica con el modelo ('rssi'/'snr')."""
        label = METRIC_LABEL_BY_ID.get(metric_id)
        if label:
            self._metric_var.set(label)

    def get_metric(self) -> str:
        """Id interno de la métrica seleccionada ('rssi' por defecto)."""
        return METRIC_ID_BY_LABEL.get(self._metric_var.get(), "rssi")

    def _tool_changed(self) -> None:
        self._on_tool(Tool(self._tool_var.get()))

    def _band_changed(self, _event=None) -> None:
        label = self._band_var.get()
        self._on_band(BAND_ID_BY_LABEL.get(label, "band_2_4"))

    def _ap_changed(self, _event=None) -> None:
        self._on_heatmap_ap(self.get_selected_ap_id())

    def _resolution_changed(self, _event=None) -> None:
        try:
            value = float(self._res_var.get().replace(",", "."))
        except ValueError:
            return
        self._on_resolution(value)

    def _heatmap_changed(self) -> None:
        self._on_heatmap_toggle(bool(self._heatmap_var.get()))

    def _metric_changed(self, _event=None) -> None:
        self._on_heatmap_metric(self.get_metric())
