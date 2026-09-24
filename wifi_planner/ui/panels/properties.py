"""Panel de propiedades del elemento seleccionado + resumen de simulación."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from ui.session import EditorSession, SelectionKind


class PropertiesPanel(ttk.Frame):
    """Muestra y edita propiedades del elemento seleccionado.

    No contiene fórmulas RF: lee/escribe el modelo vía EditorSession.
    """

    def __init__(
        self,
        master,
        session: EditorSession,
        on_changed: Callable[[], None],
        on_simulate: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, width=280, **kwargs)
        self.pack_propagate(False)
        self._session = session
        self._on_changed = on_changed
        self._on_simulate = on_simulate
        self._suppress = False

        self._build()

    def _build(self) -> None:
        # --- Selección ---
        sel_box = ttk.LabelFrame(self, text="Selección", padding=8)
        sel_box.pack(fill="x", padx=8, pady=(8, 4))

        self._info = tk.Text(
            sel_box, height=8, wrap="word", state="disabled",
            bg="#12121c", fg="#e0e0e0", relief="flat", font=("Segoe UI", 9),
        )
        self._info.pack(fill="x")

        # --- Pared: material / espesor ---
        wall_box = ttk.LabelFrame(self, text="Pared", padding=8)
        wall_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(wall_box, text="Material:").grid(row=0, column=0, sticky="w")
        self._material_var = tk.StringVar()
        self._material_combo = ttk.Combobox(
            wall_box, textvariable=self._material_var, state="readonly", width=18
        )
        self._material_combo.grid(row=0, column=1, sticky="ew", pady=2)
        self._material_combo.bind("<<ComboboxSelected>>", self._material_selected)

        ttk.Label(wall_box, text="Espesor (m):").grid(row=1, column=0, sticky="w")
        self._thickness_var = tk.StringVar()
        self._thickness_entry = ttk.Entry(wall_box, textvariable=self._thickness_var, width=12)
        self._thickness_entry.grid(row=1, column=1, sticky="ew", pady=2)
        self._thickness_entry.bind("<FocusOut>", self._thickness_apply)
        self._thickness_entry.bind("<Return>", self._thickness_apply)

        ttk.Button(wall_box, text="Aplicar espesor", command=self._thickness_apply).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        wall_box.columnconfigure(1, weight=1)

        # --- Coordenadas AP / Cliente ---
        pos_box = ttk.LabelFrame(self, text="Posición (m)", padding=8)
        pos_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(pos_box, text="X:").grid(row=0, column=0, sticky="w")
        self._x_var = tk.StringVar()
        ttk.Entry(pos_box, textvariable=self._x_var, width=10).grid(
            row=0, column=1, sticky="ew", pady=2
        )
        ttk.Label(pos_box, text="Y:").grid(row=1, column=0, sticky="w")
        self._y_var = tk.StringVar()
        ttk.Entry(pos_box, textvariable=self._y_var, width=10).grid(
            row=1, column=1, sticky="ew", pady=2
        )
        ttk.Button(pos_box, text="Aplicar posición", command=self._position_apply).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        pos_box.columnconfigure(1, weight=1)

        # --- Simulación ---
        sim_box = ttk.LabelFrame(self, text="Simulación", padding=8)
        sim_box.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        ttk.Button(sim_box, text="Ejecutar simulación", command=self._on_simulate).pack(
            fill="x", pady=(0, 6)
        )
        self._sim_text = tk.Text(
            sim_box, height=8, wrap="word", state="disabled",
            bg="#12121c", fg="#98c379", relief="flat", font=("Consolas", 9),
        )
        self._sim_text.pack(fill="both", expand=True)

        self._refresh_materials()
        self.refresh()

    def _refresh_materials(self) -> None:
        materials = self._session.project.materials
        values = [m.id for m in materials]
        self._material_combo["values"] = values

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def refresh(self) -> None:
        """Relee el modelo y actualiza los controles."""
        if self._suppress:
            return
        session = self._session
        selection = session.selection

        if selection is None:
            self._set_text(self._info, "Ningún elemento seleccionado.\n\n"
                            "Usa las herramientas para crear paredes, APs o clientes.")
            self._material_combo.configure(state="disabled")
            self._thickness_entry.configure(state="disabled")
            self._x_var.set("")
            self._y_var.set("")
        elif selection.kind == SelectionKind.WALL:
            wall = session.selected_wall()
            if wall:
                length = wall.segment.length
                thick = (
                    wall.thickness_m
                    if wall.thickness_m is not None
                    else wall.material.thickness_default_m
                )
                self._set_text(
                    self._info,
                    f"Wall\n\n"
                    f"ID: {wall.id}\n"
                    f"Material: {wall.material.name} ({wall.material.id})\n"
                    f"Espesor: {thick} m\n"
                    f"Longitud: {length:.2f} m\n"
                    f"Inicio: ({wall.segment.start.x:.2f}, {wall.segment.start.y:.2f}) m\n"
                    f"Fin: ({wall.segment.end.x:.2f}, {wall.segment.end.y:.2f}) m",
                )
                self._material_combo.configure(state="readonly")
                self._thickness_entry.configure(state="normal")
                self._material_var.set(wall.material.id)
                self._thickness_var.set(f"{thick:.4g}")
                self._x_var.set("")
                self._y_var.set("")
        elif selection.kind == SelectionKind.AP:
            ap = session.selected_ap()
            if ap:
                self._set_text(
                    self._info,
                    f"Access Point\n\n"
                    f"ID: {ap.id}\n"
                    f"X: {ap.position.x:.2f} m\n"
                    f"Y: {ap.position.y:.2f} m",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set(f"{ap.position.x:.3f}")
                self._y_var.set(f"{ap.position.y:.3f}")
        elif selection.kind == SelectionKind.CLIENT:
            client = session.selected_client()
            if client:
                self._set_text(
                    self._info,
                    f"Cliente\n\n"
                    f"ID: {client.id}\n"
                    f"X: {client.position.x:.2f} m\n"
                    f"Y: {client.position.y:.2f} m",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set(f"{client.position.x:.3f}")
                self._y_var.set(f"{client.position.y:.3f}")

        if session.last_simulation is not None or session.last_simulation_error:
            self._set_text(self._sim_text, session.simulation_summary_text())

    def show_simulation_text(self, text: str) -> None:
        self._set_text(self._sim_text, text)

    def _material_selected(self, _event=None) -> None:
        wall = self._session.selected_wall()
        if not wall:
            return
        try:
            self._session.set_wall_material(wall.id, self._material_var.get())
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Material", str(exc))
            return
        self._on_changed()

    def _thickness_apply(self, _event=None) -> None:
        wall = self._session.selected_wall()
        if not wall:
            return
        raw = self._thickness_var.get().strip().replace(",", ".")
        try:
            thickness = float(raw)
        except ValueError:
            messagebox.showerror("Espesor", f"Valor inválido: {raw!r}")
            return
        try:
            self._session.set_wall_thickness(wall.id, thickness)
        except ValueError as exc:
            messagebox.showerror("Espesor", str(exc))
            return
        self._on_changed()

    def _position_apply(self) -> None:
        session = self._session
        selection = session.selection
        if selection is None:
            return
        try:
            x = float(self._x_var.get().strip().replace(",", "."))
            y = float(self._y_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror("Posición", "Coordenadas inválidas (metros).")
            return
        from core.geometry import Point2D

        point = Point2D(x, y)
        try:
            if selection.kind == SelectionKind.AP:
                session.move_ap(selection.entity_id, point)
            elif selection.kind == SelectionKind.CLIENT:
                session.move_client(selection.entity_id, point)
            else:
                return
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Posición", str(exc))
            return
        self._on_changed()
