"""Panel de propiedades del elemento seleccionado + resumen de simulación.

Fase 8: añade edición de espacios (nombre/función) y de aperturas
(tipo/offsets) + creación de aperturas desde la pared seleccionada.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from core.wall import OPENING_KINDS
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
        # Fase 8: openings creados desde la pared seleccionada (BI).
        ttk.Label(wall_box, text="Aperturas:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self._opening_count_var = tk.StringVar(value="0")
        ttk.Label(wall_box, textvariable=self._opening_count_var).grid(
            row=3, column=1, sticky="w", pady=(6, 0)
        )
        btn_row = ttk.Frame(wall_box)
        btn_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._add_door_btn = ttk.Button(
            btn_row, text="+ Puerta", command=lambda: self._add_opening("door")
        )
        self._add_door_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self._add_window_btn = ttk.Button(
            btn_row, text="+ Ventana", command=lambda: self._add_opening("window")
        )
        self._add_window_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))
        wall_box.columnconfigure(1, weight=1)

        # --- Espacio (fase 8: zonas, sin RF — BH) ---
        space_box = ttk.LabelFrame(self, text="Espacio", padding=8)
        space_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(space_box, text="Nombre:").grid(row=0, column=0, sticky="w")
        self._space_name_var = tk.StringVar()
        self._space_name_entry = ttk.Entry(
            space_box, textvariable=self._space_name_var, width=18
        )
        self._space_name_entry.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(space_box, text="Función:").grid(row=1, column=0, sticky="w")
        self._space_function_var = tk.StringVar()
        self._space_function_entry = ttk.Entry(
            space_box, textvariable=self._space_function_var, width=18
        )
        self._space_function_entry.grid(row=1, column=1, sticky="ew", pady=2)

        self._space_apply_btn = ttk.Button(
            space_box, text="Aplicar espacio", command=self._space_apply
        )
        self._space_apply_btn.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        space_box.columnconfigure(1, weight=1)

        # --- Apertura (fase 8: offsets métricos sobre la pared — BG) ---
        opening_box = ttk.LabelFrame(self, text="Apertura", padding=8)
        opening_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(opening_box, text="Tipo:").grid(row=0, column=0, sticky="w")
        self._opening_kind_var = tk.StringVar()
        self._opening_kind_combo = ttk.Combobox(
            opening_box,
            textvariable=self._opening_kind_var,
            values=list(OPENING_KINDS),
            state="readonly",
            width=16,
        )
        self._opening_kind_combo.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(opening_box, text="Inicio (m):").grid(row=1, column=0, sticky="w")
        self._opening_start_var = tk.StringVar()
        self._opening_start_entry = ttk.Entry(
            opening_box, textvariable=self._opening_start_var, width=10
        )
        self._opening_start_entry.grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(opening_box, text="Fin (m):").grid(row=2, column=0, sticky="w")
        self._opening_end_var = tk.StringVar()
        self._opening_end_entry = ttk.Entry(
            opening_box, textvariable=self._opening_end_var, width=10
        )
        self._opening_end_entry.grid(row=2, column=1, sticky="ew", pady=2)

        self._opening_apply_btn = ttk.Button(
            opening_box, text="Aplicar apertura", command=self._opening_apply
        )
        self._opening_apply_btn.grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        opening_box.columnconfigure(1, weight=1)

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

        # --- Simulación + Heatmap ---
        sim_box = ttk.LabelFrame(self, text="Simulación / Heatmap", padding=8)
        sim_box.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        ttk.Button(sim_box, text="Ejecutar simulación", command=self._on_simulate).pack(
            fill="x", pady=(0, 6)
        )
        self._sim_text = tk.Text(
            sim_box, height=6, wrap="word", state="disabled",
            bg="#12121c", fg="#98c379", relief="flat", font=("Consolas", 9),
        )
        self._sim_text.pack(fill="x")

        ttk.Label(sim_box, text="Heatmap (grid):").pack(anchor="w", pady=(8, 2))
        self._heat_text = tk.Text(
            sim_box, height=12, wrap="word", state="disabled",
            bg="#12121c", fg="#4f9cf9", relief="flat", font=("Consolas", 9),
        )
        self._heat_text.pack(fill="both", expand=True)

        self._refresh_materials()
        self.refresh()

    def show_heatmap_text(self, text: str) -> None:
        self._set_text(self._heat_text, text)

    def append_heatmap_text(self, text: str) -> None:
        self._heat_text.configure(state="normal")
        self._heat_text.insert("end", text)
        self._heat_text.configure(state="disabled")

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
            radio = session.project.radio
            thresholds = session.project.thresholds
            self._set_text(
                self._info,
                "Ningún elemento seleccionado.\n\n"
                "Usa las herramientas para crear paredes, APs o clientes.\n\n"
                "Configuración RF (Config RF…):\n"
                f"  Piso de ruido: {radio.noise_floor_dbm:g} dBm\n"
                f"  Objetivo RSSI: > {thresholds.rssi_target_dbm:g} dBm\n"
                f"  Objetivo SNR: ≥ {thresholds.snr_target_db:g} dB\n"
                f"  Estándar: {radio.wifi_standard}\n"
                f"  Ancho de canal: {radio.channel_width_mhz:g} MHz",
            )
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
        elif selection.kind == SelectionKind.SPACE:
            space = session.selected_space()
            if space:
                rect = space.rect
                self._set_text(
                    self._info,
                    f"Espacio\n\n"
                    f"ID: {space.id}\n"
                    f"Nombre: {space.name}\n"
                    f"Función: {space.function or '—'}\n"
                    f"Rect: ({rect.x:.2f}, {rect.y:.2f}) + "
                    f"{rect.width:.2f} × {rect.height:.2f} m",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set("")
                self._y_var.set("")
        elif selection.kind == SelectionKind.OPENING:
            opening = session.selected_opening()
            if opening:
                wall = session.find_wall(opening.wall_id)
                wall_len = wall.segment.length if wall else 0.0
                self._set_text(
                    self._info,
                    f"Apertura ({opening.kind})\n\n"
                    f"ID: {opening.id}\n"
                    f"Pared: {opening.wall_id} ({wall_len:.2f} m)\n"
                    f"Tramo: [{opening.start_offset_m:.2f}, "
                    f"{opening.end_offset_m:.2f}] m\n"
                    f"Longitud: {opening.length_m:.2f} m",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set("")
                self._y_var.set("")

        # --- Estados de los controles Fase 8 (recalculados en cada refresh) ---
        kind = selection.kind if selection is not None else None
        space = session.selected_space() if kind == SelectionKind.SPACE else None
        opening = (
            session.selected_opening() if kind == SelectionKind.OPENING else None
        )
        wall = session.selected_wall() if kind == SelectionKind.WALL else None

        if space is not None:
            self._space_name_var.set(space.name)
            self._space_function_var.set(space.function)
            self._space_name_entry.configure(state="normal")
            self._space_function_entry.configure(state="normal")
            self._space_apply_btn.configure(state="normal")
        else:
            self._space_name_entry.configure(state="disabled")
            self._space_function_entry.configure(state="disabled")
            self._space_apply_btn.configure(state="disabled")

        if opening is not None:
            self._opening_kind_var.set(opening.kind)
            self._opening_start_var.set(f"{opening.start_offset_m:.3f}")
            self._opening_end_var.set(f"{opening.end_offset_m:.3f}")
            self._opening_kind_combo.configure(state="readonly")
            self._opening_start_entry.configure(state="normal")
            self._opening_end_entry.configure(state="normal")
            self._opening_apply_btn.configure(state="normal")
        else:
            self._opening_kind_combo.configure(state="disabled")
            self._opening_start_entry.configure(state="disabled")
            self._opening_end_entry.configure(state="disabled")
            self._opening_apply_btn.configure(state="disabled")

        if wall is not None:
            count = len(session.openings_for_wall(wall.id))
            self._opening_count_var.set(str(count))
            self._add_door_btn.configure(state="normal")
            self._add_window_btn.configure(state="normal")
        else:
            self._opening_count_var.set("—")
            self._add_door_btn.configure(state="disabled")
            self._add_window_btn.configure(state="disabled")

        if session.last_simulation is not None or session.last_simulation_error:
            self._set_text(self._sim_text, session.simulation_summary_text())
        if session.last_heatmap is not None or session.last_heatmap_error:
            self._set_text(self._heat_text, session.heatmap_stats_text())

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

    # ------------------------------------------------------------------
    # Fase 8: espacios y aperturas (solo CRUD vía sesión; nada de RF aquí)
    # ------------------------------------------------------------------

    def _space_apply(self) -> None:
        space = self._session.selected_space()
        if not space:
            return
        try:
            self._session.set_space_properties(
                space.id,
                self._space_name_var.get(),
                self._space_function_var.get(),
            )
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Espacio", str(exc))
            return
        self._on_changed()

    def _opening_apply(self) -> None:
        session = self._session
        opening = session.selected_opening()
        if not opening:
            return
        try:
            start = float(
                self._opening_start_var.get().strip().replace(",", ".")
            )
            end = float(self._opening_end_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror("Apertura", "Offsets inválidos (metros).")
            return
        kind = self._opening_kind_var.get()
        try:
            session.set_opening_offsets(opening.id, start, end)
            if kind != opening.kind:
                session.set_opening_kind(opening.id, kind)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Apertura", str(exc))
            return
        self._on_changed()

    def _add_opening(self, kind: str) -> None:
        wall = self._session.selected_wall()
        if not wall:
            return
        try:
            self._session.add_opening(wall.id, kind)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Apertura", str(exc))
            return
        self._on_changed()
