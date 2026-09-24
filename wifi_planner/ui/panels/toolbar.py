"""Barra de herramientas del editor."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ui.session import Tool


class Toolbar(ttk.Frame):
    """Herramientas, banda, dimensiones del espacio y simulación."""

    def __init__(
        self,
        master,
        on_tool: Callable[[Tool], None],
        on_band: Callable[[str], None],
        on_simulate: Callable[[], None],
        on_dimensions: Callable[[], None],
        on_delete: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_tool = on_tool
        self._on_band = on_band
        self._on_simulate = on_simulate
        self._on_dimensions = on_dimensions
        self._on_delete = on_delete
        self._tool_var = tk.StringVar(value=Tool.SELECT.value)
        self._band_var = tk.StringVar(value="2.4 GHz")
        self._build()

    def _build(self) -> None:
        pad = {"padx": 4, "pady": 4}

        ttk.Label(self, text="Herramienta:").grid(row=0, column=0, **pad)

        tools = [
            (Tool.SELECT, "Seleccionar"),
            (Tool.WALL, "Pared"),
            (Tool.AP, "AP"),
            (Tool.CLIENT, "Cliente"),
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
            row=0, column=5, sticky="ns", padx=8, pady=4
        )

        ttk.Label(self, text="Banda:").grid(row=0, column=6, **pad)
        band_combo = ttk.Combobox(
            self,
            textvariable=self._band_var,
            values=["2.4 GHz", "5 GHz"],
            state="readonly",
            width=8,
        )
        band_combo.grid(row=0, column=7, **pad)
        band_combo.bind("<<ComboboxSelected>>", self._band_changed)

        ttk.Button(self, text="Eliminar", command=self._on_delete).grid(
            row=0, column=8, padx=4, pady=4
        )
        ttk.Button(self, text="Espacio…", command=self._on_dimensions).grid(
            row=0, column=9, padx=4, pady=4
        )
        ttk.Button(self, text="Simular", command=self._on_simulate).grid(
            row=0, column=10, padx=4, pady=4
        )
        self.columnconfigure(11, weight=1)

    def _tool_changed(self) -> None:
        self._on_tool(Tool(self._tool_var.get()))

    def _band_changed(self, _event=None) -> None:
        label = self._band_var.get()
        band_id = "band_5" if label.startswith("5") else "band_2_4"
        self._on_band(band_id)
