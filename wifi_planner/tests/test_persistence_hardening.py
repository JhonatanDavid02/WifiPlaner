"""Fase 6.1 — endurecimiento de la persistencia (input no confiable).

Complementa ``tests/test_persistence.py`` (F6) sin modificarlo. Cubre:
parser duro (enteros gigantes, recorrupción), límites extremos,
invariantes de edición (dimensiones ↔ resolución, banda validada),
simetría guardar/cargar (≥1 piso), estado residual al abrir,
determinismo de resultados tras reload y fallos de escritura.

No toca el modelo RF: solo persistencia, sesión y flujos.
"""

from __future__ import annotations

import json
import os

import pytest

from core.geometry import Point2D
from core.material import MaterialAttenuationError
from persistence import (
    ProjectFormatError,
    document_to_dict,
    load_project,
    save_project,
)
from persistence import json_project_repository as repository
from ui.session import HEATMAP_ALL_APS, EditorSession


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

@pytest.fixture
def rich() -> EditorSession:
    """Proyecto rico: 20×15 m, pared concreto, 2 AP, 1 cliente."""
    s = EditorSession()
    s.set_floor_dimensions(20.0, 15.0)
    wall = s.add_wall(Point2D(2.0, 1.0), Point2D(9.0, 1.0))
    s.set_wall_material(wall.id, "concrete")
    s.set_wall_thickness(wall.id, 0.2)
    s.add_access_point(Point2D(3.0, 3.0))
    s.add_access_point(Point2D(12.0, 8.0))
    s.add_client(Point2D(5.0, 5.0))
    return s


def base_doc(session: EditorSession) -> dict:
    return document_to_dict(session.project, session.editor_state())


def write_doc(tmp_path, document, name: str) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def write_text(tmp_path, text: str, name: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def expect_rejected(path) -> str:
    with pytest.raises(ProjectFormatError) as exc:
        load_project(path)
    return str(exc.value)


def fingerprint(result) -> list:
    return [
        (e.access_point_id, e.rx_power_dbm, e.som_db, e.quality, e.verdict)
        for e in result.evaluations
    ]


# ---------------------------------------------------------------------------
# Parser duro (input no confiable desde el parser, no solo el validador)
# ---------------------------------------------------------------------------

def test_huge_integer_literal_is_controlled(tmp_path):
    """Entero con > 4300 dígitos: el parser lanza ValueError controlado."""
    big = "1" * 5000
    text = '{"schema_version": 1, "project": {"name": ' + big + "}}"
    path = write_text(tmp_path, text, "huge_int.json")
    with pytest.raises(ProjectFormatError, match="JSON ilegible"):
        load_project(path)


def test_parser_recursion_error_is_controlled(tmp_path, monkeypatch, rich):
    path = save_project(rich.project, tmp_path / "ok.json", rich.editor_state())

    def boom(*_args, **_kwargs):
        raise RecursionError("profundidad")

    monkeypatch.setattr(json, "loads", boom)
    with pytest.raises(ProjectFormatError, match="JSON ilegible"):
        load_project(path)


def test_truncated_json_is_controlled(tmp_path):
    good = '{"schema_version": 1, "project": {"name": "x", "units": "m",'
    path = write_text(tmp_path, good, "truncated.json")
    with pytest.raises(ProjectFormatError, match="JSON inválido"):
        load_project(path)


def test_infinity_literal_is_rejected(rich, tmp_path):
    doc = base_doc(rich)
    text = json.dumps(doc).replace('"p_tx_dbm": 20.0', '"p_tx_dbm": Infinity')
    path = write_text(tmp_path, text, "infinity.json")
    with pytest.raises(ProjectFormatError, match="no finito"):
        load_project(path)


def test_schema_version_bool_is_rejected(rich, tmp_path):
    doc = base_doc(rich)
    doc["schema_version"] = True
    with pytest.raises(ProjectFormatError, match="schema_version"):
        load_project(write_doc(tmp_path, doc, "bool_version.json"))


def test_load_directory_is_controlled(tmp_path):
    with pytest.raises(ProjectFormatError, match="no es un archivo"):
        load_project(tmp_path)


# ---------------------------------------------------------------------------
# Tipos: booleanos donde van números y viceversa
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("section", "key", "value", "match"),
    [
        ("access_points", "channel", True, "entero"),
        ("floors", "level", True, "entero"),
        ("bands", "frequency_mhz", True, "número"),
        ("radio", "p_tx_dbm", "20", "número"),
        ("radio", "sensitivity_dbm", "-75", "número"),
    ],
)
def test_wrong_types_in_numeric_fields(rich, tmp_path, section, key, value, match):
    doc = base_doc(rich)
    container = doc["project"][section]
    container = container[0] if isinstance(container, list) else container
    container[key] = value
    with pytest.raises(ProjectFormatError, match=match):
        load_project(write_doc(tmp_path, doc, f"type_{key}.json"))


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("thickness_m", True, "número"),
        ("blocks_signal", 1, "true/false"),
        ("enabled", 1, "true/false"),
    ],
)
def test_wrong_types_wall_and_ap_flags(rich, tmp_path, key, value, match):
    doc = base_doc(rich)
    if key == "enabled":
        doc["project"]["access_points"][0][key] = value
    else:
        doc["project"]["floors"][0]["walls"][0][key] = value
    with pytest.raises(ProjectFormatError, match=match):
        load_project(write_doc(tmp_path, doc, f"flag_{key}.json"))


def test_string_where_number_expected(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["floors"][0]["width_m"] = "12"
    with pytest.raises(ProjectFormatError, match="número"):
        load_project(write_doc(tmp_path, doc, "width_str.json"))

    doc = base_doc(rich)
    doc["project"]["access_points"][0]["position"]["x_m"] = "1.0"
    with pytest.raises(ProjectFormatError, match="número"):
        load_project(write_doc(tmp_path, doc, "coord_str.json"))


# ---------------------------------------------------------------------------
# Límites extremos válidos e inválidos
# ---------------------------------------------------------------------------

def test_max_dimensions_round_trip(tmp_path):
    """10000 m por lado (máximo) con resolución compatible: round-trip."""
    s = EditorSession()
    s.set_grid_resolution(2.0)
    s.set_floor_dimensions(10_000.0, 10.0)
    path = save_project(s.project, tmp_path / "max.json", s.editor_state())
    loaded, state = load_project(path)
    assert loaded.floors[0].width_m == pytest.approx(10_000.0)
    assert loaded.floors[0].height_m == pytest.approx(10.0)
    assert state.grid_resolution_m == pytest.approx(2.0)


def test_min_dimensions_round_trip(tmp_path):
    s = EditorSession()
    s.set_floor_dimensions(0.1, 0.1)
    path = save_project(s.project, tmp_path / "min.json", s.editor_state())
    loaded, _ = load_project(path)
    assert loaded.floors[0].width_m == pytest.approx(0.1)
    assert loaded.floors[0].height_m == pytest.approx(0.1)


def test_coordinate_at_exact_limit_accepted(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["access_points"][0]["position"] = {
        "x_m": 100_000.0,
        "y_m": -100_000.0,
    }
    load_project(write_doc(tmp_path, doc, "coord_limit.json"))

    doc["project"]["access_points"][0]["position"]["x_m"] = 100_000.1
    with pytest.raises(ProjectFormatError, match="x_m"):
        load_project(write_doc(tmp_path, doc, "coord_over.json"))


def test_thickness_at_limits(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["floors"][0]["walls"][0]["thickness_m"] = 10.0
    load_project(write_doc(tmp_path, doc, "thick_max.json"))

    doc["project"]["floors"][0]["walls"][0]["thickness_m"] = 10.0001
    with pytest.raises(ProjectFormatError, match="thickness_m"):
        load_project(write_doc(tmp_path, doc, "thick_over.json"))


def test_string_length_limits(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["name"] = "n" * repository.MAX_NAME_LEN
    load_project(write_doc(tmp_path, doc, "name_ok.json"))

    doc["project"]["name"] = "n" * (repository.MAX_NAME_LEN + 1)
    with pytest.raises(ProjectFormatError, match="demasiado largo"):
        load_project(write_doc(tmp_path, doc, "name_long.json"))

    doc = base_doc(rich)
    doc["project"]["access_points"][0]["id"] = "A" * repository.MAX_ID_LEN
    load_project(write_doc(tmp_path, doc, "id_ok.json"))

    doc["project"]["access_points"][0]["id"] = "A" * (repository.MAX_ID_LEN + 1)
    with pytest.raises(ProjectFormatError, match="demasiado largo"):
        load_project(write_doc(tmp_path, doc, "id_long.json"))


def test_list_size_limit_enforced(rich, tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "MAX_WALLS", 3)
    doc = base_doc(rich)
    walls = [
        {
            "id": f"WALL-{n:03d}",
            "start": {"x_m": 0.0, "y_m": float(n)},
            "end": {"x_m": 5.0, "y_m": float(n)},
            "material_id": "drywall",
        }
        for n in (1, 2, 3, 4)
    ]
    doc["project"]["floors"][0]["walls"] = walls
    with pytest.raises(ProjectFormatError, match="demasiados elementos"):
        load_project(write_doc(tmp_path, doc, "too_many.json"))

    doc["project"]["floors"][0]["walls"] = walls[:3]
    load_project(write_doc(tmp_path, doc, "at_limit.json"))


def _nested_metadata(depth: int) -> dict:
    root: dict = {}
    node = root
    for _ in range(depth):
        node["k"] = {}
        node = node["k"]
    return root


def test_metadata_depth_limit(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["metadata"] = _nested_metadata(10)
    load_project(write_doc(tmp_path, doc, "meta_ok.json"))

    doc["project"]["metadata"] = _nested_metadata(11)
    with pytest.raises(ProjectFormatError, match="profunda"):
        load_project(write_doc(tmp_path, doc, "meta_deep.json"))


def test_radio_sensitivity_bounds(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["radio"]["sensitivity_dbm"] = -200.0
    load_project(write_doc(tmp_path, doc, "sens_min.json"))
    doc["project"]["radio"]["sensitivity_dbm"] = 0.0
    load_project(write_doc(tmp_path, doc, "sens_max.json"))

    doc["project"]["radio"]["sensitivity_dbm"] = -200.1
    with pytest.raises(ProjectFormatError, match="sensitivity_dbm"):
        load_project(write_doc(tmp_path, doc, "sens_low.json"))
    doc["project"]["radio"]["sensitivity_dbm"] = 0.1
    with pytest.raises(ProjectFormatError, match="sensitivity_dbm"):
        load_project(write_doc(tmp_path, doc, "sens_high.json"))


def test_empty_floors_rejected(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["floors"] = []
    with pytest.raises(ProjectFormatError, match="al menos un piso"):
        load_project(write_doc(tmp_path, doc, "no_floors.json"))


def test_save_refuses_project_without_floor(tmp_path):
    """Simetría: si cargar exige piso, guardar nunca escribe sin piso."""
    s = EditorSession()
    s.project.floors.clear()
    target = tmp_path / "sin_piso.json"
    with pytest.raises(ProjectFormatError, match="al menos un piso"):
        save_project(s.project, target)
    assert not target.exists()


# ---------------------------------------------------------------------------
# Invariantes de edición (dimensiones ↔ resolución, banda)
# ---------------------------------------------------------------------------

def test_dimensions_too_large_for_resolution_rejected():
    """El invariante «dims + resolución ⇒ grid válido» también al cambiar dims."""
    s = EditorSession()
    assert s.grid_resolution_m == pytest.approx(0.5)
    with pytest.raises(ValueError, match="resolución"):
        s.set_floor_dimensions(10_000.0, 10_000.0)
    # No se aplicó nada: el proyecto sigue siendo editable y guardable.
    assert s.floor_width_m == pytest.approx(12.0)
    assert s.floor_height_m == pytest.approx(8.0)
    assert s.dirty is False


def test_dimensions_accepted_after_resolution_adjusted():
    s = EditorSession()
    with pytest.raises(ValueError):
        s.set_floor_dimensions(10_000.0, 10.0)  # 0.5 m ⇒ > 100k puntos
    s.set_grid_resolution(2.0)
    s.set_floor_dimensions(10_000.0, 10.0)
    assert s.floor_width_m == pytest.approx(10_000.0)


def test_band_validated_before_assignment():
    """Una banda inválida no corrompe session.band_id."""
    s = EditorSession()
    s.add_access_point(Point2D(3.0, 3.0))
    with pytest.raises(KeyError):
        s.run_heatmap("band_99")
    assert s.band_id == "band_2_4"
    with pytest.raises(KeyError):
        s.run_simulation("band_99")
    assert s.band_id == "band_2_4"


def test_band_change_via_simulation_marks_dirty():
    s = EditorSession()
    s.add_access_point(Point2D(3.0, 3.0))
    s.mark_saved()
    s.run_heatmap()  # misma banda: no marca
    assert s.dirty is False
    s.run_simulation("band_5")  # banda persistible cambia: marca
    assert s.dirty is True
    assert s.band_id == "band_5"


# ---------------------------------------------------------------------------
# Nada derivado en el archivo; nada residual al abrir
# ---------------------------------------------------------------------------

def test_no_derived_state_persisted(rich, tmp_path):
    path = save_project(rich.project, tmp_path / "limpio.json", rich.editor_state())
    raw_text = open(path, encoding="utf-8").read()
    for forbidden in (
        "generated_at",
        "last_heatmap",
        "last_simulation",
        "selection",
        "wall_drag",
        "heatmap_enabled",
    ):
        assert forbidden not in raw_text

    document = json.loads(raw_text)
    assert set(document) == {"schema_version", "project", "editor"}
    assert set(document["project"]) == {
        "name", "units", "bands", "materials", "radio", "thresholds",
        "floors", "access_points", "clients", "metadata",
    }
    assert set(document["editor"]) == {"band_id", "grid_resolution_m"}


def test_open_b_leaves_no_state_of_a(tmp_path):
    # Proyecto A: 5 GHz, res. 0.25, 2 AP, paredes, selección.
    proj_a = EditorSession()
    proj_a.set_floor_dimensions(20.0, 15.0)
    proj_a.add_wall(Point2D(0.0, 5.0), Point2D(20.0, 5.0))
    proj_a.add_access_point(Point2D(3.0, 3.0))
    proj_a.add_access_point(Point2D(10.0, 6.0))
    proj_a.add_client(Point2D(5.0, 5.0))
    proj_a.set_band("band_5")
    proj_a.set_grid_resolution(0.25)
    proj_a.set_heatmap_ap("AP-002")
    proj_a.run_heatmap()
    path_a = str(tmp_path / "a.json")
    proj_a.save_project(path_a)

    # Proyecto B: 2.4 GHz, res. 1.0, 1 AP, otras dimensiones.
    proj_b = EditorSession()
    proj_b.set_floor_dimensions(10.0, 6.0)
    proj_b.set_grid_resolution(1.0)
    proj_b.add_access_point(Point2D(1.0, 1.0))
    path_b = str(tmp_path / "b.json")
    proj_b.save_project(path_b)

    # Reabrir A en la sesión que conoce B (estado residual previo).
    session = EditorSession()
    session.open_project(path_a)
    session.select(None, None)
    session.open_project(path_b)

    assert [ap.id for ap in session.project.access_points] == ["AP-001"]
    assert session.project.access_points[0].position == Point2D(1.0, 1.0)
    assert session.floor.walls == []
    assert session.project.clients == []
    assert session.floor_width_m == pytest.approx(10.0)
    assert session.floor_height_m == pytest.approx(6.0)
    assert session.band_id == "band_2_4"
    assert session.grid_resolution_m == pytest.approx(1.0)
    assert session.selection is None
    assert session.heatmap_ap_id == HEATMAP_ALL_APS
    assert session.last_heatmap is None
    assert session.last_simulation is None
    assert session.heatmap_dirty is True
    assert session.dirty is False
    assert session.project_path == path_b


# ---------------------------------------------------------------------------
# IDs: continúan correctamente tras guardar/cargar
# ---------------------------------------------------------------------------

def test_ids_continue_after_reload(rich, tmp_path):
    path = str(tmp_path / "ids.json")
    rich.save_project(path)

    reopened = EditorSession()
    reopened.open_project(path)
    assert reopened.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0)).id == "WALL-002"
    assert reopened.add_client(Point2D(1.0, 1.0)).id == "CLIENT-002"
    assert reopened.add_access_point(Point2D(1.0, 1.0)).id == "AP-003"


def test_custom_id_continues_sequence(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["access_points"][0]["id"] = "AP-007"
    path = write_doc(tmp_path, doc, "custom_id.json")
    session = EditorSession()
    session.open_project(path)
    assert session.add_access_point(Point2D(1.0, 1.0)).id == "AP-008"


# ---------------------------------------------------------------------------
# Flujos: save → load → modify → save, new, save as
# ---------------------------------------------------------------------------

def test_save_load_modify_save_flow(tmp_path):
    s = EditorSession()
    first = str(tmp_path / "flow.json")
    s.save_project(first)
    s.add_access_point(Point2D(2.0, 2.0))
    s.save_project()

    reopened = EditorSession()
    reopened.open_project(first)
    assert len(reopened.project.access_points) == 1
    reopened.add_access_point(Point2D(4.0, 4.0))
    reopened.save_project()

    final = EditorSession()
    final.open_project(first)
    assert [ap.id for ap in final.project.access_points] == ["AP-001", "AP-002"]
    assert final.dirty is False


def test_new_then_save_as(tmp_path):
    s = EditorSession()
    s.add_access_point(Point2D(1.0, 1.0))
    s.new_project()
    assert s.project_path is None
    assert s.dirty is False
    with pytest.raises(ValueError, match="Guardar como"):
        s.save_project()
    path = s.save_project_as(str(tmp_path / "nuevo.json"))
    loaded, _ = load_project(path)
    assert loaded.access_points == []
    assert loaded.floors[0].width_m == pytest.approx(12.0)


def test_save_without_path_does_not_change_dirty():
    s = EditorSession()
    s.add_access_point(Point2D(1.0, 1.0))
    s.mark_saved()
    with pytest.raises(ValueError):  # sin ruta: "Guardar como…"
        s.save_project()
    assert s.dirty is False  # nada se modificó: sigue limpio


# ---------------------------------------------------------------------------
# Regresión de simulación y multi-AP tras reload (objetivos 13/14)
# ---------------------------------------------------------------------------

def test_simulation_stats_identical_after_reload(rich, tmp_path):
    rich.set_band("band_5")
    before = rich.run_simulation()
    path = str(tmp_path / "stats.json")
    rich.save_project(path)

    reopened = EditorSession()
    reopened.open_project(path)
    after = reopened.run_simulation()

    assert before.band_id == after.band_id
    assert before.stats == after.stats
    assert fingerprint(before) == fingerprint(after)


def test_multi_ap_selector_after_reload(rich, tmp_path):
    rich.set_band("band_5")
    combined_before = rich.run_heatmap()
    rich.set_heatmap_ap("AP-001")
    single_before = rich.run_heatmap()
    path = str(tmp_path / "selector.json")
    rich.save_project(path)

    reopened = EditorSession()
    reopened.open_project(path)

    combined_after = reopened.run_heatmap()
    assert fingerprint(combined_before) == fingerprint(combined_after)
    assert combined_after.stats["ap_dominance_percent"] == (
        combined_before.stats["ap_dominance_percent"]
    )

    reopened.set_heatmap_ap("AP-001")
    single_after = reopened.run_heatmap()
    assert fingerprint(single_before) == fingerprint(single_after)
    assert {e.access_point_id for e in single_after.evaluations} == {"AP-001"}

    reopened.set_heatmap_ap(HEATMAP_ALL_APS)
    assert reopened.run_heatmap().stats["source_results"] == 2


def test_6ghz_behavior_unchanged_after_reload(tmp_path):
    s = EditorSession()
    s.add_access_point(Point2D(1.0, 1.0))
    wall = s.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 8.0))
    s.set_wall_material(wall.id, "concrete")
    s.add_client(Point2D(9.0, 4.0))
    path = str(tmp_path / "seis.json")
    s.save_project(path)

    reopened = EditorSession()
    reopened.open_project(path)
    with pytest.raises(MaterialAttenuationError):
        reopened.run_simulation("band_6")


# ---------------------------------------------------------------------------
# Escritura: fallos simulados no destruyen el archivo anterior
# ---------------------------------------------------------------------------

def test_replace_failure_preserves_previous_file(rich, tmp_path, monkeypatch):
    path = str(tmp_path / "atomico.json")
    rich.save_project(path)
    original = open(path, encoding="utf-8").read()

    def boom(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", boom)
    rich.add_access_point(Point2D(1.0, 1.0))
    with pytest.raises(OSError):
        rich.save_project(path)
    monkeypatch.undo()

    assert open(path, encoding="utf-8").read() == original
    assert list(tmp_path.glob("*.tmp")) == []
    assert rich.dirty is True  # la falla no marca como guardado


def test_write_failure_preserves_previous_file(rich, tmp_path, monkeypatch):
    path = str(tmp_path / "escritura.json")
    rich.save_project(path)
    original = open(path, encoding="utf-8").read()

    def boom(*_args, **_kwargs):
        raise OSError("sin espacio en disco")

    monkeypatch.setattr(repository, "open", boom, raising=False)
    rich.add_access_point(Point2D(1.0, 1.0))
    with pytest.raises(OSError):
        rich.save_project(path)

    assert open(path, encoding="utf-8").read() == original
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# Tolerancia documentada (misma versión de esquema)
# ---------------------------------------------------------------------------

def test_unknown_keys_ignored_same_version(rich, tmp_path):
    doc = base_doc(rich)
    doc["project"]["clave_futura"] = {"a": 1}
    load_project(write_doc(tmp_path, doc, "unknown.json"))


def test_editor_null_treated_as_absent(rich, tmp_path):
    doc = base_doc(rich)
    doc["editor"] = None
    project, state = load_project(write_doc(tmp_path, doc, "editor_null.json"))
    assert state.band_id == "band_2_4"
    assert state.grid_resolution_m == pytest.approx(0.5)
    assert project.name == rich.project.name
