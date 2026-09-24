"""Estado del editor: operaciones puras sobre Project (sin Tkinter).

Esta capa es testeable sin abrir la ventana. La UI (Canvas/panels)
la invoca y luego vuelve a dibujar desde el Project (fuente de verdad).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable

from core.access_point import AccessPoint
from core.client import ClientDevice
from core.geometry import Point2D, Segment2D
from core.material import Material
from core.project import Project
from core.result import SimulationResult
from core.space import Floor
from core.wall import Wall
from engine.combine import combine_results
from engine.coverage_grid import CoverageGrid
from engine.simulator import simulate_coverage
from persistence import EditorState
from persistence import load_project as _load_document
from persistence import save_project as _save_document

# Selector de heatmap: todos los APs (cobertura combinada, Fase 5).
HEATMAP_ALL_APS = "__all__"


class Tool(str, Enum):
    """Herramientas del editor."""

    SELECT = "select"
    WALL = "wall"
    AP = "ap"
    CLIENT = "client"


class SelectionKind(str, Enum):
    WALL = "wall"
    AP = "ap"
    CLIENT = "client"


@dataclass(frozen=True)
class Selection:
    """Elemento seleccionado en el editor."""

    kind: SelectionKind
    entity_id: str


def next_entity_id(existing_ids: Iterable[str], prefix: str) -> str:
    """Genera el siguiente ID estable: AP-001, WALL-001, CLIENT-001."""
    max_n = 0
    token = f"{prefix}-"
    for entity_id in existing_ids:
        if entity_id.startswith(token):
            suffix = entity_id[len(token) :]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
    return f"{prefix}-{max_n + 1:03d}"


def create_default_project() -> Project:
    """Proyecto inicial del editor: 12 m × 8 m, sin elementos."""
    from config import load_config

    cfg = load_config()
    project = Project(
        name="Wi-Fi Planner — Proyecto nuevo",
        bands=cfg["bands"],
        materials=cfg["materials"],
        radio=cfg["radio"],
        thresholds=cfg["thresholds"],
    )
    floor = Floor(
        id="FLOOR-001",
        name="Planta baja",
        width_m=12.0,
        height_m=8.0,
    )
    project.floors.append(floor)
    return project


class EditorSession:
    """Operaciones del editor sobre el Project (sin UI).

    La fuente de verdad es siempre ``project``. El Canvas solo pinta.
    """

    def __init__(self, project: Project | None = None) -> None:
        self.project = project if project is not None else create_default_project()
        self.tool: Tool = Tool.SELECT
        self.selection: Selection | None = None
        # Punto de inicio mientras se dibuja una pared (metros).
        self.wall_drag_start: Point2D | None = None
        self.band_id: str = "band_2_4"
        self.last_simulation: SimulationResult | None = None
        self.last_simulation_error: str | None = None
        # Fase 4: heatmap espacial
        self.grid_resolution_m: float = 0.5
        self.heatmap_enabled: bool = True
        # Fase 5: HEATMAP_ALL_APS (combinado) o id de un AP concreto.
        self.heatmap_ap_id: str = HEATMAP_ALL_APS
        self.last_heatmap: SimulationResult | None = None
        self.last_heatmap_error: str | None = None
        self.heatmap_dirty: bool = True
        # Fase 6: persistencia. Ruta del documento y cambios sin guardar.
        self.project_path: str | None = None
        self.dirty: bool = False

    # ------------------------------------------------------------------
    # Cambios sin guardar (Fase 6)
    # ------------------------------------------------------------------

    def mark_dirty(self) -> None:
        """Marca el proyecto como modificado desde la última guarda."""
        self.dirty = True

    def mark_saved(self, path: str | None = None) -> None:
        """Marca el proyecto como guardado (opcionalmente en una ruta)."""
        if path is not None:
            self.project_path = str(path)
        self.dirty = False

    # ------------------------------------------------------------------
    # Persistencia (Fase 6): guardar / abrir / nuevo
    # ------------------------------------------------------------------

    def editor_state(self) -> EditorState:
        """Preferencias persistibles del editor (banda y resolución)."""
        return EditorState(
            band_id=self.band_id, grid_resolution_m=self.grid_resolution_m
        )

    def save_project(self, path: str | None = None) -> str:
        """Guarda el proyecto en JSON.

        Args:
            path: Ruta destino. Si es None se usa ``project_path``.

        Raises:
            ValueError: si el proyecto aún no tiene ruta (usar “Guardar como…”).
            ProjectFormatError: el proyecto no serializa/valida.
            OSError: fallo de escritura (el archivo previo queda intacto).
        """
        target = path if path is not None else self.project_path
        if target is None:
            raise ValueError("El proyecto no tiene ruta; usa “Guardar como…”.")
        written = _save_document(
            self.project, target, editor_state=self.editor_state()
        )
        self.mark_saved(str(written))
        return str(written)

    def save_project_as(self, path: str) -> str:
        """Guarda el proyecto en otra ruta y la asocia al documento."""
        return self.save_project(path)

    def open_project(self, path: str) -> None:
        """Carga un proyecto JSON y lo deja como documento activo.

        Si el archivo es inválido lanza ``ProjectFormatError`` y el
        proyecto actual queda intacto (sin estado parcial).
        """
        project, editor_state = _load_document(path)
        self._replace_document(project, editor_state, path=str(path))

    def new_project(self) -> None:
        """Crea un proyecto vacío (12 × 8 m) y limpia el documento activo."""
        self._replace_document(create_default_project(), EditorState(), path=None)

    def _replace_document(
        self, project: Project, editor_state: EditorState, path: str | None
    ) -> None:
        """Intercambia el documento y reinicia el estado transitorio.

        Solo se conserva del archivo lo que es ``Project`` + configuración
        persistible; la selección, el heatmap y las simulaciones se
        regeneran (decisión AB/AC, docs/decisions.md).
        """
        self.project = project
        self.project_path = path
        self.tool = Tool.SELECT
        self.selection = None
        self.wall_drag_start = None
        self.band_id = editor_state.band_id
        self.grid_resolution_m = editor_state.grid_resolution_m
        self.heatmap_ap_id = HEATMAP_ALL_APS
        self.heatmap_enabled = True
        self.last_simulation = None
        self.last_simulation_error = None
        self.last_heatmap = None
        self.last_heatmap_error = None
        self.invalidate_heatmap()
        self.dirty = False

    # ------------------------------------------------------------------
    # Piso / dimensiones
    # ------------------------------------------------------------------

    @property
    def floor(self) -> Floor:
        if not self.project.floors:
            self.project.floors.append(
                Floor(id="FLOOR-001", name="Planta baja", width_m=12.0, height_m=8.0)
            )
        return self.project.floors[0]

    @property
    def floor_width_m(self) -> float:
        return float(self.floor.width_m or 12.0)

    @property
    def floor_height_m(self) -> float:
        return float(self.floor.height_m or 8.0)

    def set_floor_dimensions(self, width_m: float, height_m: float) -> None:
        """Valida y aplica nuevas dimensiones del espacio (metros)."""
        self.floor.set_dimensions(width_m, height_m)
        self.invalidate_heatmap()
        self.mark_dirty()

    def set_grid_resolution(self, resolution_m: float) -> None:
        """Resolución del CoverageGrid en metros (> 0, con límite mínimo)."""
        resolution = float(resolution_m)
        if resolution <= 0:
            raise ValueError(f"Resolución debe ser > 0 (got {resolution}).")
        # La validación completa (mín. / máx. puntos) ocurre al construir el grid.
        probe = CoverageGrid(
            width_m=self.floor_width_m,
            height_m=self.floor_height_m,
            resolution_m=resolution,
        )
        if probe.point_count <= 0:
            raise ValueError("Grid vacío con esa resolución.")
        self.grid_resolution_m = resolution
        self.invalidate_heatmap()
        self.mark_dirty()

    def set_band(self, band_id: str) -> None:
        """Cambia la banda activa y invalida el heatmap (no reutiliza 2.4→5)."""
        self.project.get_band(band_id)  # valida existencia
        if band_id != self.band_id:
            self.band_id = band_id
            self.invalidate_heatmap()
            self.mark_dirty()

    def set_heatmap_enabled(self, enabled: bool) -> None:
        self.heatmap_enabled = bool(enabled)
        if enabled:
            self.invalidate_heatmap()

    def invalidate_heatmap(self) -> None:
        """Marca el heatmap como no válido (no sirve el resultado anterior)."""
        self.heatmap_dirty = True

    def build_coverage_grid(self) -> CoverageGrid:
        """Grid espacial del piso con la resolución actual (metros)."""
        return CoverageGrid(
            width_m=self.floor_width_m,
            height_m=self.floor_height_m,
            resolution_m=self.grid_resolution_m,
        )

    def set_heatmap_ap(self, ap_id: str | None) -> None:
        """Selector del heatmap: ``HEATMAP_ALL_APS`` o un id de AP concreto.

        Invalida el heatmap al cambiar el ámbito (combinado ↔ individual).
        """
        if ap_id is None or ap_id == HEATMAP_ALL_APS:
            new_id = HEATMAP_ALL_APS
        else:
            # Debe existir en el proyecto
            found = any(ap.id == ap_id for ap in self.project.access_points)
            if not found:
                raise KeyError(f"Access Point no encontrado: {ap_id}")
            new_id = ap_id
        if new_id != self.heatmap_ap_id:
            self.heatmap_ap_id = new_id
            self.invalidate_heatmap()

    def ap_choices_for_heatmap(self) -> list[str]:
        """Valores del selector de AP en la toolbar (todos + ids)."""
        choices = [HEATMAP_ALL_APS]
        choices += [ap.id for ap in self.project.access_points]
        return choices

    def resolve_ap_for_heatmap(self) -> AccessPoint | None:
        """AP seleccionado o el primero del proyecto (comportamiento Fase 3/4)."""
        ap = self.selected_ap()
        if ap is None and self.project.access_points:
            return self.project.access_points[0]
        return ap

    def resolve_aps_for_heatmap(self) -> list[AccessPoint]:
        """APs a evaluar en el heatmap actual.

        - ``HEATMAP_ALL_APS``: todos los APs del proyecto (orden estable).
        - id concreto: solo ese AP (F4 / vista individual).
        """
        aps = list(self.project.access_points)
        if self.heatmap_ap_id == HEATMAP_ALL_APS:
            return aps
        for ap in aps:
            if ap.id == self.heatmap_ap_id:
                return [ap]
        # AP del selector ya no existe → todos (o el primero si solo queda)
        return aps

    def run_heatmap(self, band_id: str | None = None) -> SimulationResult:
        """Simula el CoverageGrid con las paredes reales.

        Fase 5: si el selector es ``HEATMAP_ALL_APS`` y hay N > 1 APs,
        evalúa el **mismo grid** para cada AP con ``simulate_coverage``
        y fusiona con ``combine_results`` (mejor RSSI por punto; no es
        interferencia). Con 0 o 1 AP el comportamiento es el de Fase 4.

        Raises:
            ValueError: si no hay AP o el grid es inválido.
            MaterialAttenuationError: banda sin datos (p. ej. 6 GHz).
        """
        band_id = band_id or self.band_id
        self.band_id = band_id
        self.last_heatmap_error = None

        aps = self.resolve_aps_for_heatmap()
        if not aps:
            raise ValueError("Coloca al menos un Access Point para el heatmap.")

        band = self.project.get_band(band_id)
        grid = self.build_coverage_grid()
        points = grid.points()

        results: list[SimulationResult] = []
        for ap in aps:
            results.append(
                simulate_coverage(
                    project=self.project,
                    access_point=ap,
                    frequency_band=band,
                    sample_points=points,
                    walls=self.floor.walls,
                )
            )

        result = results[0] if len(results) == 1 else combine_results(results)
        self.last_heatmap = result
        self.heatmap_dirty = False
        return result

    def heatmap_stats_text(self) -> str:
        """Estadísticas del último heatmap (denominador: puntos del grid)."""
        if self.last_heatmap_error:
            return self.last_heatmap_error
        if self.last_heatmap is None:
            return "Sin heatmap todavía."
        from ui.coverage_renderer import stats_text

        band = self.project.get_band(self.last_heatmap.band_id)
        if self.heatmap_ap_id == HEATMAP_ALL_APS:
            n = len(self.project.access_points)
            ap_label = f"Todos los AP ({n})" if n != 1 else "Todos los AP (1)"
        else:
            ap_label = self.heatmap_ap_id
        header = (
            f"AP: {ap_label}\n"
            f"Banda: {band.name}\n"
            f"Resolución: {self.grid_resolution_m:g} m\n\n"
        )
        return header + stats_text(self.last_heatmap)

    def client_rssi_lines(self) -> list[str]:
        """RSSI/SOM en posiciones de clientes (si hay heatmap y clientes)."""
        if not self.last_heatmap or not self.project.clients:
            return []
        lines: list[str] = []
        for client in self.project.clients:
            ev = self.last_heatmap.best_at(client.position)
            if ev is None:
                # Buscar por proximidad mínima (redondeo de grid)
                best = None
                best_d = float("inf")
                for e in self.last_heatmap.evaluations:
                    d = e.point.distance_to(client.position)
                    if d < best_d:
                        best_d = d
                        best = e
                ev = best
            if ev is None:
                continue
            lines.append(
                f"{client.id}: RSSI {ev.rx_power_dbm:.1f} dBm | "
                f"SOM {ev.som_db:.1f} | {ev.quality.value}"
            )
        return lines

    # ------------------------------------------------------------------
    # Selección / herramienta
    # ------------------------------------------------------------------

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self.wall_drag_start = None
        if tool != Tool.SELECT:
            self.selection = None

    def select(self, kind: SelectionKind | None, entity_id: str | None) -> None:
        if kind is None or entity_id is None:
            self.selection = None
        else:
            self.selection = Selection(kind=kind, entity_id=entity_id)

    def selected_wall(self) -> Wall | None:
        if self.selection and self.selection.kind == SelectionKind.WALL:
            for wall in self.floor.walls:
                if wall.id == self.selection.entity_id:
                    return wall
        return None

    def selected_ap(self) -> AccessPoint | None:
        if self.selection and self.selection.kind == SelectionKind.AP:
            for ap in self.project.access_points:
                if ap.id == self.selection.entity_id:
                    return ap
        return None

    def selected_client(self) -> ClientDevice | None:
        if self.selection and self.selection.kind == SelectionKind.CLIENT:
            for client in self.project.clients:
                if client.id == self.selection.entity_id:
                    return client
        return None

    # ------------------------------------------------------------------
    # Crear entidades
    # ------------------------------------------------------------------

    def _all_ids(self) -> list[str]:
        ids = [w.id for w in self.floor.walls]
        ids += [ap.id for ap in self.project.access_points]
        ids += [c.id for c in self.project.clients]
        ids += [f.id for f in self.project.floors]
        return ids

    def add_wall(self, start: Point2D, end: Point2D) -> Wall:
        """Crea una pared en metros. Validaciones de geometría mínima."""
        if start.distance_to(end) < 1e-6:
            raise ValueError("La pared necesita dos puntos distintos.")
        wall_id = next_entity_id(self._all_ids(), "WALL")
        wall = Wall(
            id=wall_id,
            segment=Segment2D(start, end),
            material=self.project.get_material("drywall"),
        )
        self.floor.walls.append(wall)
        self.select(SelectionKind.WALL, wall_id)
        self.invalidate_heatmap()
        self.mark_dirty()
        return wall

    def add_access_point(self, position: Point2D) -> AccessPoint:
        """Crea un AP en metros con la radio por defecto del proyecto."""
        position = self._clamp_to_floor(position)
        ap_id = next_entity_id(self._all_ids(), "AP")
        ap = AccessPoint(id=ap_id, position=position, radio=self.project.radio)
        self.project.access_points.append(ap)
        self.select(SelectionKind.AP, ap_id)
        self.invalidate_heatmap()
        self.mark_dirty()
        return ap

    def add_client(self, position: Point2D) -> ClientDevice:
        """Crea un dispositivo cliente en metros."""
        position = self._clamp_to_floor(position)
        client_id = next_entity_id(self._all_ids(), "CLIENT")
        client = ClientDevice(id=client_id, position=position)
        self.project.clients.append(client)
        self.select(SelectionKind.CLIENT, client_id)
        self.mark_dirty()
        return client

    def _clamp_to_floor(self, position: Point2D) -> Point2D:
        """Mantiene el punto dentro del rectángulo del piso."""
        x = min(max(position.x, 0.0), self.floor_width_m)
        y = min(max(position.y, 0.0), self.floor_height_m)
        return Point2D(x, y)

    # ------------------------------------------------------------------
    # Mover / editar
    # ------------------------------------------------------------------

    def move_ap(self, ap_id: str, position: Point2D) -> None:
        """Actualiza la posición del AP en METROS (nunca píxeles)."""
        position = self._clamp_to_floor(position)
        for index, ap in enumerate(self.project.access_points):
            if ap.id == ap_id:
                self.project.access_points[index] = replace(ap, position=position)
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Access Point no encontrado: {ap_id}")

    def move_client(self, client_id: str, position: Point2D) -> None:
        """Actualiza la posición del cliente en METROS."""
        position = self._clamp_to_floor(position)
        for index, client in enumerate(self.project.clients):
            if client.id == client_id:
                self.project.clients[index] = replace(client, position=position)
                self.mark_dirty()
                return
        raise KeyError(f"Cliente no encontrado: {client_id}")

    def set_wall_material(self, wall_id: str, material_id: str) -> None:
        """Cambia el material de una pared (catálogo del Project)."""
        material: Material = self.project.get_material(material_id)
        for index, wall in enumerate(self.floor.walls):
            if wall.id == wall_id:
                self.floor.walls[index] = replace(wall, material=material)
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Pared no encontrada: {wall_id}")

    def set_wall_thickness(self, wall_id: str, thickness_m: float) -> None:
        """Cambia el espesor de una pared. Debe ser > 0."""
        if thickness_m <= 0:
            raise ValueError(f"Espesor debe ser > 0 m (got {thickness_m}).")
        if thickness_m > 10:
            raise ValueError(
                f"Espesor no razonable: {thickness_m} m (máximo 10 m)."
            )
        for index, wall in enumerate(self.floor.walls):
            if wall.id == wall_id:
                self.floor.walls[index] = replace(wall, thickness_m=float(thickness_m))
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Pared no encontrada: {wall_id}")

    # ------------------------------------------------------------------
    # Eliminar
    # ------------------------------------------------------------------

    def delete_selection(self) -> bool:
        """Elimina el elemento seleccionado del modelo. True si había uno."""
        if self.selection is None:
            return False
        kind, entity_id = self.selection.kind, self.selection.entity_id

        if kind == SelectionKind.WALL:
            for index, wall in enumerate(self.floor.walls):
                if wall.id == entity_id:
                    del self.floor.walls[index]
                    self.selection = None
                    self.invalidate_heatmap()
                    self.mark_dirty()
                    return True
        elif kind == SelectionKind.AP:
            for index, ap in enumerate(self.project.access_points):
                if ap.id == entity_id:
                    del self.project.access_points[index]
                    self.selection = None
                    # Si el heatmap apuntaba a ese AP, volver a combinado.
                    if self.heatmap_ap_id == entity_id:
                        self.heatmap_ap_id = HEATMAP_ALL_APS
                    self.invalidate_heatmap()
                    self.mark_dirty()
                    return True
        elif kind == SelectionKind.CLIENT:
            for index, client in enumerate(self.project.clients):
                if client.id == entity_id:
                    del self.project.clients[index]
                    self.selection = None
                    self.invalidate_heatmap()
                    self.mark_dirty()
                    return True
        self.selection = None
        return False

    # ------------------------------------------------------------------
    # Simulación (invoca engine; sin fórmulas aquí)
    # ------------------------------------------------------------------

    def sample_points_for_simulation(self) -> list[Point2D]:
        """Puntos de muestreo: clientes si existen, si no una malla 3×3."""
        if self.project.clients:
            return [c.position for c in self.project.clients]
        w, h = self.floor_width_m, self.floor_height_m
        points: list[Point2D] = []
        for fx in (0.2, 0.5, 0.8):
            for fy in (0.2, 0.5, 0.8):
                points.append(Point2D(w * fx, h * fy))
        return points

    def run_simulation(self, band_id: str | None = None) -> SimulationResult:
        """Invoca simulate_coverage con las paredes reales del piso.

        La UI solo muestra un resumen de texto (sin heatmap en Fase 3).

        Raises:
            ValueError: si no hay AP.
            MaterialAttenuationError: banda sin datos (p. ej. 6 GHz).
        """
        band_id = band_id or self.band_id
        self.band_id = band_id
        self.last_simulation_error = None

        ap = self.selected_ap()
        if ap is None and self.project.access_points:
            ap = self.project.access_points[0]
        if ap is None:
            raise ValueError("Coloca al menos un Access Point para simular.")

        band = self.project.get_band(band_id)
        points = self.sample_points_for_simulation()
        result = simulate_coverage(
            project=self.project,
            access_point=ap,
            frequency_band=band,
            sample_points=points,
            walls=self.floor.walls,
        )
        self.last_simulation = result
        return result

    def simulation_summary_text(self) -> str:
        """Resumen de texto del último resultado (o mensaje de error)."""
        if self.last_simulation_error:
            return self.last_simulation_error
        result = self.last_simulation
        if result is None:
            return "Sin simulación todavía."

        evaluations = result.evaluations
        if not evaluations:
            return "Sin puntos simulados."

        rx_values = [e.rx_power_dbm for e in evaluations]
        ap_id = evaluations[0].access_point_id
        band = self.project.get_band(result.band_id)
        wall_count = len(self.floor.walls)
        return (
            f"AP: {ap_id}\n"
            f"Banda: {band.name}\n"
            f"Paredes: {wall_count}\n"
            f"Puntos simulados: {len(evaluations)}\n"
            f"RSSI mínimo: {min(rx_values):.2f} dBm\n"
            f"RSSI máximo: {max(rx_values):.2f} dBm"
        )
