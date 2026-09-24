"""Repositorio JSON de proyectos: Project ↔ JSON, con validación estricta.

Formato (``schema_version = 1``)::

    {
      "schema_version": 1,
      "project": {
        "name": "...",
        "units": "m",
        "bands": [...],
        "materials": [...],
        "radio": {...},
        "thresholds": {...},
        "floors": [{"id", "name", "level", "width_m", "height_m",
                    "elevation_m", "metadata", "walls": [...]}],
        "access_points": [...],
        "clients": [...],
        "metadata": {...}
      },
      "editor": {"band_id": "band_2_4", "grid_resolution_m": 0.5}
    }

Decisiones de formato (docs/decisions.md, Fase 6):

- Coordenadas SIEMPRE en metros (``x_m`` / ``y_m``); los píxeles no
  existen aquí (la conversión es responsabilidad del ``Viewport``).
- Las paredes referencian el catálogo de materiales por ``material_id``
  (una sola tabla: ``project.materials``).
- No se persisten resultados de simulación, heatmaps ni estado visual:
  se regeneran al abrir.
- ``schema_version`` incompatible => ``ProjectFormatError`` controlado
  (nunca carga parcial ni sobrescribe el proyecto en memoria).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.access_point import AccessPoint
from core.band import FrequencyBand
from core.client import ClientDevice
from core.geometry import Point2D, Segment2D
from core.material import Material
from core.project import CoverageThresholds, Project
from core.radio import RadioConfiguration
from core.space import Floor
from core.wall import Wall

# Versión del formato. Un incremento implica que hay que migrar/validar.
SCHEMA_VERSION = 1

# Resolución de grid por defecto (coincide con EditorSession).
DEFAULT_GRID_RESOLUTION_M = 0.5

# Límites de seguridad: el JSON es entrada no confiable.
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_NAME_LEN = 200
MAX_ID_LEN = 64
MAX_COORD_M = 100_000.0
MAX_DIMENSION_M = 10_000.0
MAX_THICKNESS_M = 10.0
MAX_RESOLUTION_M = 1_000.0
MAX_BANDS = 64
MAX_MATERIALS = 512
MAX_FLOORS = 64
MAX_WALLS = 50_000
MAX_APS = 10_000
MAX_CLIENTS = 10_000
MAX_ATTENUATION_DB = 200.0
MAX_METADATA_DEPTH = 10
MAX_METADATA_ITEMS = 10_000


class ProjectFormatError(Exception):
    """Archivo de proyecto ilegible, inválido o con versión incompatible."""


@dataclass(frozen=True)
class EditorState:
    """Preferencias del editor que SÍ se persisten (configuración).

    No es estado visual (selección, heatmap visible, herramienta): son
    parámetros que afectan a cómo se rehace la simulación al abrir.
    """

    band_id: str = "band_2_4"
    grid_resolution_m: float = DEFAULT_GRID_RESOLUTION_M


# ---------------------------------------------------------------------------
# Validadores primitivos
# ---------------------------------------------------------------------------


def _fail(message: str) -> None:
    raise ProjectFormatError(message)


def _require_dict(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{path}: se espera un objeto JSON.")
    return value


def _require_list(value: Any, path: str, max_items: int) -> list:
    if not isinstance(value, list):
        _fail(f"{path}: se espera una lista JSON.")
    if len(value) > max_items:
        _fail(f"{path}: demasiados elementos ({len(value)} > {max_items}).")
    return value


def _require_str(
    value: Any, path: str, *, max_len: int = MAX_NAME_LEN, allow_empty: bool = True
) -> str:
    if not isinstance(value, str):
        _fail(f"{path}: se espera una cadena de texto.")
    if len(value) > max_len:
        _fail(f"{path}: demasiado largo ({len(value)} > {max_len} caracteres).")
    if not allow_empty and not value.strip():
        _fail(f"{path}: no puede estar vacío.")
    return value


def _require_id(value: Any, path: str) -> str:
    return _require_str(value, path, max_len=MAX_ID_LEN, allow_empty=False)


def _require_number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if value is None:
        _fail(f"{path}: falta el campo obligatorio.")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{path}: se espera un número.")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{path}: número no finito ({value!r}).")
    if minimum is not None and number < minimum:
        _fail(f"{path}: debe ser >= {minimum} (got {number}).")
    if maximum is not None and number > maximum:
        _fail(f"{path}: debe ser <= {maximum} (got {number}).")
    return number


def _require_int(
    value: Any,
    path: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{path}: se espera un entero.")
    if minimum is not None and value < minimum:
        _fail(f"{path}: debe ser >= {minimum} (got {value}).")
    if maximum is not None and value > maximum:
        _fail(f"{path}: debe ser <= {maximum} (got {value}).")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{path}: se espera true/false.")
    return value


def _validate_metadata(value: Any, path: str, depth: int = 0) -> dict:
    """metadata: dict JSON con claves str y valores finitos (recursivo)."""
    if depth > MAX_METADATA_DEPTH:
        _fail(f"{path}: anidación demasiado profunda.")
    if value is None:
        return {}
    data = _require_dict(value, path)
    _walk_metadata(data, path, depth)
    return data


def _walk_metadata(value: Any, path: str, depth: int) -> None:
    if depth > MAX_METADATA_DEPTH:
        _fail(f"{path}: anidación demasiado profunda.")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{path}: número no finito en metadata.")
        return
    if isinstance(value, list):
        if len(value) > MAX_METADATA_ITEMS:
            _fail(f"{path}: lista de metadata demasiado grande.")
        for index, item in enumerate(value):
            _walk_metadata(item, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_METADATA_ITEMS:
            _fail(f"{path}: objeto de metadata demasiado grande.")
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{path}: las claves de metadata deben ser texto.")
            _walk_metadata(item, f"{path}.{key}", depth + 1)
        return
    _fail(f"{path}: valor de metadata no soportado ({type(value).__name__}).")


def _point_to_dict(point: Point2D) -> dict[str, float]:
    return {"x_m": point.x, "y_m": point.y}


def _point_from_dict(value: Any, path: str) -> Point2D:
    data = _require_dict(value, path)
    x = _require_number(data.get("x_m"), f"{path}.x_m", minimum=-MAX_COORD_M, maximum=MAX_COORD_M)
    y = _require_number(data.get("y_m"), f"{path}.y_m", minimum=-MAX_COORD_M, maximum=MAX_COORD_M)
    return Point2D(x, y)


def _require_unique(ids: list[str], path: str) -> None:
    seen: set[str] = set()
    for entity_id in ids:
        if entity_id in seen:
            _fail(f"{path}: id duplicado {entity_id!r}.")
        seen.add(entity_id)


# ---------------------------------------------------------------------------
# Serialización (Project → dict)
# ---------------------------------------------------------------------------


def _radio_to_dict(radio: RadioConfiguration) -> dict[str, float]:
    return {
        "p_tx_dbm": radio.p_tx_dbm,
        "g_tx_dbi": radio.g_tx_dbi,
        "l_tx_db": radio.l_tx_db,
        "g_rx_dbi": radio.g_rx_dbi,
        "l_rx_db": radio.l_rx_db,
        "sensitivity_dbm": radio.sensitivity_dbm,
        "fade_margin_db": radio.fade_margin_db,
    }


def _thresholds_to_dict(thresholds: CoverageThresholds) -> dict[str, float]:
    return {
        "rssi_target_dbm": thresholds.rssi_target_dbm,
        "som_aprobado_min_db": thresholds.som_aprobado_min_db,
        "som_riesgo_min_db": thresholds.som_riesgo_min_db,
        "excellent_min_dbm": thresholds.excellent_min_dbm,
        "good_min_dbm": thresholds.good_min_dbm,
        "regular_min_dbm": thresholds.regular_min_dbm,
        "weak_min_dbm": thresholds.weak_min_dbm,
    }


def _wall_to_dict(wall: Wall) -> dict[str, Any]:
    return {
        "id": wall.id,
        "start": _point_to_dict(wall.segment.start),
        "end": _point_to_dict(wall.segment.end),
        "material_id": wall.material.id,
        "thickness_m": wall.thickness_m,
        "blocks_signal": wall.blocks_signal,
    }


def _floor_to_dict(floor: Floor) -> dict[str, Any]:
    return {
        "id": floor.id,
        "name": floor.name,
        "level": floor.level,
        "width_m": floor.width_m,
        "height_m": floor.height_m,
        "elevation_m": floor.elevation_m,
        "metadata": dict(floor.metadata),
        "walls": [_wall_to_dict(wall) for wall in floor.walls],
    }


def _ap_to_dict(ap: AccessPoint) -> dict[str, Any]:
    return {
        "id": ap.id,
        "position": _point_to_dict(ap.position),
        "name": ap.name,
        "enabled": ap.enabled,
        "channel": ap.channel,
        "radio": _radio_to_dict(ap.radio),
        "metadata": dict(ap.metadata),
    }


def _client_to_dict(client: ClientDevice) -> dict[str, Any]:
    return {
        "id": client.id,
        "position": _point_to_dict(client.position),
        "name": client.name,
        "sensitivity_dbm": client.sensitivity_dbm,
        "metadata": dict(client.metadata),
    }


def project_to_dict(project: Project) -> dict[str, Any]:
    """Convierte un ``Project`` en datos JSON-compatibles (determinista)."""
    return {
        "name": project.name,
        "units": project.units,
        "bands": [
            {"id": band.id, "name": band.name, "frequency_mhz": band.frequency_mhz}
            for band in project.bands
        ],
        "materials": [
            {
                "id": material.id,
                "name": material.name,
                "description": material.description,
                "thickness_default_m": material.thickness_default_m,
                "attenuation_db": dict(material.attenuation_db),
            }
            for material in project.materials
        ],
        "radio": _radio_to_dict(project.radio),
        "thresholds": _thresholds_to_dict(project.thresholds),
        "floors": [_floor_to_dict(floor) for floor in project.floors],
        "access_points": [_ap_to_dict(ap) for ap in project.access_points],
        "clients": [_client_to_dict(client) for client in project.clients],
        "metadata": dict(project.metadata),
    }


def document_to_dict(
    project: Project, editor_state: EditorState | None = None
) -> dict[str, Any]:
    """Documento completo: ``schema_version`` + proyecto + estado de editor."""
    state = editor_state or EditorState(band_id=_default_band_id(project))
    return {
        "schema_version": SCHEMA_VERSION,
        "project": project_to_dict(project),
        "editor": {
            "band_id": state.band_id,
            "grid_resolution_m": state.grid_resolution_m,
        },
    }


def _default_band_id(project: Project) -> str:
    """Banda por defecto para un documento sin sección ``editor``."""
    if any(band.id == "band_2_4" for band in project.bands):
        return "band_2_4"
    if project.bands:
        return project.bands[0].id
    return "band_2_4"


# ---------------------------------------------------------------------------
# Deserialización (dict → Project)
# ---------------------------------------------------------------------------


def _radio_from_dict(value: Any, path: str) -> RadioConfiguration:
    data = _require_dict(value, path)
    fields = (
        "p_tx_dbm",
        "g_tx_dbi",
        "l_tx_db",
        "g_rx_dbi",
        "l_rx_db",
        "sensitivity_dbm",
        "fade_margin_db",
    )
    kwargs: dict[str, float] = {}
    for field in fields:
        if field not in data:
            _fail(f"{path}.{field}: falta el campo obligatorio.")
        kwargs[field] = _require_number(data[field], f"{path}.{field}")
    if kwargs["fade_margin_db"] < 0:
        _fail(f"{path}.fade_margin_db no puede ser negativo.")
    return RadioConfiguration(**kwargs)


def _thresholds_from_dict(value: Any, path: str) -> CoverageThresholds:
    data = _require_dict(value, path)
    fields = (
        "rssi_target_dbm",
        "som_aprobado_min_db",
        "som_riesgo_min_db",
        "excellent_min_dbm",
        "good_min_dbm",
        "regular_min_dbm",
        "weak_min_dbm",
    )
    kwargs: dict[str, float] = {}
    for field in fields:
        if field not in data:
            _fail(f"{path}.{field}: falta el campo obligatorio.")
        kwargs[field] = _require_number(data[field], f"{path}.{field}")
    return CoverageThresholds(**kwargs)


def _bands_from_list(value: Any, path: str) -> list[FrequencyBand]:
    items = _require_list(value, path, MAX_BANDS)
    if not items:
        _fail(f"{path}: el proyecto necesita al menos una banda.")
    bands: list[FrequencyBand] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "name", "frequency_mhz"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        frequency = _require_number(
            data["frequency_mhz"], f"{item_path}.frequency_mhz", minimum=1e-6
        )
        bands.append(
            FrequencyBand(
                id=_require_id(data["id"], f"{item_path}.id"),
                name=_require_str(data["name"], f"{item_path}.name"),
                frequency_mhz=frequency,
            )
        )
    _require_unique([band.id for band in bands], path)
    return bands


def _materials_from_list(value: Any, path: str) -> list[Material]:
    items = _require_list(value, path, MAX_MATERIALS)
    materials: list[Material] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "name", "thickness_default_m", "attenuation_db"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        thickness = _require_number(
            data["thickness_default_m"],
            f"{item_path}.thickness_default_m",
            minimum=1e-6,
            maximum=MAX_THICKNESS_M,
        )
        raw_attenuation = _require_dict(
            data["attenuation_db"], f"{item_path}.attenuation_db"
        )
        attenuation: dict[str, float] = {}
        for band_id, raw_value in raw_attenuation.items():
            if not isinstance(band_id, str):
                _fail(f"{item_path}.attenuation_db: las claves deben ser texto.")
            attenuation[band_id] = _require_number(
                raw_value,
                f"{item_path}.attenuation_db.{band_id}",
                minimum=0.0,
                maximum=MAX_ATTENUATION_DB,
            )
        materials.append(
            Material(
                id=_require_id(data["id"], f"{item_path}.id"),
                name=_require_str(data["name"], f"{item_path}.name"),
                description=_require_str(
                    data.get("description", ""), f"{item_path}.description"
                ),
                thickness_default_m=thickness,
                attenuation_db=attenuation,
            )
        )
    _require_unique([material.id for material in materials], path)
    return materials


def _walls_from_list(
    value: Any, path: str, materials_by_id: dict[str, Material]
) -> list[Wall]:
    items = _require_list(value, path, MAX_WALLS)
    walls: list[Wall] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "start", "end", "material_id"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        material_id = _require_id(data["material_id"], f"{item_path}.material_id")
        if material_id not in materials_by_id:
            _fail(f"{item_path}.material_id: material desconocido {material_id!r}.")
        raw_thickness = data.get("thickness_m")
        if raw_thickness is None:
            thickness: float | None = None
        else:
            thickness = _require_number(
                raw_thickness,
                f"{item_path}.thickness_m",
                minimum=1e-6,
                maximum=MAX_THICKNESS_M,
            )
        start = _point_from_dict(data["start"], f"{item_path}.start")
        end = _point_from_dict(data["end"], f"{item_path}.end")
        if start.distance_to(end) < 1e-6:
            _fail(f"{item_path}: la pared necesita dos puntos distintos.")
        walls.append(
            Wall(
                id=_require_id(data["id"], f"{item_path}.id"),
                segment=Segment2D(start, end),
                material=materials_by_id[material_id],
                thickness_m=thickness,
                blocks_signal=_require_bool(
                    data.get("blocks_signal", True), f"{item_path}.blocks_signal"
                ),
            )
        )
    _require_unique([wall.id for wall in walls], path)
    return walls


def _floors_from_list(
    value: Any, path: str, materials_by_id: dict[str, Material]
) -> list[Floor]:
    items = _require_list(value, path, MAX_FLOORS)
    floors: list[Floor] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "width_m", "height_m", "walls"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        width = _require_number(
            data["width_m"],
            f"{item_path}.width_m",
            minimum=1e-6,
            maximum=MAX_DIMENSION_M,
        )
        height = _require_number(
            data["height_m"],
            f"{item_path}.height_m",
            minimum=1e-6,
            maximum=MAX_DIMENSION_M,
        )
        walls = _walls_from_list(
            data["walls"], f"{item_path}.walls", materials_by_id
        )
        floors.append(
            Floor(
                id=_require_id(data["id"], f"{item_path}.id"),
                name=_require_str(data.get("name", ""), f"{item_path}.name"),
                level=_require_int(data.get("level", 0), f"{item_path}.level"),
                walls=walls,
                elevation_m=_require_number(
                    data.get("elevation_m", 0.0),
                    f"{item_path}.elevation_m",
                    minimum=-10_000.0,
                    maximum=10_000.0,
                ),
                width_m=width,
                height_m=height,
                metadata=_validate_metadata(
                    data.get("metadata"), f"{item_path}.metadata"
                ),
            )
        )
    _require_unique([floor.id for floor in floors], path)
    return floors


def _aps_from_list(value: Any, path: str) -> list[AccessPoint]:
    items = _require_list(value, path, MAX_APS)
    aps: list[AccessPoint] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "position"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        raw_channel = data.get("channel")
        channel: int | None = None
        if raw_channel is not None:
            channel = _require_int(raw_channel, f"{item_path}.channel", minimum=0)
        if "radio" in data:
            radio = _radio_from_dict(data["radio"], f"{item_path}.radio")
        else:
            radio = RadioConfiguration()
        aps.append(
            AccessPoint(
                id=_require_id(data["id"], f"{item_path}.id"),
                position=_point_from_dict(data["position"], f"{item_path}.position"),
                radio=radio,
                channel=channel,
                name=_require_str(data.get("name", ""), f"{item_path}.name"),
                enabled=_require_bool(data.get("enabled", True), f"{item_path}.enabled"),
                metadata=_validate_metadata(
                    data.get("metadata"), f"{item_path}.metadata"
                ),
            )
        )
    _require_unique([ap.id for ap in aps], path)
    return aps


def _clients_from_list(value: Any, path: str) -> list[ClientDevice]:
    items = _require_list(value, path, MAX_CLIENTS)
    clients: list[ClientDevice] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "position"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        clients.append(
            ClientDevice(
                id=_require_id(data["id"], f"{item_path}.id"),
                position=_point_from_dict(data["position"], f"{item_path}.position"),
                sensitivity_dbm=_require_number(
                    data.get("sensitivity_dbm", -75.0),
                    f"{item_path}.sensitivity_dbm",
                    minimum=-200.0,
                    maximum=0.0,
                ),
                name=_require_str(data.get("name", ""), f"{item_path}.name"),
                metadata=_validate_metadata(
                    data.get("metadata"), f"{item_path}.metadata"
                ),
            )
        )
    _require_unique([client.id for client in clients], path)
    return clients


def project_from_dict(value: Any) -> Project:
    """Valida y reconstruye un ``Project`` desde datos JSON.

    Raises:
        ProjectFormatError: estructura, tipos, límites o referencias
            inválidas (p. ej. material inexistente, id duplicado, NaN).
    """
    data = _require_dict(value, "project")
    for field in (
        "name",
        "units",
        "bands",
        "materials",
        "radio",
        "thresholds",
        "floors",
        "access_points",
        "clients",
    ):
        if field not in data:
            _fail(f"project.{field}: falta el campo obligatorio.")

    units = _require_str(data["units"], "project.units", max_len=16)
    if units != "m":
        _fail(f"project.units: unidad no soportada {units!r} (se espera 'm').")

    name = _require_str(data["name"], "project.name", allow_empty=False)
    bands = _bands_from_list(data["bands"], "project.bands")
    materials = _materials_from_list(data["materials"], "project.materials")
    materials_by_id = {material.id: material for material in materials}
    floors = _floors_from_list(data["floors"], "project.floors", materials_by_id)
    access_points = _aps_from_list(data["access_points"], "project.access_points")
    clients = _clients_from_list(data["clients"], "project.clients")
    metadata = _validate_metadata(data.get("metadata"), "project.metadata")

    project = Project(
        name=name,
        units=units,
        bands=bands,
        materials=materials,
        radio=_radio_from_dict(data["radio"], "project.radio"),
        thresholds=_thresholds_from_dict(data["thresholds"], "project.thresholds"),
        access_points=access_points,
        clients=clients,
        floors=floors,
        metadata=metadata,
    )
    return project


def _validate_grid_resolution(project: Project, resolution_m: float) -> None:
    """La resolución debe producir un grid usable con el piso del archivo."""
    if not (0.0 < resolution_m <= MAX_RESOLUTION_M):
        _fail(
            "editor.grid_resolution_m: debe estar en (0, "
            f"{MAX_RESOLUTION_M:g}] (got {resolution_m})."
        )
    if not project.floors:
        return
    from engine.coverage_grid import CoverageGrid

    floor = project.floors[0]
    if floor.width_m is None or floor.height_m is None:
        return
    try:
        grid = CoverageGrid(
            width_m=floor.width_m,
            height_m=floor.height_m,
            resolution_m=resolution_m,
        )
    except ValueError as exc:
        _fail(f"editor.grid_resolution_m: {exc}")
    if grid.point_count <= 0:
        _fail("editor.grid_resolution_m: el grid quedaría vacío.")


def document_from_dict(value: Any) -> tuple[Project, EditorState]:
    """Valida el documento completo y devuelve ``(project, editor_state)``.

    Raises:
        ProjectFormatError: versión incompatible, JSON malformado o
            valores inválidos. Nunca devuelve un estado parcial.
    """
    try:
        return _document_from_dict(value)
    except ProjectFormatError:
        raise
    except (ValueError, TypeError) as exc:
        raise ProjectFormatError(f"Valores inválidos en el documento: {exc}") from exc


def _document_from_dict(value: Any) -> tuple[Project, EditorState]:
    document = _require_dict(value, "documento")
    version = document.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        _fail("schema_version: falta el campo o no es un entero.")
    if version != SCHEMA_VERSION:
        _fail(
            f"Versión de esquema incompatible: {version} "
            f"(esta aplicación soporta schema_version={SCHEMA_VERSION})."
        )
    if "project" not in document:
        _fail("project: falta la sección obligatoria del proyecto.")

    project = project_from_dict(document["project"])

    raw_editor = document.get("editor")
    if raw_editor is None:
        state = EditorState(band_id=_default_band_id(project))
    else:
        editor = _require_dict(raw_editor, "editor")
        for field in ("band_id", "grid_resolution_m"):
            if field not in editor:
                _fail(f"editor.{field}: falta el campo obligatorio.")
        band_id = _require_id(editor["band_id"], "editor.band_id")
        known = {band.id for band in project.bands}
        if band_id not in known:
            _fail(f"editor.band_id: banda desconocida {band_id!r}.")
        resolution = _require_number(
            editor["grid_resolution_m"], "editor.grid_resolution_m", minimum=1e-6
        )
        state = EditorState(band_id=band_id, grid_resolution_m=resolution)

    _validate_grid_resolution(project, state.grid_resolution_m)
    return project, state


# ---------------------------------------------------------------------------
# Archivo (guardar / abrir)
# ---------------------------------------------------------------------------


def save_project(
    project: Project,
    path: str | Path,
    editor_state: EditorState | None = None,
) -> Path:
    """Guarda el proyecto en ``path`` de forma atómica (temp + replace).

    El documento se revalida antes de escribir: nunca se deja en disco
    un archivo que la propia aplicación no podría abrir.

    Raises:
        ProjectFormatError: el proyecto no es serializable o no valida.
        OSError: error de escritura (el archivo previo queda intacto).
    """
    document = document_to_dict(project, editor_state)
    # Revalidación: lo que guardas debe poder abrirse.
    document_from_dict(document)

    try:
        text = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProjectFormatError(
            f"El proyecto no es serializable a JSON: {exc}"
        ) from exc

    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)

    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def load_project(path: str | Path) -> tuple[Project, EditorState]:
    """Carga y valida un proyecto desde ``path``.

    Raises:
        ProjectFormatError: archivo ausente, demasiado grande, no UTF-8,
            JSON inválido, esquema incompatible o valores inválidos.
    """
    source = Path(path)
    if not source.is_file():
        raise ProjectFormatError(f"El archivo no existe: {source}")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ProjectFormatError(f"No se puede leer {source}: {exc}") from exc
    if size > MAX_FILE_BYTES:
        raise ProjectFormatError(
            f"Archivo demasiado grande ({size} bytes; máximo {MAX_FILE_BYTES})."
        )
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectFormatError(
            f"El archivo no es texto UTF-8 válido: {exc}"
        ) from exc
    except OSError as exc:
        raise ProjectFormatError(f"No se puede leer {source}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectFormatError(f"JSON inválido en {source.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectFormatError(
            f"El documento debe ser un objeto JSON (got {type(data).__name__})."
        )
    return document_from_dict(data)
