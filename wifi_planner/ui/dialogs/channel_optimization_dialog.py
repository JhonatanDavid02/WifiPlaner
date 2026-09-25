"""Diálogo de propuesta de optimización de canales (Fase 13).

Presenta el resultado de ``session.optimize_channels``: búsqueda usada,
nº de evaluaciones, score SINR actual → propuesto y la asignación AP
por AP. La optimización es SIEMPRE una PROPUESTA: los canales no
cambian hasta que el usuario pulsa «Aplicar propuesta», que delega en
``on_apply`` (decisión CM: sin auto-aplicar; paso «Aplicar» de la spec).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from engine.channel_optimization import (
    SEARCH_COORDINATE_DESCENT,
    SEARCH_EXHAUSTIVE,
    OptimizationResult,
)

# Etiquetas visibles de la estrategia de búsqueda (spec: búsqueda y coste).
SEARCH_LABEL = {
    SEARCH_EXHAUSTIVE: "Exhaustiva",
    SEARCH_COORDINATE_DESCENT: "Descenso coordinado",
}

ApplyCallback = Callable[[OptimizationResult], None]


def _fmt(value: float | None, unit: str = "") -> str:
    """Formatea un número opcional (None → «—»)."""
    if value is None:
        return "—"
    return f"{value:.2f}{unit}"


class ChannelOptimizationDialog(tk.Toplevel):
    """Muestra la propuesta de canales y solo la aplica si se confirma."""

    def __init__(
        self,
        master,
        *,
        result: OptimizationResult,
        on_apply: ApplyCallback,
    ) -> None:
        super().__init__(master)
        self.title("Optimización de canales")
        self.resizable(False, False)
        self.transient(master)
        self._result = result
        self._on_apply = on_apply
        self._build()
        self.grab_set()

    def _build(self) -> None:
        result = self._result
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        search_label = SEARCH_LABEL.get(result.search, result.search)
        ttk.Label(
            body,
            text=(
                f"Búsqueda: {search_label}  ·  "
                f"{result.evaluation_count} evaluaciones"
            ),
            font=("", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        if result.changed:
            delta = result.improvement if result.improvement is not None else 0.0
            summary = (
                f"SINR promedio: {_fmt(result.original_score, ' dB')} → "
                f"{_fmt(result.optimized_score, ' dB')}  (+{_fmt(delta, ' dB')})"
            )
        else:
            summary = (
                "Sin cambios: la asignación actual ya es la mejor "
                "propuesta por el modelo (óptimo local)."
            )
        ttk.Label(body, text=summary).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        orig_min = result.original_stats.get("sinr_min_db")
        opt_min = result.optimized_stats.get("sinr_min_db")
        ttk.Label(
            body,
            text=(
                f"SINR mínimo: {_fmt(orig_min, ' dB')} → {_fmt(opt_min, ' dB')}"
            ),
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        # Tabla AP: actual → propuesto.
        table = ttk.Treeview(
            body,
            columns=("ap", "actual", "propuesto"),
            show="headings",
            height=min(max(len(result.optimized_assignment), 3), 12),
        )
        table.heading("ap", text="AP")
        table.heading("actual", text="Actual")
        table.heading("propuesto", text="Propuesto")
        table.column("ap", width=120, anchor="w")
        table.column("actual", width=80, anchor="center")
        table.column("propuesto", width=100, anchor="center")
        for ap_id in sorted(result.optimized_assignment):
            current = result.original_assignment.get(ap_id)
            proposed = result.optimized_assignment.get(ap_id)
            table.insert(
                "",
                "end",
                values=(ap_id, current if current is not None else "—", proposed),
            )
        table.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(10, 0))

        ttk.Label(
            body,
            text=(
                "Propuesta: todavía no se ha modificado ningún canal. "
                "El heatmap y el proyecto se actualizan solo al aplicar."
                if result.changed
                else "No hay nada que aplicar."
            ),
            foreground="#9a9aa8",
            wraplength=340,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = ttk.Frame(body)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Cerrar", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        apply_btn = ttk.Button(
            btns, text="Aplicar propuesta", command=self._apply
        )
        apply_btn.pack(side="right")
        if not result.changed:
            apply_btn.state(["disabled"])

    def _apply(self) -> None:
        try:
            self._on_apply(self._result)
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Optimización de canales", str(exc), parent=self)
            return
        self.destroy()


__all__ = ["ChannelOptimizationDialog"]
