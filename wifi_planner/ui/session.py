"""Estado del editor: operaciones puras sobre Project (sin Tkinter).

Esta capa es testeable sin abrir la ventana. La UI (Canvas/panels)
la invoca y luego vuelve a dibujar desde el Project (fuente de verdad).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable

from core.access_point import AccessPoint
from core.client import ClientDevice
from core.geometry import Point2D, Rect, Segment2D
from core.material import Material
from core.project import Project
from core.radio import wifi_generation
from core.result import SimulationResult
from core.space import MIN_SPACE_SIZE_M, Floor, Space
from core.wall import (
    DEFAULT_OPENING_LENGTH_M,
    MIN_OPENING_LENGTH_M,
    OPENING_KINDS,
    Opening,
    Wall,
)
from engine.classifier import rf_diagnostic
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
    SPACE = "space"


class HeatmapMetric(str, Enum):
    """Métrica visual del heatmap (Fase 7): RSSI o SNR.

    Es una vista, no configuración del proyecto: no se persiste ni
    marca ``dirty`` (decisión BA).
    """

    RSSI = "rssi"
    SNR = "snr"


def _standard_label(project: Project, frequency_mhz: float) -> str:
    """Etiqueta del estándar del proyecto para una banda (Fase 7).

    Ej.: ``802.11ax (Wi-Fi 6)`` o ``802.11ax (Wi-Fi 6E)`` a 6 GHz.
    """
    standard = project.radio.wifi_standard
    return f"{standard} ({wifi_generation(standard, frequency_mhz)})"


class SelectionKind(str, Enum):
    WALL = "wall"
    AP = "ap"
    CLIENT = "client"
    SPACE = "space"
    OPENING = "opening"


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
        # Fase 8: punto de inicio mientras se dibuja un espacio (metros).
        self.space_drag_start: Point2D | None = None
        self.band_id: str = "band_2_4"
        self.last_simulation: SimulationResult | None = None
        self.last_simulation_error: str | None = None
        # Fase 4: heatmap espacial
        self.grid_resolution_m: float = 0.5
        self.heatmap_enabled: bool = True
        # Fase 5: HEATMAP_ALL_APS (combinado) o id de un AP concreto.
        self.heatmap_ap_id: str = HEATMAP_ALL_APS
        # Fase 7: métrica visual del heatmap (vista; no persistible).
        self.heatmap_metric: str = HeatmapMetric.RSSI.value
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
        self.space_drag_start = None
        self.band_id = editor_state.band_id
        self.grid_resolution_m = editor_state.grid_resolution_m
        self.heatmap_ap_id = HEATMAP_ALL_APS
        self.heatmap_metric = HeatmapMetric.RSSI.value
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
        """Valida y aplica nuevas dimensiones del espacio (metros).

        Además de los límites del piso, comprueba que la resolución
        actual siga produciendo un grid usable: el invariante
        «dimensiones + resolución ⇒ grid válido» se mantiene en ambos
        cambios de entrada (dimensiones y resolución), para que el
        proyecto siempre sea simulable y guardable.
        """
        floor = self.floor
        previous = (floor.width_m, floor.height_m)
        floor.set_dimensions(width_m, height_m)  # valida > 0 y <= 10000 m
        try:
            probe = CoverageGrid(
                width_m=float(floor.width_m),
                height_m=float(floor.height_m),
                resolution_m=self.grid_resolution_m,
            )
            if probe.point_count <= 0:
                raise ValueError("Grid vacío con esas dimensiones/resolución.")
        except ValueError as exc:
            floor.width_m, floor.height_m = previous
            raise ValueError(
                f"Dimensiones incompatibles con la resolución "
                f"{self.grid_resolution_m:g} m: {exc}"
            ) from exc
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

    def apply_rf_settings(
        self,
        *,
        noise_floor_dbm: float,
        snr_target_db: float,
        rssi_target_dbm: float,
        wifi_standard: str,
        channel_width_mhz: int,
    ) -> None:
        """Configuración RF global (Fase 7): ruido, umbrales, estándar, ancho.

        Atómico: radio y thresholds se construyen con ``replace`` ANTES de
        tocar el proyecto; si la validación falla (``ValueError``), nada
        cambia. Después se sincroniza la radio de los APs existentes
        (F7 sin configuración por AP) y se invalida el heatmap.
        """
        radio = replace(
            self.project.radio,
            noise_floor_dbm=float(noise_floor_dbm),
            channel_width_mhz=int(channel_width_mhz),
            wifi_standard=str(wifi_standard),
        )
        thresholds = replace(
            self.project.thresholds,
            rssi_target_dbm=float(rssi_target_dbm),
            snr_target_db=float(snr_target_db),
        )
        # Hasta aquí solo se validó: ahora la mutación es segura.
        self.project.radio = radio
        self.project.thresholds = thresholds
        for ap in self.project.access_points:
            ap.radio = replace(
                ap.radio,
                noise_floor_dbm=radio.noise_floor_dbm,
                channel_width_mhz=radio.channel_width_mhz,
                wifi_standard=radio.wifi_standard,
            )
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

    def set_heatmap_metric(self, metric: str) -> None:
        """Métrica visual del heatmap: ``rssi`` o ``snr`` (Fase 7).

        Es una vista: invalida el heatmap (los píxeles a pintar cambian)
        pero NO marca ``dirty`` ni se persiste (decisión BA).
        """
        if metric not in {m.value for m in HeatmapMetric}:
            raise ValueError(
                f"Métrica no soportada: {metric!r} (usa 'rssi' o 'snr')."
            )
        if metric != self.heatmap_metric:
            self.heatmap_metric = metric
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
        # Valida ANTES de mutar: una banda desconocida no debe dejar la
        # sesión con band_id inválido, y un cambio real de banda es
        # configuración persistible ⇒ dirty (decisión AN, F6.1).
        band = self.project.get_band(band_id)
        if band_id != self.band_id:
            self.band_id = band_id
            self.mark_dirty()
        self.last_heatmap_error = None

        aps = self.resolve_aps_for_heatmap()
        if not aps:
            raise ValueError("Coloca al menos un Access Point para el heatmap.")

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
                    openings=self.floor.openings,
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
            f"Resolución: {self.grid_resolution_m:g} m\n"
            f"Estándar: {_standard_label(self.project, band.frequency_mhz)}\n"
        )
        if self.heatmap_metric == HeatmapMetric.SNR.value:
            header += (
                f"Métrica: SNR (dB)\n"
                f"SNR objetivo: {self.project.thresholds.snr_target_db:g} dB\n"
            )
        header += "\n"
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
            diagnostic = rf_diagnostic(
                ev.rx_power_dbm, ev.snr_db, self.project.thresholds
            )
            lines.append(
                f"{client.id}: AP {ev.access_point_id} | "
                f"{ev.distance_m:.2f} m | "
                f"RSSI {ev.rx_power_dbm:.1f} dBm | "
                f"SOM {ev.som_db:.1f} | "
                f"SNR {ev.snr_db:.1f} dB | {ev.quality.value} | "
                f"{diagnostic}"
            )
        return lines

    # ------------------------------------------------------------------
    # Selección / herramienta
    # ------------------------------------------------------------------

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self.wall_drag_start = None
        self.space_drag_start = None
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

    def selected_space(self) -> Space | None:
        if self.selection and self.selection.kind == SelectionKind.SPACE:
            for space in self.floor.spaces:
                if space.id == self.selection.entity_id:
                    return space
        return None

    def selected_opening(self) -> Opening | None:
        if self.selection and self.selection.kind == SelectionKind.OPENING:
            for opening in self.floor.openings:
                if opening.id == self.selection.entity_id:
                    return opening
        return None

    def find_wall(self, wall_id: str) -> Wall | None:
        """Pared por id (o None). Útil para el panel de propiedades."""
        for wall in self.floor.walls:
            if wall.id == wall_id:
                return wall
        return None

    def openings_for_wall(self, wall_id: str) -> list[Opening]:
        """Openings de una pared en orden canónico ``(start, id)``."""
        from core.wall import group_openings_by_wall

        return list(group_openings_by_wall(self.floor.openings).get(wall_id, ()))

    # ------------------------------------------------------------------
    # Crear entidades
    # ------------------------------------------------------------------

    def _all_ids(self) -> list[str]:
        ids = [w.id for w in self.floor.walls]
        ids += [ap.id for ap in self.project.access_points]
        ids += [c.id for c in self.project.clients]
        ids += [f.id for f in self.project.floors]
        ids += [s.id for s in self.floor.spaces]
        ids += [o.id for o in self.floor.openings]
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

    # ------------------------------------------------------------------
    # Espacios (Fase 8): geometría + organización, sin RF (decisión BH)
    # ------------------------------------------------------------------

    def add_space(self, corner_a: Point2D, corner_b: Point2D) -> Space:
        """Crea un espacio (rect alineado a ejes) entre dos esquinas.

        Ambas esquinas se recortan al rectángulo del piso. El tamaño
        mínimo por lado es ``MIN_SPACE_SIZE_M``. No invalida el heatmap:
        los espacios no participan en la propagación (decisión BH).

        Raises:
            ValueError: si el rectángulo resultante es demasiado pequeño.
        """
        width = self.floor_width_m
        height = self.floor_height_m

        def _clamp(point: Point2D) -> tuple[float, float]:
            return (
                min(max(point.x, 0.0), width),
                min(max(point.y, 0.0), height),
            )

        x1, y1 = _clamp(corner_a)
        x2, y2 = _clamp(corner_b)
        rect = Rect(
            x=min(x1, x2),
            y=min(y1, y2),
            width=abs(x2 - x1),
            height=abs(y2 - y1),
        )
        if rect.width < MIN_SPACE_SIZE_M or rect.height < MIN_SPACE_SIZE_M:
            raise ValueError(
                f"Espacio demasiado pequeño: mínimo {MIN_SPACE_SIZE_M:g} m "
                f"por lado (got {rect.width:g} × {rect.height:g} m)."
            )
        space_id = next_entity_id(self._all_ids(), "SPACE")
        number = space_id.rsplit("-", 1)[-1]
        space = Space(id=space_id, name=f"Espacio {number}", rect=rect)
        self.floor.spaces.append(space)
        self.select(SelectionKind.SPACE, space_id)
        self.mark_dirty()
        return space

    def set_space_properties(
        self, space_id: str, name: str, function: str = ""
    ) -> None:
        """Actualiza nombre y función zonal de un espacio (strings)."""
        name = str(name)
        function = str(function)
        if not name.strip():
            raise ValueError("El nombre del espacio no puede estar vacío.")
        if len(name) > 200 or len(function) > 200:
            raise ValueError("Nombre o función demasiado largo (máx. 200).")
        for index, space in enumerate(self.floor.spaces):
            if space.id == space_id:
                self.floor.spaces[index] = replace(
                    space, name=name, function=function
                )
                self.mark_dirty()
                return
        raise KeyError(f"Espacio no encontrado: {space_id}")

    # ------------------------------------------------------------------
    # Aperturas (Fase 8): huecos en paredes (decisión BG: reemplazo)
    # ------------------------------------------------------------------

    def add_opening(
        self, wall_id: str, kind: str, center_offset_m: float | None = None
    ) -> Opening:
        """Crea una apertura centrada (o en ``center_offset_m``) en una pared.

        La longitud por defecto es la del tipo (``DEFAULT_OPENING_LENGTH_M``)
        y se recorta para caber en la pared. Invalida el heatmap (los
        openings sí afectan a la propagación) y marca ``dirty``.

        Raises:
            KeyError: si la pared no existe.
            ValueError: si el tipo no es válido o la pared es demasiado
                corta para cualquier apertura.
        """
        wall = self.find_wall(wall_id)
        if wall is None:
            raise KeyError(f"Pared no encontrada: {wall_id}")
        if kind not in OPENING_KINDS:
            raise ValueError(
                f"Tipo de apertura no soportado: {kind!r} "
                f"(permitidos: {', '.join(OPENING_KINDS)})."
            )
        wall_length = wall.segment.length
        if wall_length < MIN_OPENING_LENGTH_M:
            raise ValueError(
                "La pared es demasiado corta para una apertura "
                f"({wall_length:g} m)."
            )
        length = min(DEFAULT_OPENING_LENGTH_M[kind], wall_length)
        center = wall_length / 2.0 if center_offset_m is None else float(center_offset_m)
        start = min(max(center - length / 2.0, 0.0), wall_length - length)
        end = start + length

        opening_id = next_entity_id(self._all_ids(), "OPEN")
        opening = Opening(
            id=opening_id,
            wall_id=wall_id,
            start_offset_m=start,
            end_offset_m=end,
            kind=kind,
        )
        self.floor.openings.append(opening)
        self.select(SelectionKind.OPENING, opening_id)
        self.invalidate_heatmap()
        self.mark_dirty()
        return opening

    def set_opening_offsets(
        self, opening_id: str, start_offset_m: float, end_offset_m: float
    ) -> None:
        """Mueve/redimensiona una apertura por offsets métricos sobre la pared.

        Los offsets se recortan al intervalo de la pared y después se
        exige la longitud mínima: una edición nunca puede producir un
        opening inválido o fuera de la pared.

        Raises:
            KeyError: si la apertura o su pared no existen.
            ValueError: si los valores no son finitos o la longitud
                resultante es menor que ``MIN_OPENING_LENGTH_M``.
        """
        try:
            start = float(str(start_offset_m).replace(",", "."))
            end = float(str(end_offset_m).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Offsets inválidos: {exc}") from exc
        if not (math.isfinite(start) and math.isfinite(end)):
            raise ValueError("Los offsets deben ser finitos.")

        opening = None
        for item in self.floor.openings:
            if item.id == opening_id:
                opening = item
                break
        if opening is None:
            raise KeyError(f"Apertura no encontrada: {opening_id}")
        wall = self.find_wall(opening.wall_id)
        if wall is None:
            raise KeyError(f"Pared no encontrada: {opening.wall_id}")

        wall_length = wall.segment.length
        start = min(max(start, 0.0), wall_length)
        end = min(max(end, 0.0), wall_length)
        if end - start < MIN_OPENING_LENGTH_M:
            raise ValueError(
                f"La apertura debe medir ≥ {MIN_OPENING_LENGTH_M:g} m "
                f"(pared de {wall_length:g} m; got {end - start:g} m)."
            )
        for index, item in enumerate(self.floor.openings):
            if item.id == opening_id:
                self.floor.openings[index] = replace(
                    item, start_offset_m=start, end_offset_m=end
                )
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Apertura no encontrada: {opening_id}")

    def set_opening_kind(self, opening_id: str, kind: str) -> None:
        """Cambia el tipo visual (door/window/pass_through).

        El tipo NO altera la pérdida (decisión BG): marca ``dirty`` pero
        no invalida el heatmap.
        """
        if kind not in OPENING_KINDS:
            raise ValueError(
                f"Tipo de apertura no soportado: {kind!r} "
                f"(permitidos: {', '.join(OPENING_KINDS)})."
            )
        for index, item in enumerate(self.floor.openings):
            if item.id == opening_id:
                self.floor.openings[index] = replace(item, kind=kind)
                self.mark_dirty()
                return
        raise KeyError(f"Apertura no encontrada: {opening_id}")

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
                    # Fase 8: al borrar la pared, sus openings se caen con ella
                    # (nada puede referenciar una pared inexistente).
                    remaining = [
                        op for op in self.floor.openings if op.wall_id != entity_id
                    ]
                    if len(remaining) != len(self.floor.openings):
                        self.floor.openings[:] = remaining
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
        elif kind == SelectionKind.SPACE:
            # Los espacios no son RF: dirty sí, heatmap no (decisión BH).
            for index, space in enumerate(self.floor.spaces):
                if space.id == entity_id:
                    del self.floor.spaces[index]
                    self.selection = None
                    self.mark_dirty()
                    return True
        elif kind == SelectionKind.OPENING:
            for index, opening in enumerate(self.floor.openings):
                if opening.id == entity_id:
                    del self.floor.openings[index]
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
        # Misma regla que run_heatmap: validar antes de mutar + dirty
        # si la banda persistible cambia (decisión AN, F6.1).
        band = self.project.get_band(band_id)
        if band_id != self.band_id:
            self.band_id = band_id
            self.mark_dirty()
        self.last_simulation_error = None

        ap = self.selected_ap()
        if ap is None and self.project.access_points:
            ap = self.project.access_points[0]
        if ap is None:
            raise ValueError("Coloca al menos un Access Point para simular.")

        points = self.sample_points_for_simulation()
        result = simulate_coverage(
            project=self.project,
            access_point=ap,
            frequency_band=band,
            sample_points=points,
            walls=self.floor.walls,
            openings=self.floor.openings,
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
        snr_values = [e.snr_db for e in evaluations]
        ap_id = evaluations[0].access_point_id
        band = self.project.get_band(result.band_id)
        wall_count = len(self.floor.walls)
        return (
            f"AP: {ap_id}\n"
            f"Banda: {band.name}\n"
            f"Paredes: {wall_count}\n"
            f"Puntos simulados: {len(evaluations)}\n"
            f"RSSI mínimo: {min(rx_values):.2f} dBm\n"
            f"RSSI máximo: {max(rx_values):.2f} dBm\n"
            f"SNR mínimo: {min(snr_values):.2f} dB\n"
            f"SNR máximo: {max(snr_values):.2f} dB"
        )
