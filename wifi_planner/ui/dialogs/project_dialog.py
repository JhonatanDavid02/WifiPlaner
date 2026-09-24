"""Diálogo para definir el tamaño del espacio físico (metros)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable


class ProjectDimensionsDialog(tk.Toplevel):
    """Pide ancho y alto del espacio en metros (> 0)."""

    def __init__(
        self,
        master,
        width_m: float,
        height_m: float,
        on_apply: Callable[[float, float], None],
    ) -> None:
        super().__init__(master)
        self.title("Dimensiones del espacio")
        self.resizable(False, False)
        self.transient(master)
        self._on_apply = on_apply
        self._width_var = tk.StringVar(value=f"{width_m:g}")
        self._height_var = tk.StringVar(value=f"{height_m:g}")
        self._build()
        self.grab_set()
        self._width_entry.focus_set()

    def _build(self) -> None:
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Ancho (m):").grid(row=0, column=0, sticky="w", pady=4)
        self._width_entry = ttk.Entry(body, textvariable=self._width_var, width=12)
        self._width_entry.grid(row=0, column=1, pady=4, padx=(8, 0))

        ttk.Label(body, text="Alto (m):").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=self._height_var, width=12).grid(
            row=1, column=1, pady=4, padx=(8, 0)
        )

        ttk.Label(
            body, text="El espacio se guarda en metros (no en píxeles).",
            foreground="#9a9aa8",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = ttk.Frame(body)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Aplicar", command=self._apply).pack(side="right")

    def _apply(self) -> None:
        try:
            width = float(self._width_var.get().strip().replace(",", "."))
            height = float(self._height_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror(
                "Dimensiones", "Introduce valores numéricos válidos.", parent=self
            )
            return
        if width <= 0 or height <= 0:
            messagebox.showerror(
                "Dimensiones", "Ancho y alto deben ser > 0 metros.", parent=self
            )
            return
        if width > 10_000 or height > 10_000:
            messagebox.showerror(
                "Dimensiones", "Máximo 10000 m por lado.", parent=self
            )
            return
        try:
            self._on_apply(width, height)
        except ValueError as exc:
            messagebox.showerror("Dimensiones", str(exc), parent=self)
            return
        self.destroy()
