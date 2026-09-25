"""Fase 14.2: configuración de un AP desde el editor (2.4 ↔ 5 GHz).

Cierra el flujo «seleccionar AP → configurar → aplicar → simular»
reutilizando la validación existente de F10
(``core.channel.validate_channel_config``) y el modelo ya existente
(``AccessPoint`` + ``RadioConfiguration``). No hay modelo nuevo ni
segunda tabla de canales: los catálogos salen de
``core.channel.channel_numbers_for_frequency`` y de
``core.radio.allowed_channel_widths_mhz``.

Las pruebas son de comportamiento real sobre ``EditorSession`` (sin
abrir Tkinter); la única comprobación sobre la UI verifica el cableado
de los manejadores en ``ui/panels/properties.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.channel import channel_numbers_for_frequency
from core.geometry import Point2D
from core.radio import WIFI_STANDARDS, allowed_channel_widths_mhz
from tests.factories import make_session
from ui.session import EditorSession

PANEL = Path(__file__).resolve().parents[1] / "ui" / "panels" / "properties.py"
APP = Path(__file__).resolve().parents[1] / "ui" / "app.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ap_session():
    """Sesión 10×10 con un solo AP (sin banda explícita aún)."""
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    ap = session.add_access_point(Point2D(2.0, 5.0))
    session.set_grid_resolution(2.0)
    return session, ap


def _ap(session, ap_id: str):
    return next(a for a in session.project.access_points if a.id == ap_id)


def _steps(session) -> int:
    return len(session._undo_stack)


# ---------------------------------------------------------------------------
# 1–4 / 6. Cambio de banda y catálogos derivados
# ---------------------------------------------------------------------------

def test_change_band_24_to_5_updates_channel_catalog():
    session, ap = _ap_session()
    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=20)
    assert _ap(session, ap.id).band_id == "band_2_4"

    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=80)

    configured = _ap(session, ap.id)
    assert configured.band_id == "band_5"
    assert configured.channel == 36
    assert configured.radio.channel_width_mhz == 80
    # El canal elegido pertenece al catálogo de la banda nueva.
    assert configured.channel in channel_numbers_for_frequency(5180.0)
    assert configured.channel not in channel_numbers_for_frequency(2437.0)


def test_change_band_5_to_24_updates_channel_catalog():
    session, ap = _ap_session()
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=40)

    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=20)

    configured = _ap(session, ap.id)
    assert configured.band_id == "band_2_4"
    assert configured.channel == 6
    assert configured.channel in channel_numbers_for_frequency(2437.0)
    # 80 MHz no existe en 2.4 GHz: el ancho ofrecido por la UI es (20, 40).
    assert allowed_channel_widths_mhz(2437.0) == (20, 40)


def test_channel_of_another_band_is_rejected():
    session, ap = _ap_session()
    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=20)
    before = _steps(session)

    # Canal 6 (2.4 GHz) contra la banda 5 GHz ⇒ inválido.
    with pytest.raises(ValueError):
        session.set_ap_rf_config(ap.id, band_id="band_5", channel=6, width_mhz=20)

    configured = _ap(session, ap.id)
    assert configured.band_id == "band_2_4"
    assert configured.channel == 6
    assert _steps(session) == before  # nada se apiló


def test_width_not_allowed_for_band_is_rejected():
    session, ap = _ap_session()
    before = _steps(session)
    with pytest.raises(ValueError):
        session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=80)
    with pytest.raises(ValueError):
        session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=30)
    assert _ap(session, ap.id).band_id is None
    assert _steps(session) == before  # ninguna entrada de historial


def test_unknown_band_is_rejected():
    session, ap = _ap_session()
    before = _steps(session)
    with pytest.raises(KeyError):
        session.set_ap_rf_config(ap.id, band_id="band_99", channel=6, width_mhz=20)
    assert _steps(session) == before


# ---------------------------------------------------------------------------
# 7–9. Aplicar / cancelar / UNA entrada de undo
# ---------------------------------------------------------------------------

def test_apply_all_fields_creates_a_single_undo_entry():
    session, ap = _ap_session()
    before = _steps(session)

    session.set_ap_rf_config(
        ap.id,
        band_id="band_5",
        channel=44,
        width_mhz=80,
        p_tx_dbm=17.0,
        wifi_standard="802.11ac",
    )

    assert _steps(session) == before + 1  # UNA entrada por «Aplicar»
    configured = _ap(session, ap.id)
    assert (configured.band_id, configured.channel) == ("band_5", 44)
    assert configured.radio.channel_width_mhz == 80
    assert configured.radio.p_tx_dbm == pytest.approx(17.0)
    assert configured.radio.wifi_standard == "802.11ac"


def test_undo_restores_the_whole_ap_configuration():
    session, ap = _ap_session()
    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=1, width_mhz=40)
    original = _ap(session, ap.id)

    session.set_ap_rf_config(
        ap.id,
        band_id="band_5",
        channel=36,
        width_mhz=80,
        p_tx_dbm=10.0,
        wifi_standard="802.11n",
    )
    session.undo()

    restored = _ap(session, ap.id)
    assert (restored.band_id, restored.channel) == (original.band_id, original.channel)
    assert restored.radio.channel_width_mhz == original.radio.channel_width_mhz
    assert restored.radio.p_tx_dbm == original.radio.p_tx_dbm
    assert restored.radio.wifi_standard == original.radio.wifi_standard


def test_no_real_change_keeps_model_and_dirty_untouched():
    """Decisión BU: aplicar lo mismo no marca dirty ni invalida."""
    session, ap = _ap_session()
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=80)
    session.dirty = False
    session.heatmap_dirty = False

    session.set_ap_rf_config(
        ap.id, band_id="band_5", channel=36, width_mhz=80, p_tx_dbm=20.0
    )

    assert session.dirty is False
    assert session.heatmap_dirty is False


def test_panel_does_not_apply_when_the_form_is_unchanged():
    """«Aplicar» sin cambios no escribe en la sesión (sin undo fantasma)."""
    from ui.panels.properties import ap_config_unchanged

    session, ap = _ap_session()
    session.set_ap_rf_config(
        ap.id,
        band_id="band_5",
        channel=36,
        width_mhz=80,
        p_tx_dbm=17.0,
        wifi_standard="802.11ac",
    )
    current = _ap(session, ap.id)
    before = _steps(session)

    assert (
        ap_config_unchanged(
            current,
            band_id="band_5",
            channel=36,
            width_mhz=80,
            p_tx_dbm=17.0,
            wifi_standard="802.11ac",
        )
        is True
    )
    assert _steps(session) == before  # la lectura no toca el historial

    assert (
        ap_config_unchanged(
            current,
            band_id="band_5",
            channel=40,
            width_mhz=80,
            p_tx_dbm=17.0,
            wifi_standard="802.11ac",
        )
        is False
    )
    assert (
        ap_config_unchanged(
            current,
            band_id="band_5",
            channel=36,
            width_mhz=40,
            p_tx_dbm=17.0,
            wifi_standard="802.11ac",
        )
        is False
    )
    assert (
        ap_config_unchanged(
            current,
            band_id="band_5",
            channel=36,
            width_mhz=80,
            p_tx_dbm=10.0,
            wifi_standard="802.11ac",
        )
        is False
    )
    assert (
        ap_config_unchanged(
            current,
            band_id="band_5",
            channel=36,
            width_mhz=80,
            p_tx_dbm=17.0,
            wifi_standard="802.11ax",
        )
        is False
    )


def test_reset_does_not_touch_the_model():
    """«Restablecer» (cancelar) solo relee: ninguna mutación, ningún undo."""
    session, ap = _ap_session()
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    before = (
        _steps(session),
        session.dirty,
        _ap(session, ap.id).channel,
    )

    # Releer los controles desde el modelo no cambia el modelo.
    current = _ap(session, ap.id)
    assert (current.band_id, current.channel) == ("band_5", 36)

    assert before == (
        _steps(session),
        session.dirty,
        _ap(session, ap.id).channel,
    )

    # Y el manejador de la UI no escribe en la sesión.
    source = PANEL.read_text(encoding="utf-8")
    reset_block = source.split("def _ap_reset(")[1].split("\n    def ")[0]
    assert "_ap_load_controls" in reset_block
    for banned in ("set_ap_rf_config", "mark_dirty", "set_band("):
        assert banned not in reset_block


# ---------------------------------------------------------------------------
# 10–11. Configuración inválida no modifica / válida sí modifica
# ---------------------------------------------------------------------------

def test_invalid_p_tx_leaves_model_unchanged():
    session, ap = _ap_session()
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    before = _steps(session)

    with pytest.raises(ValueError):
        session.set_ap_rf_config(
            ap.id, band_id="band_5", channel=36, width_mhz=20, p_tx_dbm=float("nan")
        )
    with pytest.raises(ValueError):
        session.set_ap_rf_config(
            ap.id, band_id="band_5", channel=36, width_mhz=20, p_tx_dbm="alta"
        )

    assert _steps(session) == before
    assert _ap(session, ap.id).radio.p_tx_dbm == pytest.approx(20.0)


def test_invalid_wifi_standard_leaves_model_unchanged():
    session, ap = _ap_session()
    before = _steps(session)

    with pytest.raises(ValueError):
        session.set_ap_rf_config(
            ap.id,
            band_id="band_2_4",
            channel=6,
            width_mhz=20,
            wifi_standard="802.11g",
        )

    assert _steps(session) == before
    assert _ap(session, ap.id).radio.wifi_standard == "802.11ax"
    assert _ap(session, ap.id).band_id is None  # nada se aplicó


def test_valid_change_marks_dirty_and_invalidates_heatmap():
    session, ap = _ap_session()
    session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=20)
    session.heatmap_dirty = False
    session.dirty = False

    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=40)

    assert session.dirty is True
    assert session.heatmap_dirty is True


def test_p_tx_changes_the_rf_results():
    """La potencia TX ya existente sí entra en el link budget (F1)."""
    session, ap = _ap_session()
    session.set_ap_rf_config(
        ap.id, band_id="band_2_4", channel=6, width_mhz=20, p_tx_dbm=10.0
    )
    weak = session.run_heatmap()

    session.set_ap_rf_config(
        ap.id, band_id="band_2_4", channel=6, width_mhz=20, p_tx_dbm=20.0
    )
    strong = session.run_heatmap()

    assert strong.stats["rx_avg_dbm"] > weak.stats["rx_avg_dbm"]


# ---------------------------------------------------------------------------
# 12. Pipeline después de modificar el AP
# ---------------------------------------------------------------------------

def test_pipeline_after_band_change_uses_the_new_band():
    session, ap = _ap_session()
    session.set_grid_resolution(1.0)
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=40)

    result = session.run_heatmap("band_2_4")  # banda activa sin cambiar

    assert result.band_id == "band_5"
    assert result.stats["point_count"] > 0
    assert math.isfinite(result.stats["rx_avg_dbm"])


def test_single_ap_selector_avoids_mixed_band_error():
    """Escape hatch: ver un AP concreto aunque haya bandas mixtas."""
    session, ap1 = _ap_session()
    ap2 = session.add_access_point(Point2D(8.0, 5.0))
    session.set_grid_resolution(2.0)
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_2_4", channel=6, width_mhz=20)

    # Ambas bandas a la vez ⇒ el combinado F5 sigue rechazando (F10 intacto).
    with pytest.raises(ValueError):
        session.run_heatmap()

    # Seleccionando un AP concreto sí se puede ver su heatmap.
    session.set_heatmap_ap(ap1.id)
    result = session.run_heatmap()
    assert result.band_id == "band_5"


# ---------------------------------------------------------------------------
# 13. Persistencia round-trip (schema v1, sin claves nuevas)
# ---------------------------------------------------------------------------

def test_persistence_round_trip_after_ap_config(tmp_path):
    session, ap = _ap_session()
    session.set_ap_rf_config(
        ap.id,
        band_id="band_5",
        channel=48,
        width_mhz=80,
        p_tx_dbm=16.0,
        wifi_standard="802.11ac",
    )
    path = str(tmp_path / "ap.json")
    session.save_project(path)

    loaded = EditorSession()
    loaded.open_project(path)

    restored = _ap(loaded, ap.id)
    assert restored.band_id == "band_5"
    assert restored.channel == 48
    assert restored.radio.channel_width_mhz == 80
    assert restored.radio.p_tx_dbm == pytest.approx(16.0)
    assert restored.radio.wifi_standard == "802.11ac"
    # El pipeline sigue funcionando tras guardar/cargar.
    loaded.set_grid_resolution(2.0)
    assert loaded.run_heatmap().stats["point_count"] > 0


# ---------------------------------------------------------------------------
# Cableado de la UI (sin abrir Tkinter)
# ---------------------------------------------------------------------------

def test_panel_applies_the_config_in_one_place():
    source = PANEL.read_text(encoding="utf-8")
    # UNA sola escritura en el modelo: todo el bloque en una entrada de undo.
    assert source.count("set_ap_rf_config(") == 1
    assert "def _ap_apply(" in source
    assert "def _ap_reset(" in source  # cancelar/restablecer


def test_panel_uses_existing_catalogs_only():
    source = PANEL.read_text(encoding="utf-8")
    assert "channel_numbers_for_frequency" in source
    assert "allowed_channel_widths_mhz" in source
    # Sin tabla de canales hardcodeada dentro del diálogo.
    for banned in ("CHANNELS =", "CANALES =", "[1, 6, 11]", "[36, 40, 44"):
        assert banned not in source


def test_panel_syncs_active_band_and_app_explains_mixed_bands():
    panel = PANEL.read_text(encoding="utf-8")
    assert "set_band(" in panel  # la banda activa sigue a la del AP
    app = APP.read_text(encoding="utf-8")
    assert "bandas distintas" in app  # error traducido a una acción clara


def test_panel_offers_the_existing_wifi_standards():
    source = PANEL.read_text(encoding="utf-8")
    # El combo de estándar se llena con el catálogo único de core/radio.py.
    assert "values=list(WIFI_STANDARDS)" in source
    assert "from core.radio import" in source
    # Y el modelo sigue acotando el catálogo (F7).
    assert WIFI_STANDARDS == ("802.11n", "802.11ac", "802.11ax", "802.11be")
