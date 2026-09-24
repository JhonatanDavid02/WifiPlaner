"""Pruebas de persistencia local (Fase 6): Project ↔ JSON.

Cobertura (spec F6, tests 1–19): round-trip, IDs, metros, editor,
schema_version, errores controlados, atomicidad, dirty state,
compatibilidad F5 (multi-AP tras abrir) y regresión de simulación.
"""

from __future__ import annotations

import json

import pytest

from core.geometry import Point2D
from persistence import (
    SCHEMA_VERSION,
    EditorState,
    ProjectFormatError,
    document_from_dict,
    document_to_dict,
    load_project,
    project_from_dict,
    project_to_dict,
    save_project,
)
from ui.session import HEATMAP_ALL_APS, EditorSession


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

@pytest.fixture
def session() -> EditorSession:
    """Proyecto rico: 20×15 m, 2 paredes (materiales distintos), 2 AP, 1 cliente."""
    s = EditorSession()
    s.set_floor_dimensions(20.0, 15.0)
    w1 = s.add_wall(Point2D(2.0, 1.0), Point2D(8.0, 1.0))
    s.set_wall_material(w1.id, "concrete")
    s.set_wall_thickness(w1.id, 0.2)
    w2 = s.add_wall(Point2D(8.0, 1.0), Point2D(8.0, 10.0))
    s.set_wall_material(w2.id, "metal")
    s.add_access_point(Point2D(3.0, 3.0))
    s.add_access_point(Point2D(10.0, 6.0))
    s.add_client(Point2D(5.0, 5.0))
    return s


def save(session: EditorSession, tmp_path, name: str = "proj.json") -> str:
    return session.save_project(str(tmp_path / name))


def write_document(tmp_path, document, name: str = "doc.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def fingerprint(result):
    """Huella de un resultado SIN generated_at (no forma parte del proyecto)."""
    return [
        (
            e.access_point_id,
            e.rx_power_dbm,
            e.som_db,
            e.quality,
            e.verdict,
            e.obstacle_loss.total_db,
            e.point.x,
            e.point.y,
        )
        for e in result.evaluations
    ]


# ---------------------------------------------------------------------------
# Tests 1–9: round-trip de contenido
# ---------------------------------------------------------------------------

def test_01_minimal_project_round_trip(tmp_path):
    original = EditorSession().project
    path = save_project(original, tmp_path / "min.json")
    loaded, _state = load_project(path)
    assert project_to_dict(original) == project_to_dict(loaded)


def test_02_multiple_walls_round_trip(session, tmp_path):
    path = save(session, tmp_path)
    loaded, _ = load_project(path)
    walls = loaded.floors[0].walls
    assert len(walls) == 2
    assert {w.id for w in walls} == {"WALL-001", "WALL-002"}


def test_03_materials_and_thickness_preserved(session, tmp_path):
    path = save(session, tmp_path)
    loaded, _ = load_project(path)
    walls = {w.id: w for w in loaded.floors[0].walls}
    assert walls["WALL-001"].material.id == "concrete"
    assert walls["WALL-001"].thickness_m == pytest.approx(0.2)
    assert walls["WALL-002"].material.id == "metal"
    assert walls["WALL-002"].thickness_m is None  # usa el default del material
    # El catálogo de materiales viaja con el proyecto (autocontenido).
    assert {m.id for m in loaded.materials} == {m.id for m in session.project.materials}


def test_04_multiple_access_points_round_trip(session, tmp_path):
    path = save(session, tmp_path)
    loaded, _ = load_project(path)
    assert [ap.id for ap in loaded.access_points] == ["AP-001", "AP-002"]
    assert loaded.access_points[0].position == Point2D(3.0, 3.0)
    assert loaded.access_points[1].position == Point2D(10.0, 6.0)


def test_05_clients_round_trip(session, tmp_path):
    path = save(session, tmp_path)
    loaded, _ = load_project(path)
    assert [c.id for c in loaded.clients] == ["CLIENT-001"]
    assert loaded.clients[0].position == Point2D(5.0, 5.0)
    assert loaded.clients[0].sensitivity_dbm == pytest.approx(-75.0)


def test_06_ids_preserved_and_not_reused(session, tmp_path):
    path = save(session, tmp_path)
    reopened = EditorSession()
    reopened.open_project(path)
    assert [ap.id for ap in reopened.project.access_points] == ["AP-001", "AP-002"]
    # El siguiente AP sigue la secuencia (AP-003), no reutiliza AP-001.
    new_ap = reopened.add_access_point(Point2D(1.0, 1.0))
    assert new_ap.id == "AP-003"


def test_07_dimensions_preserved(session, tmp_path):
    path = save(session, tmp_path)
    reopened = EditorSession()
    reopened.open_project(path)
    assert reopened.floor_width_m == pytest.approx(20.0)
    assert reopened.floor_height_m == pytest.approx(15.0)


def test_08_coordinates_in_meters_preserved(tmp_path):
    s = EditorSession()
    ap = s.add_access_point(Point2D(2.5, 1.25))
    path = save(s, tmp_path)
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["project"]["access_points"][0]["position"] == {
        "x_m": 2.5,
        "y_m": 1.25,
    }
    loaded, _ = load_project(path)
    assert loaded.access_points[0].position == ap.position


def test_09_editor_band_and_resolution_preserved(session, tmp_path):
    session.set_band("band_5")
    session.set_grid_resolution(0.25)
    path = save(session, tmp_path)
    reopened = EditorSession()
    reopened.open_project(path)
    assert reopened.band_id == "band_5"
    assert reopened.grid_resolution_m == pytest.approx(0.25)


def test_project_metadata_round_trip(tmp_path):
    s = EditorSession()
    s.project.metadata.update({"author": "cun", "revision": 2, "tags": ["a", "b"]})
    path = save(s, tmp_path)
    loaded, _ = load_project(path)
    assert loaded.metadata == {"author": "cun", "revision": 2, "tags": ["a", "b"]}


def test_save_is_deterministic(session, tmp_path):
    first = save(session, tmp_path, "a.json")
    second = save(session, tmp_path, "b.json")
    with open(first, "rb") as handle:
        bytes_a = handle.read()
    with open(second, "rb") as handle:
        bytes_b = handle.read()
    assert bytes_a == bytes_b


def test_save_adds_json_extension(tmp_path):
    s = EditorSession()
    path = s.save_project(str(tmp_path / "sin_extension"))
    assert path.endswith(".json")


# ---------------------------------------------------------------------------
# Tests 10–14: schema_version, JSON corrupto, campos y valores inválidos
# ---------------------------------------------------------------------------

def test_10_schema_version_present(session, tmp_path):
    path = save(session, tmp_path)
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["schema_version"] == SCHEMA_VERSION == 1
    assert set(raw) == {"schema_version", "project", "editor"}


def test_11_schema_version_incompatible(session, tmp_path):
    document = document_to_dict(session.project, session.editor_state())
    document["schema_version"] = 99
    path = write_document(tmp_path, document)
    with pytest.raises(ProjectFormatError, match="esquema incompatible"):
        load_project(path)

    document["schema_version"] = "1"
    path = write_document(tmp_path, document, "string_version.json")
    with pytest.raises(ProjectFormatError, match="schema_version"):
        load_project(path)

    document.pop("schema_version")
    path = write_document(tmp_path, document, "missing_version.json")
    with pytest.raises(ProjectFormatError, match="schema_version"):
        load_project(path)


def test_12_corrupt_json_is_controlled_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{esto no es json", encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="JSON inválido"):
        load_project(bad)

    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="JSON inválido"):
        load_project(empty)

    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="objeto JSON"):
        load_project(not_object)

    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00\x00")
    with pytest.raises(ProjectFormatError, match="UTF-8"):
        load_project(binary)

    with pytest.raises(ProjectFormatError, match="no existe"):
        load_project(tmp_path / "missing.json")


def test_13_missing_required_fields(session, tmp_path):
    document = document_to_dict(session.project, session.editor_state())
    document.pop("project")
    path = write_document(tmp_path, document)
    with pytest.raises(ProjectFormatError, match="project"):
        load_project(path)

    document = document_to_dict(session.project, session.editor_state())
    del document["project"]["floors"][0]["walls"][0]["start"]
    path = write_document(tmp_path, document, "wall_no_start.json")
    with pytest.raises(ProjectFormatError, match="start"):
        load_project(path)

    document = document_to_dict(session.project, session.editor_state())
    del document["project"]["radio"]["p_tx_dbm"]
    path = write_document(tmp_path, document, "radio_no_ptx.json")
    with pytest.raises(ProjectFormatError, match="p_tx_dbm"):
        load_project(path)

    document = document_to_dict(session.project, session.editor_state())
    del document["editor"]["band_id"]
    path = write_document(tmp_path, document, "editor_no_band.json")
    with pytest.raises(ProjectFormatError, match="editor.band_id"):
        load_project(path)


def test_14_invalid_values_are_rejected(session, tmp_path):
    base = document_to_dict(session.project, session.editor_state())

    # Coordenada no finita (JSON acepta NaN literales).
    document = json.loads(json.dumps(base))
    document["project"]["access_points"][0]["position"]["x_m"] = float("nan")
    path = write_document(tmp_path, document, "nan.json")
    with pytest.raises(ProjectFormatError, match="no finito"):
        load_project(path)

    # Espesor negativo.
    document = json.loads(json.dumps(base))
    document["project"]["floors"][0]["walls"][0]["thickness_m"] = -1.0
    path = write_document(tmp_path, document, "negative.json")
    with pytest.raises(ProjectFormatError, match="thickness_m"):
        load_project(path)

    # Material inexistente.
    document = json.loads(json.dumps(base))
    document["project"]["floors"][0]["walls"][0]["material_id"] = "unobtainium"
    path = write_document(tmp_path, document, "bad_material.json")
    with pytest.raises(ProjectFormatError, match="material desconocido"):
        load_project(path)

    # ID duplicado.
    document = json.loads(json.dumps(base))
    document["project"]["access_points"][1]["id"] = "AP-001"
    path = write_document(tmp_path, document, "dup.json")
    with pytest.raises(ProjectFormatError, match="duplicado"):
        load_project(path)

    # Banda desconocida en el estado de editor.
    document = json.loads(json.dumps(base))
    document["editor"]["band_id"] = "band_99"
    path = write_document(tmp_path, document, "bad_band.json")
    with pytest.raises(ProjectFormatError, match="banda desconocida"):
        load_project(path)

    # Resolución inválida.
    document = json.loads(json.dumps(base))
    document["editor"]["grid_resolution_m"] = 0.0
    path = write_document(tmp_path, document, "zero_res.json")
    with pytest.raises(ProjectFormatError):
        load_project(path)

    # Unidad distinta de metros.
    document = json.loads(json.dumps(base))
    document["project"]["units"] = "px"
    path = write_document(tmp_path, document, "units_px.json")
    with pytest.raises(ProjectFormatError, match="unidad no soportada"):
        load_project(path)

    # Coordenada absurda.
    document = json.loads(json.dumps(base))
    document["project"]["access_points"][0]["position"]["y_m"] = 1e9
    path = write_document(tmp_path, document, "huge.json")
    with pytest.raises(ProjectFormatError, match="y_m"):
        load_project(path)

    # Bool donde debe haber número.
    document = json.loads(json.dumps(base))
    document["project"]["radio"]["p_tx_dbm"] = True
    path = write_document(tmp_path, document, "bool_number.json")
    with pytest.raises(ProjectFormatError, match="número"):
        load_project(path)


def test_document_from_dict_requires_object():
    with pytest.raises(ProjectFormatError, match="objeto JSON"):
        document_from_dict(["no"])


def test_project_from_dict_requires_lists():
    with pytest.raises(ProjectFormatError):
        project_from_dict({"name": "x", "units": "m"})


def test_file_size_limit(monkeypatch, session, tmp_path):
    import persistence.json_project_repository as repository

    path = save(session, tmp_path)
    monkeypatch.setattr(repository, "MAX_FILE_BYTES", 10)
    with pytest.raises(ProjectFormatError, match="demasiado grande"):
        repository.load_project(path)


def test_save_revalidates_before_writing(tmp_path):
    """Un proyecto que no puede abrirse tampoco se guarda."""
    s = EditorSession()
    # Espesor fuera de límites por construcción directa del modelo.
    from dataclasses import replace as dc_replace

    wall = s.add_wall(Point2D(0.0, 1.0), Point2D(5.0, 1.0))
    s.floor.walls[0] = dc_replace(wall, thickness_m=12.0)
    with pytest.raises(ProjectFormatError):
        s.save_project(str(tmp_path / "no_escrito.json"))
    assert not (tmp_path / "no_escrito.json").exists()


# ---------------------------------------------------------------------------
# Test 15: el proyecto actual queda intacto si abrir falla
# ---------------------------------------------------------------------------

def test_15_failed_open_keeps_current_project(session, tmp_path):
    good = save(session, tmp_path, "good.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{corrupt", encoding="utf-8")

    before = project_to_dict(session.project)
    session.mark_dirty()
    with pytest.raises(ProjectFormatError):
        session.open_project(str(bad))
    assert project_to_dict(session.project) == before
    assert session.dirty is True
    assert session.project_path == good

    # Una versión incompatible tampoco toca el proyecto.
    document = document_to_dict(session.project, session.editor_state())
    document["schema_version"] = 7
    incompatible = write_document(tmp_path, document, "v7.json")
    with pytest.raises(ProjectFormatError):
        session.open_project(incompatible)
    assert project_to_dict(session.project) == before


# ---------------------------------------------------------------------------
# Tests 16–18: simulación equivalente tras el round-trip
# ---------------------------------------------------------------------------

def test_16_round_trip_simulation_equivalent(session, tmp_path):
    session.set_band("band_5")
    before = session.run_simulation()
    path = save(session, tmp_path)

    reopened = EditorSession()
    reopened.open_project(path)
    after = reopened.run_simulation()

    assert fingerprint(before) == fingerprint(after)
    assert before.band_id == after.band_id
    assert before.stats["point_count"] == after.stats["point_count"]


def test_17_loaded_multi_ap_combine(session, tmp_path):
    path = save(session, tmp_path)
    reopened = EditorSession()
    reopened.open_project(path)
    result = reopened.run_heatmap()
    assert result.stats["source_results"] == 2
    assert result.stats["combined"] is True
    assert set(result.stats["ap_dominance_percent"]) == {"AP-001", "AP-002"}
    # Selector F5 reconstruido tras abrir.
    assert reopened.heatmap_ap_id == HEATMAP_ALL_APS
    assert reopened.ap_choices_for_heatmap() == [HEATMAP_ALL_APS, "AP-001", "AP-002"]


def test_18_loaded_walls_affect_propagation(tmp_path):
    s = EditorSession()
    s.add_access_point(Point2D(3.0, 3.0))
    wall = s.add_wall(Point2D(0.0, 1.0), Point2D(8.0, 1.0))
    s.set_wall_material(wall.id, "concrete")
    s.add_client(Point2D(5.0, 0.5))  # detrás de la pared
    before = s.run_simulation()
    path = save(s, tmp_path)

    reopened = EditorSession()
    reopened.open_project(path)
    after = reopened.run_simulation()

    assert before.evaluations[0].obstacle_loss.total_db > 0
    assert fingerprint(before) == fingerprint(after)

    # Contraste: sin paredes no hay pérdida por obstáculos.
    bare = EditorSession()
    bare.add_access_point(Point2D(3.0, 3.0))
    bare.add_client(Point2D(5.0, 0.5))
    assert bare.run_simulation().evaluations[0].obstacle_loss.total_db == 0.0


def test_two_loads_produce_identical_results(session, tmp_path):
    path = save(session, tmp_path)
    first = EditorSession()
    first.open_project(path)
    second = EditorSession()
    second.open_project(path)
    assert project_to_dict(first.project) == project_to_dict(second.project)
    assert fingerprint(first.run_heatmap()) == fingerprint(second.run_heatmap())


# ---------------------------------------------------------------------------
# EditorSession: guardar / abrir / nuevo / dirty state (test 16 del spec)
# ---------------------------------------------------------------------------

def test_save_without_path_raises(tmp_path):
    s = EditorSession()
    assert s.project_path is None
    with pytest.raises(ValueError, match="Guardar como"):
        s.save_project()


def test_save_sets_path_and_clears_dirty(session, tmp_path):
    assert session.dirty is True  # fixture mutó el proyecto
    path = save(session, tmp_path)
    assert session.dirty is False
    assert session.project_path == path


def test_dirty_on_mutations_not_on_visual_actions():
    s = EditorSession()
    assert s.dirty is False
    s.select(None, None)  # selección: no marca
    assert s.dirty is False
    ap = s.add_access_point(Point2D(1, 1))
    assert s.dirty is True
    s.mark_saved()
    s.set_heatmap_ap(ap.id)  # selector visual: no marca
    assert s.dirty is False
    s.set_heatmap_enabled(False)
    assert s.dirty is False
    s.set_heatmap_enabled(True)
    assert s.dirty is False
    s.move_ap(ap.id, Point2D(2, 2))
    assert s.dirty is True
    s.mark_saved()
    s.run_simulation()  # simulación: no se persiste, no marca
    assert s.dirty is False


def test_dirty_on_all_persistable_changes():
    s = EditorSession()
    for action in (
        lambda: s.set_floor_dimensions(14, 9),
        lambda: s.set_grid_resolution(1.0),
        lambda: s.set_band("band_5"),
        lambda: s.add_wall(Point2D(0, 0), Point2D(4, 0)),
        lambda: s.add_access_point(Point2D(2, 2)),
        lambda: s.add_client(Point2D(3, 3)),
    ):
        s.mark_saved()
        assert s.dirty is False
        action()
        assert s.dirty is True
    s.mark_saved()
    s.set_wall_material("WALL-001", "brick")
    assert s.dirty is True
    s.mark_saved()
    s.set_wall_thickness("WALL-001", 0.3)
    assert s.dirty is True
    s.mark_saved()
    s.delete_selection()
    assert s.dirty is True


def test_new_project_resets_document(session, tmp_path):
    save(session, tmp_path)
    assert session.project_path is not None
    session.new_project()
    assert session.project_path is None
    assert session.dirty is False
    assert session.floor_width_m == pytest.approx(12.0)
    assert session.floor_height_m == pytest.approx(8.0)
    assert session.project.access_points == []
    assert session.heatmap_ap_id == HEATMAP_ALL_APS
    assert session.last_heatmap is None


def test_open_resets_transient_state(session, tmp_path):
    session.set_band("band_5")
    session.set_heatmap_ap("AP-002")
    path = save(session, tmp_path)
    session.run_heatmap()

    reopened = EditorSession()
    reopened.set_band("band_6")
    reopened.select(None, None)
    reopened.open_project(path)
    assert reopened.band_id == "band_5"  # configuración persistida
    assert reopened.heatmap_ap_id == HEATMAP_ALL_APS  # estado visual no persistido
    assert reopened.tool.value == "select"
    assert reopened.selection is None
    assert reopened.last_heatmap is None
    assert reopened.heatmap_dirty is True
    assert reopened.dirty is False


def test_opened_project_full_workflow(session, tmp_path):
    """Flujo de aceptación: guardar → abrir → editar → simular → guardar."""
    path = save(session, tmp_path, "flujo.json")
    reopened = EditorSession()
    reopened.open_project(path)

    new_ap = reopened.add_access_point(Point2D(15.0, 12.0))
    assert new_ap.id == "AP-003"
    assert reopened.dirty is True
    reopened.set_band("band_5")
    result = reopened.run_heatmap()
    assert result.stats["source_results"] == 3
    reopened.save_project()
    assert reopened.dirty is False

    again = EditorSession()
    again.open_project(path)
    assert [ap.id for ap in again.project.access_points] == [
        "AP-001",
        "AP-002",
        "AP-003",
    ]
    assert again.band_id == "band_5"


def test_save_as_changes_associated_path(session, tmp_path):
    first = save(session, tmp_path, "uno.json")
    second = session.save_project_as(str(tmp_path / "dos.json"))
    assert second != first
    assert session.project_path == second
    assert session.dirty is False
    assert (tmp_path / "uno.json").exists()
    assert (tmp_path / "dos.json").exists()


def test_save_is_atomic_no_temp_leftovers(session, tmp_path):
    path = save(session, tmp_path, "atomico.json")
    assert list(tmp_path.glob("*.tmp")) == []
    # Sobrescribir una ruta existente también es atómico.
    session.mark_dirty()
    session.save_project()
    assert list(tmp_path.glob("*.tmp")) == []
    loaded, _ = load_project(path)
    assert loaded.name == session.project.name


def test_editor_state_defaults_for_documents_without_editor(tmp_path):
    s = EditorSession()
    document = document_to_dict(s.project, s.editor_state())
    document.pop("editor")
    path = write_document(tmp_path, document)
    project, state = load_project(path)
    assert state.band_id == "band_2_4"
    assert state.grid_resolution_m == pytest.approx(0.5)
    assert project.name == s.project.name


def test_editor_state_default_dataclass():
    state = EditorState()
    assert state.band_id == "band_2_4"
    assert state.grid_resolution_m == pytest.approx(0.5)
