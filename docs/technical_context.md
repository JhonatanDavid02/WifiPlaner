# CONTEXTO TÉCNICO COMPLETO — PROYECTO DE REDES

> **Documento de fuente de verdad técnica para el redactor del documento final (Word).**
> Fecha de corte de esta fotografía: **27 de septiembre de 2026**.
> Origen: inspección directa del código, del historial de git y de la suite de pruebas ejecutada hoy.
> **Nada de este documento está inventado.** Todo lo no verificable se marca explícitamente.

### Leyenda de marcadores (usarlos también en el documento final)

| Marcador | Significado |
|---|---|
| `[IMPLEMENTADO]` | Existe en el código y se pudo ejecutar/observar. |
| `[IMPLEMENTADO Y PROBADO]` | Además tiene pruebas automatizadas que lo verifican. |
| `[IMPLEMENTACIÓN PARCIAL]` | Existe pero con alcance limitado o incompleto. |
| `[PLANEADO / NO IMPLEMENTADO]` | Diseñado o previsto en la documentación, pero sin código que lo haga. |
| `[OBSOLETO / REEMPLAZADO]` | Existió y fue sustituido por otra solución vigente. |
| `[NO DETERMINADO]` | No puede establecerse con la evidencia disponible. |
| `[NO VERIFICADO]` | Existe en el código pero no se pudo comprobar en ejecución. |
| `[INFERIDO]` | Deducción razonable a partir de la evidencia, no afirmación directa. |

### Clasificación de alcance que debe usarse al redactar
- **A) Implementado realmente** — código + verificación.
- **B) Implementado parcialmente** — parcial o inaccesible desde la interfaz.
- **C) Planeado** — mencionado en diseño/docs sin implementación.
- **D) Inferido** — deducido de la evidencia.
- **E) No determinado** — sin evidencia suficiente.

---

## 1. Identidad del proyecto

- **Nombre del producto:** **Wi‑Fi Planner V1** (aparece como tal en `wifi_planner/main.py`, `docs/architecture.md` y `config/default_config.yaml`).
- **Nombre del repositorio / directorio:** `ProyectoRedes` (raíz del proyecto académico de redes).
- **Lenguaje:** Python. **Entorno de ejecución verificado hoy:** CPython **3.14.7**.
- **Qué es:** aplicación de escritorio para **diseño y simulación predictiva de cobertura Wi‑Fi** sobre planos 2D en metros: el usuario dibuja la planta (paredes, huecos, mobiliario), coloca puntos de acceso (AP) y clientes, configura parámetros de radio y obtiene mapas de cobertura (heatmaps) con métricas RF (RSSI, SNR, Interferencia, SINR).
- **Naturaleza del cálculo:** estimación predictiva con modelo propio (FSPL + presupuesto de enlace + atenuación por materiales). **No es una simulación electromagnética** (así se declara en `docs/architecture.md` y `docs/formulas.md`). Ver §15.
- **Usuario objetivo:** estudiante/ingeniero de redes que debe planificar la ubicación y configuración de APs antes de instalarlos. `[INFERIDO del alcance funcional; el repo no contiene un análisis de mercado]`.
- **Origen de los datos de referencia (golden data):** `wifi_planner/tests/fixtures/golden_data.py` declara que los valores de validación provienen de un **DOCX/XLSX legacy del "proyecto CUN"** (Tablas 2 y 3 del documento). Ver §12 y §13 (decisión A).
- **Legado previo en la raíz del repo** (no forma parte de la aplicación, es la base histórica): `calculo_wifi_biblioteca.py` (v1), `CalculoWifi2.py` (v2), `CODIGO(Interactivo).py` (v3), `CalculadoraWLAN_Visual.py` (v4). `[IMPLEMENTADO como scripts congelados]`. Las discrepancias entre ellos están auditadas en `docs/decisions.md` ("Discrepancias encontradas", 10 ítems).
- **Estado del repositorio git:** rama `master`, **27 commits**, último commit `3f1c751` ("phase 15: direct manipulation and per-ap coverage overlay", 2026‑09‑25). **Existe trabajo posterior SIN commitear** en el árbol de trabajo (detallado en §11 y §16): caché de cobertura por AP, estados de señal de clientes, desplazamiento del plano (pan), arreglo de estilos de la UI y dos documentos de usuario en `Documentos/`.
- **Documentos de usuario existentes** (en `Documentos/`, sin commitear): `manual_de_uso.md` (referencia técnica de uso) y `como_presentar_el_programa.md` (guía de demostración). En `wifi_planner/docs/` (commiteados): `architecture.md`, `decisions.md`, `formulas.md`.

---

## 2. Objetivo

### Objetivo general
Proporcionar una herramienta visual que permita **modelar una planta baja, colocar APs y predecir la cobertura Wi‑Fi resultante**, de modo que las decisiones de despliegue se tomen antes de la instalación física.

### Objetivos específicos verificables (cada uno está implementado)
1. Modelar geometría en **metros** (paredes con material y espesor, aperturas, espacios, obstáculos de mobiliario) — F2/F8/F9.
2. Calcular RSSI/SOM/SNR por punto con fórmulas RF canónicas y configurables — F1/F2/F7.
3. Visualizar la cobertura como **heatmap** de una o cuatro métricas sobre la planta — F4/F7/F11/F12.
4. Combinar la cobertura de **múltiples APs** (mejor RSSI por punto) — F5.
5. Modelar **interferencia espectral** entre APs y derivar **SINR** — F11/F12.
6. **Optimizar la asignación de canales** con un coste explícito basado en SINR — F13.
7. Editar interactivamente (arrastrar, deshacer/rehacer, medir, zoom/pan) — F14/F14.1/F15.
8. **Persistir** proyectos en JSON con validación estricta de entrada — F6/F6.1.
9. Mostrar el **estado de señal de cada cliente** en su posición exacta — trabajo 15.2 (§11).

### Lo que NO es el objetivo (declarado en el propio proyecto)
- No sustituye mediciones en sitio (`docs/formulas.md`, disclaimer del heatmap).
- No modela MAC/CSMA/CCA, roaming, throughput ni normativa por país (`docs/decisions.md`, decisiones CD/CO: "fuera de alcance").

---

## 3. Problema

**Problema que resuelve:** planificar una red Wi‑Fi interior a mano es iterativo y caro: la calidad de recepción depende de la distancia, la frecuencia, la potencia de transmisión y las paredes/mobiliario que el trayecto AP→usuario atraviesa. Sin una herramienta predictiva, cada corrección requiere instalar o medir.

**Solución aportada:** un modelo de propagación determinista que, dado un plano y una configuración de radio, estima la potencia recibida (RSSI), el margen operativo (SOM), la relación señal/ruido (SNR), la interferencia entre APs y el SINR en cada punto del plano, y lo representa visualmente como mapa de color.

**Casos de uso reales soportados hoy:**
- Comparar ubicaciones de APs sobre una planta.
- Detectar zonas sin cobertura útil (debajo del umbral de calidad).
- Identificar interferencia entre APs por solapamiento de canales.
- Proponer una reasignación de canales que mejore el SINR medio.
- Comprobar la señal que recibe un punto concreto (cliente) en una posición exacta.

---

## 4. Tecnologías

| Tecnología | Versión verificada | Uso en el proyecto |
|---|---|---|
| Python | 3.14.7 (intérprete usado para ejecutar la suite) | Lenguaje único de todo el proyecto (`requirements.txt`, `main.py`) |
| Tkinter | stdlib de Python (versión [NO DETERMINADA]) | UI de escritorio: ventana, canvas, paneles, diálogos (`ui/`) |
| Pillow (PIL) | 12.3.0 instalada; `requirements.txt` exige `Pillow>=10.0` | Generación de la imagen del heatmap y de la capa de cobertura (`ui/coverage_renderer.py`, `ui/app.py`) |
| PyYAML | 6.0.3 instalada; exige `PyYAML>=6.0` | Carga de `config/default_config.yaml` (`config/__init__.py`) |
| pytest | 9.1.1 instalada; exige `pytest>=8.0` | Suite de 955 pruebas (`wifi_planner/pytest.ini`) |
| JSON (stdlib `json`) | — | Formato de proyecto persistido (`persistence/json_project_repository.py`, `schema_version = 1`) |
| math / dataclasses / itertools | stdlib | Motor de cálculo (`engine/`), modelo de dominio (`core/`) |
| Git | — | Control de versiones (27 commits, mensajes en inglés con numeración de fases) |

**Reglas de dependencias (verificadas en código y en `docs/architecture.md`):**
- `core/` y `engine/` **nunca** importan `ui/`, ni `tkinter`, ni `PIL`.
- `engine/` son funciones puras, deterministas, sin caché ni hilos (decisiones CE).
- `persistence/` importa `core/` (y `engine` solo para límites de grid); **nunca** UI.
- `ui/` puede importar `core/` y `engine/`; **no contiene fórmulas RF**.

**Formatos de archivo:**
- Proyecto: `.json` con `schema_version: 1` (estructura en §5 y §7).
- Configuración: `wifi_planner/config/default_config.yaml`.
- No hay base de datos, ni red, ni servicios externos. `[IMPLEMENTADO]` (ausencia verificada).

---

## 5. Arquitectura

### 5.1 Capas

```
ui/            Presentación (Tkinter + Pillow). Consume resultados; nunca calcula RF.
persistence/   Proyecto ⇄ JSON. Entrada no confiable. Escritura atómica.
engine/        Motor RF puro: FSPL, link budget, trazado, grid, combinación, interferencia, SINR, optimización.
core/          Modelo de dominio en metros: geometría, materiales, radios, bandas, canales, APs, clientes, proyecto, resultados.
config/        Configuración centralizada en YAML. Sin números mágicos en el código.
tests/         pytest, deterministas, sin abrir ventanas (salvo tests de UI con Tk real).
```

### 5.2 Flujo de datos (verificado en `ui/session.py::run_heatmap` y `docs/architecture.md`)

1. La UI construye/lee un `Project` (geometría en metros).
2. `EditorSession.run_heatmap()` crea un `CoverageGrid` (`build_coverage_grid`) y llama a `engine.simulator.simulate_coverage(...)` por cada AP del ámbito seleccionado.
3. Por cada punto del grid: `trace_walls` (paredes + aperturas + obstáculos) → `link_budget` → SOM → SNR → SINR.
4. Si hay ≥2 resultados y canales configurados: `interference.annotate_interference` (anota I por AP) → `sinr.annotate_sinr` (anota SINR) → `combine.combine_results` (**mayor RSSI por punto**; nunca promedia).
5. `ui.coverage_renderer.build_heatmap_image` convierte el `SimulationResult` en imagen Pillow (píxeles solo aquí, vía `ui/viewport.py`).
6. `ui/editor_canvas` dibuja capas en orden: suelo/rejilla → heatmap → espacios → obstáculos → paredes/huecos → APs/clientes → leyenda.

### 5.3 Módulos importantes (formato requerido)

**ARCHIVO:** `wifi_planner/core/geometry.py`
**RESPONSABILIDAD:** primitivas geométricas en metros (`Point2D`, `Segment2D`, `Rect`).
**ENTRADAS:** coordenadas en metros.
**SALIDAS:** distancias, intersecciones, `Rect.edge_segments` (usado por obstáculos).
**DEPENDENCIAS:** stdlib.
**FUNCIONES IMPORTANTES:** `Point2D.distance_to`, `Segment2D`, `Rect.contains`, `Rect.edge_segments`.

**ARCHIVO:** `wifi_planner/core/material.py`
**RESPONSABILIDAD:** catálogo de materiales y su atenuación de referencia por banda.
**ENTRADAS:** id de banda.
**SALIDAS:** atenuación en dB; **`MaterialAttenuationError`** (subclase de `KeyError`) si la banda no está configurada (p. ej. 6 GHz).
**DEPENDENCIAS:** stdlib.
**FUNCIONES IMPORTANTES:** `Material.attenuation_for(band_id)`, `Material.has_band`, `default_materials()`. `thickness_default_m` (espesor de referencia).

**ARCHIVO:** `wifi_planner/core/radio.py`
**RESPONSABILIDAD:** parámetros de radio (`RadioConfiguration`) y reglas de familia de frecuencia.
**SALIDAS:** validación de `noise_floor_dbm` en `[-200, 0]`; `allowed_channel_widths_mhz(f)`; `wifi_generation(standard, f)`.
**FUNCIONES IMPORTANTES:** `RadioConfiguration` (campos en §9), `_24GHZ_FAMILY_MAX_MHZ = 3000.0`, `_6GHZ_MIN_MHZ = 5925.0` (fronteras de familia, fuente única).

**ARCHIVO:** `wifi_planner/core/band.py`
**RESPONSABILIDAD:** `FrequencyBand` (2.4/5/6 GHz) con `frequency_mhz` de referencia (2437 / 5180 / 6135 MHz).
**FUNCIONES IMPORTANTES:** `DEFAULT_BANDS`.

**ARCHIVO:** `wifi_planner/core/channel.py`
**RESPONSABILIDAD:** catálogo de canales Wi‑Fi (número lógico → frecuencia central derivada). **Fuente única**: ningún otro archivo tabula frecuencias (decisión BQ).
**SALIDAS:** `WifiChannel(number, center_frequency_mhz)`; validación del triple (banda, canal, ancho).
**FUNCIONES IMPORTANTES:** `channels_for_frequency`, `channel_numbers_for_frequency`, `channel_for_band`, `default_channel`, `validate_channel_config`; `MAX_CHANNEL_NUMBER = 233`.
**CATÁLOGOS (fórmulas, verificadas en el código):**
- 2.4 GHz: `f_c(n) = 2412 + 5·(n−1)` MHz para n = 1…13; n = 14 → 2484 MHz.
- 5 GHz: `36…64 → 5180 + 20·((n−36)/4)`; `100…144 → 5500 + 20·((n−100)/4)`; `149…161 → 5745 + 20·((n−149)/4)`; `165 → 5825`.
- 6 GHz: `f_c(n) = 5950 + 5·n` MHz para n = 1, 5, 9, …, 233.
- Familia de frecuencia: `f < 3000` → 2.4 GHz; `3000 ≤ f < 5925` → 5 GHz; `f ≥ 5925` → 6 GHz.

**ARCHIVO:** `wifi_planner/core/wall.py`
**RESPONSABILIDAD:** `Wall` (segmento + material + espesor + `blocks_signal`) y `Opening` (hueco muro‑relativo con offsets métricos).
**FUNCIONES IMPORTANTES:** `wall_point_at_offset`, `opening_segment`, `group_openings_by_wall` (orden canónico `(start, id)`), `OPENING_KINDS = {door, window, pass_through}`.
**CONSTANTES:** `MIN_OPENING_LENGTH_M = 0.01`, `DEFAULT_OPENING_LENGTH_M = {"door": 0.9, "window": 1.2, "pass_through": 1.0}`, `MAX_OPENING_ATTENUATION_DB = 200`.

**ARCHIVO:** `wifi_planner/core/obstacle.py`
**RESPONSABILIDAD:** obstáculo de mobiliario con footprint `Rect` (alineado a ejes, sin altura ni giro).
**FUNCIONES IMPORTANTES:** `Obstacle` (frozen dataclass), `OBSTACLE_KINDS = {furniture, equipment, column, other}`, `MIN/MAX_OBSTACLE_SIZE_M`, `DEFAULT_OBSTACLE_MATERIAL_ID = "wood"`.

**ARCHIVO:** `wifi_planner/core/space.py`
**RESPONSABILIDAD:** `Space` (zona organizativa, **sin efecto RF**, decisión BH) y `Floor` (`width_m`/`height_m` opcionales, `walls`, `openings`, `obstacles`, `spaces`).

**ARCHIVO:** `wifi_planner/core/access_point.py` / `core/client.py`
**RESPONSABILIDAD:** AP (posición + `radio` + `band_id` + `channel`) y cliente (posición + `sensitivity_dbm`).
**INVARIANTE (decisión BS):** un `channel` explícito exige `band_id`; canal ∈ [1, 233]. Un AP = un radio = una banda (sin multi‑radio).

**ARCHIVO:** `wifi_planner/core/project.py`
**RESPONSABILIDAD:** contenedor raíz `Project` (name, units, bands, materials, radio, thresholds, access_points, clients, floors, metadata) y `CoverageThresholds` (umbrales).
**CONSTANTES:** `DEFAULT_SNR_TARGET_DB = 25.0`, `DEFAULT_SINR_TARGET_DB = 25.0`, rangos `[-20, 60]` dB.

**ARCHIVO:** `wifi_planner/core/result.py`
**RESPONSABILIDAD:** `LinkEvaluation` (resultado por punto: distancias, pérdidas, `rx_power_dbm`, `som_db`, `snr_db`, `sinr_db`, calidad, veredicto + campos de interferencia), `SimulationResult`, `QualityClass`, `Verdict`.
**NOTA:** los campos de interferencia (`interference_evaluated`, `interference_dbm`, `interferer_count`, `dominant_interferer_ap_id`) y de SINR (`sinr_db`, `sinr_meets_target`) son **información paralela con default**: no alteran RSSI/SOM/SNR/calidad/veredicto (decisiones BX/CF).

**ARCHIVO:** `wifi_planner/engine/propagation.py`
**RESPONSABILIDAD:** FSPL y longitud de onda.
**FUNCIONES:** `wavelength_m(frequency_hz)`, `path_loss_fspl_db(distance_m, frequency_mhz)` (alias `fspl_db`). Constante `_FSPL_CONSTANT_DB = -27.55`, `SPEED_OF_LIGHT_M_S = 3e8`.

**ARCHIVO:** `wifi_planner/engine/link_budget.py`
**RESPONSABILIDAD:** presupuesto de enlace, SOM, SNR, evaluación atómica de un enlace.
**FUNCIONES:** `link_budget(...)`, `system_operating_margin`, `signal_to_noise_ratio`, `evaluate_link(...)` (devuelve `LinkEvaluation` completo incl. SINR sin interferencia). Constante `MIN_FSPL_DISTANCE_M = 0.1`.

**ARCHIVO:** `wifi_planner/engine/obstacles.py`
**RESPONSABILIDAD:** trazado de trayectoria contra paredes, aperturas y obstáculos (pérdidas acumuladas).
**FUNCIONES:** `wall_attenuation_db(wall, band_id)`, `obstacle_attenuation_db(obstacle, band_id)`, `trace_walls(source, target, walls, band_id, openings=(), obstacles=())`, `trace_obstacles(...)`. `MaterialAttenuationError` se propaga para bandas sin datos (6 GHz) en cruces sólidos.

**ARCHIVO:** `wifi_planner/engine/intersection.py`
**RESPONSABILIDAD:** intersección segmento–segmento con **cruce interior estricto** (los extremos no cuentan).
**FUNCIONES:** `segments_cross`, `segment_crossing_parameters` (parámetro `u` sobre la pared).

**ARCHIVO:** `wifi_planner/engine/coverage_grid.py`
**RESPONSABILIDAD:** malla regular de puntos en metros.
**LÍMITES:** `MIN_RESOLUTION_M = 0.05`, `MAX_GRID_POINTS = 100_000`.
**FUNCIONES:** `CoverageGrid.points()`, `point_count`.

**ARCHIVO:** `wifi_planner/engine/simulator.py`
**RESPONSABILIDAD:** simulación de cobertura de un AP sobre puntos o sobre el grid completo.
**FUNCIONES:** `simulate_coverage(project, access_point, frequency_band, sample_points=None, obstacle_materials_by_point=None, client=None, walls=None, openings=None, obstacles=None)`; `_compute_stats` (estadísticas incl. SNR y bloque SINR).

**ARCHIVO:** `wifi_planner/engine/combine.py`
**RESPONSABILIDAD:** combinación multi‑AP: **mejor RSSI por punto** (`_better`), empate → menor `access_point_id`. Rechaza bandas mixtas (contrato F5).
**FUNCIONES:** `combine_results(results)`.

**ARCHIVO:** `wifi_planner/engine/classifier.py`
**RESPONSABILIDAD:** clasificación y diagnósticos.
**FUNCIONES:** `classify_quality`, `classify_som`, `meets_rssi_target`, `meets_snr_target`, `meets_sinr_target`, `rf_diagnostic` (4 salidas), `sinr_diagnostic` (2 salidas).

**ARCHIVO:** `wifi_planner/engine/interference.py`
**RESPONSABILIDAD:** modelo espectral entre emisores (F11).
**FUNCIONES:** `occupied_interval_mhz`, `spectral_overlap`, `effective_interference_dbm`, `dbm_to_mw`/`mw_to_dbm`/`aggregate_dbm`, `emission_for_ap`, `annotate_interference`, `interference_summary`. Sin caché/hilos.

**ARCHIVO:** `wifi_planner/engine/sinr.py`
**RESPONSABILIDAD:** fórmula única de SINR (F12).
**FUNCIONES:** `signal_to_interference_noise_ratio`, `interference_plus_noise_dbm`, `annotate_sinr`, `sinr_stats_block`.

**ARCHIVO:** `wifi_planner/engine/channel_optimization.py`
**RESPONSABILIDAD:** propuesta de canales (F13) — **nunca aplica cambios**.
**FUNCIONES:** `optimize_channels`, `evaluate_channel_assignment`, `candidate_channels`; `OptimizationTarget`, `AssignmentEvaluation`, `OptimizationResult`; `EXHAUSTIVE_LIMIT = 64`.

**ARCHIVO:** `wifi_planner/persistence/json_project_repository.py`
**RESPONSABILIDAD:** `Project` ⇄ JSON (schema v1), validación de entrada no confiable, escritura atómica (`.tmp` + `fsync` + `os.replace`).
**FUNCIONES:** `save_project`, `load_project`, `project_to_dict`, `project_from_dict`, `ProjectFormatError`, `EditorState`.
**LÍMITES (verificados):** `SCHEMA_VERSION = 1`, `MAX_FILE_BYTES = 20 MB`, `MAX_FLOORS = 64`, `MAX_WALLS = 50 000`, `MAX_APS = MAX_CLIENTS = 10 000`, `MAX_SPACES = 5 000`, `MAX_OPENINGS = 10 000`, `MAX_OPENINGS_PER_WALL = 32`, `MAX_OBSTACLES = 5 000`, `MAX_DIMENSION_M = 10 000`, `MAX_ATTENUATION_DB = 200`.

**ARCHIVO:** `wifi_planner/ui/session.py` (2171 líneas — el módulo central de la aplicación)
**RESPONSABILIDAD:** `EditorSession`: estado editable del documento + operaciones (CRUD de geometría/APs/clientes, undo/redo, heatmap, métricas, interferencia/SINR, optimización de canales, persistencia, estados de cliente, caché de cobertura por AP). Todo testeable **sin Tk**.
**ENTRADAS:** eventos de la UI (posiciones en metros, valores de panel).
**SALIDAS:** `SimulationResult`, textos de panel, invalidaciones.
**FUNCIONES IMPORTANTES (líneas verificadas hoy):** `undoable` (150), `mark_dirty` (308), `undo`/`redo` (349/369), `begin_edit`/`commit_edit`/`cancel_edit` (410/428/454), `geometry_view` (614), `apply_rf_settings` (740), `resolve_band_for_ap` (798), `set_ap_rf_config` (816), `invalidate_heatmap` (893), `set_heatmap_metric` (931), `_interference_context_aps` (983), `optimize_channels` (1122), `apply_channel_assignment` (1198), `_ap_coverage_key` (1239), `selected_ap_coverage` (1278), `run_heatmap` (1326), `client_states` (1503), `client_state` (1528), `add_client` (1665), `move_client` (2027), `run_simulation` (2338).
**CONSTANTE:** `MAX_UNDO_STEPS = 50` (147).

**ARCHIVO:** `wifi_planner/ui/app.py` (1066 líneas)
**RESPONSABILIDAD:** ventana principal `WifiPlannerApp(tk.Tk)`: menús, teclado, debounce del heatmap, orquestación de capas.
**FUNCIONES IMPORTANTES:** `_build_menu` (292), `_on_band` (640), `_on_heatmap_toggle` (662), `_recolor_heatmap` (705), `_on_simulate` (894), `_update_status_coords` (920), `_schedule_heatmap` (1028), `_refresh_ap_coverage` (1058), `_run_heatmap_now` (1097).
**CONSTANTE:** `HEATMAP_DEBOUNCE_MS = 150` (31).

**ARCHIVO:** `wifi_planner/ui/editor_canvas.py` (956 líneas)
**RESPONSABILIDAD:** lienzo 2D: dibujo de capas, hit‑testing, herramientas de dibujo/edición, arrastres, zoom/pan, indicadores de cliente.
**FUNCIONES IMPORTANTES:** `clear_ap_coverage`/`draw_ap_coverage` (capa de cobertura del AP seleccionado), `_draw_client_signal` (indicador de estado del cliente), `_on_press` (880), `_on_motion` (774), `_on_drag` (1023), `_on_pan_press/_on_pan_motion/_on_pan_release` (757/760/771), `_on_release` (cierra el gesto de undo, 1025+).

**ARCHIVO:** `wifi_planner/ui/coverage_renderer.py` (427 líneas)
**RESPONSABILIDAD:** `SimulationResult` → imagen Pillow + leyenda + escalas de color.
**REGISTRO ÚNICO:** `HEATMAP_METRICS = ("rssi", "snr", "interference", "sinr")` (línea 83).
**FUNCIONES:** `build_heatmap_image` (317), `rssi_to_color` (125), `snr_to_color` (140), `interference_to_color` (159, **dirección invertida**), `sinr_to_color` (180), `legend_title` (201), `legend_rows` (214).

**ARCHIVO:** `wifi_planner/ui/viewport.py`
**RESPONSABILIDAD:** **único** conversor metros ⇄ píxeles (escala isotrópica). `world_width_m`/`world_height_m` obligatorios (sin tamaño implícito, decisión CQ).

**ARCHIVO:** `wifi_planner/ui/geometry_view.py`
**RESPONSABILIDAD:** instantánea congelada (`GeometryView`) del piso activo; el Canvas no recorre listas internas del documento (decisión CR).

**ARCHIVO:** `wifi_planner/ui/client_signal.py` (162 líneas, **sin commitear**)
**RESPONSABILIDAD:** estado RF del cliente en su posición exacta (5 niveles), reutilizando `engine.simulator.simulate_coverage` (sin fórmulas propias).
**FUNCIONES/CONSTANTES:** `BUENA_MIN_DBM = -55`, `FUERTE_MIN_DBM = -67`, `DEBIL_MIN_DBM = -75`, `INESTABLE_MIN_DBM = -85`; `state_for_rssi`, `ClientSignalState`, `evaluate_client_state`.

**ARCHIVO:** `wifi_planner/ui/theme.py`
**RESPONSABILIDAD:** paleta/estilos ttk + colores de estado de cliente (`CLIENT_STATE_COLOR`, añadido sin commitear).

**ARCHIVO:** `wifi_planner/ui/panels/toolbar.py` / `ui/panels/properties.py`
**RESPONSABILIDAD:** barra de herramientas y selectores (herramienta, banda, resolución, métrica, AP, heatmap, acciones) / panel de propiedades y resúmenes (selección, config RF del AP, objeto, interferencia/SINR, estado del cliente).

**ARCHIVO:** `wifi_planner/ui/dialogs/*`
**RESPONSABILIDAD:** `project_dialog.py` (dimensiones de proyecto nuevo), `rf_dialog.py` (configuración RF global), `channel_optimization_dialog.py` (propuesta de canales), `material_dialog.py` y `wall_dialog.py` (**stubs vacíos**, "reservados" según su docstring → `[PLANEADO / NO IMPLEMENTADO]`).

**ARCHIVO:** `wifi_planner/main.py`
**RESPONSABILIDAD:** punto de entrada (`python main.py` → `ui.run_app()`).

**ARCHIVO:** `wifi_planner/config/default_config.yaml` + `config/__init__.py`
**RESPONSABILIDAD:** configuración central (radio, umbrales, bandas, materiales) y su carga. Los defaults de `core/` son la fuente; el YAML los referencia.

---

## 6. Estructura del código

```
ProyectoRedes/
├── CalculadoraWLAN_Visual.py, CalculoWifi2.py,
│   calculo_wifi_biblioteca.py, CODIGO(Interactivo).py   ← legacy v1–v4 (congelado)
├── Documentos/                                          ← docs de usuario (sin commitear)
│   ├── manual_de_uso.md
│   ├── como_presentar_el_programa.md
│   └── CONTEXTO_TECNICO_COMPLETO.md   (este documento)
└── wifi_planner/
    ├── main.py
    ├── requirements.txt, pytest.ini
    ├── config/        default_config.yaml, __init__.py
    ├── core/          12 módulos (dominio)
    ├── engine/        11 módulos (motor RF)
    ├── persistence/   json_project_repository.py
    ├── ui/            app, session, editor_canvas, coverage_renderer,
    │                  viewport, geometry_view, client_signal, theme,
    │                  panels/ (toolbar, properties), dialogs/ (5)
    ├── docs/          architecture.md, decisions.md, formulas.md
    └── tests/         37 archivos de prueba + fixtures/ + factories.py
```

Tamaños aproximados (líneas): `ui/session.py` 2171 · `persistence/json_project_repository.py` 1169 · `ui/app.py` 1066 · `ui/panels/properties.py` 1056 · `ui/editor_canvas.py` 956 · `engine/channel_optimization.py` 486 · `engine/obstacles.py` 487 · `ui/coverage_renderer.py` 427 · `engine/interference.py` 413 · `tests/` ~12 500 en total.

---

## 7. Funcionalidades

Convención de la columna **Estado**: A = implementado realmente, B = parcial, C = planeado, E = no determinado (ver §0).

### 7.1 Editor / entorno
| Funcionalidad | Qué hace / cómo se usa | Módulo | Estado |
|---|---|---|---|
| Planta en metros con rejilla visual | `Archivo → Nuevo` pide dimensiones (diálogo `project_dialog.py`); el piso se dibuja con rejilla | `core/space.py`, `ui/viewport.py`, `ui/editor_canvas.py` | A `[IMPLEMENTADO Y PROBADO]` (`test_no_implicit_dimensions.py`) |
| Zoom / desplazamiento | Rueda y `Ver` menú; **pan con clic‑izquierdo en hueco o botón central** (cursor `fleur`) | `ui/viewport.py`, `ui/editor_canvas.py` (`_on_pan_*`, `_on_drag`) | A `[IMPLEMENTADO Y PROBADO]` (`test_viewport.py`, `test_left_drag_on_empty_space_pans_the_view`) |
| Snap a rejilla | Al editar geometría | `ui/editor_canvas.py` | A (`test_grid_snap.py`) |
| Deshacer / Rehacer | `Ctrl+Z` / `Ctrl+Y`, menú `Editar`; 50 pasos; **un arrastre = un paso** | `ui/session.py` (`undoable`, `begin/commit/cancel_edit`) | A (`test_undo_redo.py`, `test_gesture_undo.py`) |
| Medir distancia | Herramienta `Medir` (tecla `m`), metros reales | `ui/session.py`, `ui/editor_canvas.py` | A (`test_measure_tool.py`) |
| Piso activo (multiplanta) | El modelo `Floor` soporta varios pisos y `set_active_floor` | `ui/session.py` (`geometry_view`) | **B**: modelo `[IMPLEMENTADO]`, **sin selector de planta en la UI** `[IMPLEMENTACIÓN PARCIAL]` (auditoría 2026‑09: `set_active_floor` no se invoca desde app/paneles) |

### 7.2 Diseño de planta: paredes, huecos, espacios, objetos
| Funcionalidad | Detalle | Módulo | Estado |
|---|---|---|---|
| Paredes | Herramienta `Pared`/tecla `w`, 2 clics; arrastre de pared y de extremos; material y espesor editables | `core/wall.py`, `ui/session.py` | A (`test_geometry_editing.py`, `test_drag_and_coverage.py`) |
| Puertas/ventanas/pass‑through | Con pared seleccionada: botones `+ Puerta` / `+ Ventana`; offsets métricos sobre la pared; **reemplazan** la atenuación del muro en el cruce | `core/wall.py`, `engine/obstacles.py` | A (`test_spaces_openings.py`, 69 pruebas) |
| Espacios (zonas) | Herramienta `Zona`/tecla `e`; solo organizativos, **sin efecto RF** (decisión BH) | `core/space.py` | A |
| Objetos (mobiliario) | Herramienta `Objeto`/tecla `o`, 2 clics + preview; footprint rectangular; material + atenuación por banda; **sí atenúa la señal** | `core/obstacle.py`, `engine/obstacles.py` | A (`test_obstacles.py`, 84 pruebas) |

### 7.3 Access Points y configuración RF
| Funcionalidad | Detalle | Módulo | Estado |
|---|---|---|---|
| Crear/mover AP | Herramienta `AP`/tecla `a`, 1 clic; arrastre en modo selección | `ui/session.py`, `ui/editor_canvas.py` | A |
| Configuración RF por AP | Panel "Configuración RF del AP": banda, canal, ancho, estándar, potencia TX; botón `Aplicar` (commit atómico con validación) | `ui/panels/properties.py`, `core/channel.py` | A (`test_ap_config_flow.py`) |
| Canal Wi‑Fi | Catálogo por familia; etiqueta `CH n · w MHz` bajo el AP solo si tiene canal | `core/channel.py` | A (`test_channels.py`, 34 pruebas) |
| Banda por AP (`band_id`) | `ap.band_id` o la banda de la corrida o la activa (`resolve_band_for_ap`) | `ui/session.py` | A |
| Optimización de canales | Botón `Opt. canal…` → propuesta con método de búsqueda, score SINR actual vs propuesto, tabla AP actual/propuesto; `Aplicar propuesta` **solo tras confirmar** | `engine/channel_optimization.py`, `ui/dialogs/channel_optimization_dialog.py` | A (`test_channel_optimization.py`, 38 pruebas) |
| Sensibilidad del cliente (`sensitivity_dbm`) | Existe en el modelo y se usa en `evaluate_link` | `core/client.py` | **B**: `[IMPLEMENTACIÓN PARCIAL]` — no editable desde la UI |

### 7.4 Clientes / dispositivos
| Funcionalidad | Detalle | Módulo | Estado |
|---|---|---|---|
| Crear/mover/eliminar cliente | Herramienta `Cliente`/tecla `c`; arrastre | `ui/session.py` | A |
| **Estado de señal del cliente** | 5 niveles: SEÑAL BUENA (≥ −55), SEÑAL FUERTE (≥ −67), SEÑAL DÉBIL (≥ −75), SEÑAL INESTABLE (≥ −85), SIN SEÑAL. Indicador de color en el plano + bloque en el panel (AP asociado, banda, RSSI, SNR, estado) | `ui/client_signal.py`, `ui/theme.py`, `ui/panels/properties.py` | A `[IMPLEMENTADO Y PROBADO]` (`test_client_signal.py`, 16 pruebas; **sin commitear**) |
| Asociación AP↔cliente | Es **dinámica**: el de mayor RSSI en la posición del cliente (no hay estado de asociación guardado) | `ui/client_signal.py::evaluate_client_state` | A (decisión explícita; ver §13) |

### 7.5 Heatmaps y métricas (detalle completo en §10)
| Funcionalidad | Detalle | Estado |
|---|---|---|
| Heatmap combinado ("Todos los AP") | Mejor RSSI por punto | A (`test_heatmap.py`, `test_multi_ap.py`) |
| Heatmap por AP | Selector `AP:` | A |
| Métricas `RSSI` / `SNR` / `Interferencia` / `SINR` | Selector `Métrica:`; cambio **sin recalcular RF** (solo repintado) | A (`test_ap_coverage_cache.py::test_changing_the_metric_only_repaints`) |
| Leyenda + estadísticas | Cobertura %, dominancia por AP, min/max/avg de la métrica, ratios de cumplimiento | A |
| Encender/apagar heatmap | Casilla `Heatmap`; apagar **no** recalcula ni borra la capa del AP seleccionado | A |
| Capa de cobertura del AP seleccionado | Overlay cian→violeta con el límite de cobertura, independiente del fondo | A `[IMPLEMENTADO Y PROBADO]` (`test_drag_and_coverage.py`, 11 pruebas de overlay; **sin commitear**) |

### 7.6 Cálculos
| Funcionalidad | Detalle | Estado |
|---|---|---|
| FSPL, link budget, SOM, SNR, SINR | Ver §8 (fórmulas exactas) | A (`test_link_budget.py`, `test_propagation.py`, `test_rf_extension.py`, `test_sinr.py`) |
| Pérdidas por paredes/huecos/objetos | Ver §8.4 | A (`test_wall_materials.py`, `test_spaces_openings.py`, `test_obstacles.py`) |
| Interferencia espectral entre APs | Ver §8.5 | A (`test_interference.py`, 72 pruebas) |
| Clasificación de calidad y veredictos | Ver §8.6 | A (`test_classifier.py`) |
| Simulación puntual | Botón `Simular`: resumen + heatmap; con error controlado (sin AP → diálogo; 6 GHz → mensaje en panel) | A (`test_simulator.py`, auditado) |

### 7.7 Persistencia
| Funcionalidad | Detalle | Estado |
|---|---|---|
| Guardar / Abrir / Nuevo | Menú `Archivo`; JSON `schema_version 1`; `dirty state` con confirmación de cambios sin guardar | A (`test_persistence.py` 37, `test_persistence_hardening.py` 43, `test_persistence_f14.py` 7) |
| Compatibilidad hacia atrás | Claves nuevas (`radio` ampliado, `spaces`/`openings`/`obstacles`, `band_id`, `sinr_target_db`) son **opcionales al leer**: los archivos de fases previas abren sin migración | A |
| Escritura segura | `.tmp` + `fsync` + `os.replace`; revalidación previa | A |
| Entrada no confiable | Tipos estrictos, NaN/Inf, límites de tamaño, ids únicos, parser también protegido | A |

### 7.8 Exportación / impresión / ayuda
| Funcionalidad | Estado |
|---|---|
| Exportar imagen/PDF/CSV/reportes | **C `[PLANEADO / NO IMPLEMENTADO]`** — grep de `export|imprimir|clipboard|png` en el código = 0 resultados (auditoría 2026‑09) |
| Impresión | **C `[PLANEADO / NO IMPLEMENTADO]`** |
| Menú Ayuda / tooltips | **C `[PLANEADO / NO IMPLEMENTADO]`** — solo menús `Archivo`, `Editar`, `Ver` |
| Copiar al portapapeles | **C `[PLANEADO / NO IMPLEMENTADO]`** |

### 7.9 Testing (resumen; detalle en §12)
Suite pytest de 955 pruebas que cubre dominio, motor RF, persistencia y UI (con Tk real en los tests marcados `tk_*`).

---

## 8. Modelo RF

> **Regla de honestidad:** todas las fórmulas viven en `engine/`. La UI no contiene fórmulas.
> Unidades: distancia **m**, frecuencia **MHz** (FSPL) o **Hz** (λ), potencia **dBm**, ganancia **dBi**, pérdidas **dB**.

### 8.1 Longitud de onda
**NOMBRE:** wavelength_m
**FÓRMULA:** `λ = c / f`
**VARIABLES:** `c = 3×10⁸ m/s` (aproximación de ingeniería), `f` en Hz.
**UNIDADES:** metros.
**VALORES POR DEFECTO:** — (n/a).
**ORIGEN DEL VALOR:** `engine/propagation.py::SPEED_OF_LIGHT_M_S`.
**DÓNDE SE CALCULA:** `engine/propagation.py::wavelength_m`.
**CÓMO SE USA POSTERIORMENTE:** utilidad de dominio (no entra en el link budget).

### 8.2 FSPL — Free Space Path Loss
**NOMBRE:** path_loss_fspl_db
**FÓRMULA:** `FSPL(dB) = 20·log10(d) + 20·log10(f_MHz) − 27.55`
**VARIABLES:** `d` en metros (> 0), `f_MHz` en MHz (> 0).
**UNIDADES:** dB. **Redondeo:** 2 decimales (compatibilidad legacy).
**ORIGEN DEL VALOR:** `_FSPL_CONSTANT_DB = -27.55` (`engine/propagation.py`) — forma abreviada de la fórmula ITU con d en metros. *Nota de trazabilidad:* la forma equivalente `+32.44` (aparece en una línea de `docs/formulas.md`) corresponde a `d` en **km**; la implementación usa la forma de metros.
**DÓNDE SE CALCULA:** `engine/propagation.py::path_loss_fspl_db`.
**CÓMO SE USA:** entra al link budget (§8.3) como `path_loss`.
**VALIDACIONES:** `ValueError` si `d ≤ 0` o `f ≤ 0`.
**APROXIMACIÓN:** es pérdida en **espacio libre**; el efecto de los obstáculos se añade aparte (§8.4). No es una simulación EM.

### 8.3 Presupuesto de enlace (P_rx / RSSI) y SOM
**NOMBRE:** link_budget
**FÓRMULA:**
`P_rx = P_tx + G_tx − L_tx − FSPL − L_m + G_rx − L_rx − L_obstacles`
`SOM = P_rx − Sensibilidad`
**VARIABLES / UNIDADES / VALORES POR DEFECTO:**

| Símbolo | Significado | Unidad | Default | Origen |
|---|---|---|---|---|
| `P_tx` | Potencia de transmisión | dBm | 20.0 | `core/radio.py::RadioConfiguration.p_tx_dbm` |
| `G_tx` | Ganancia antena TX | dBi | 3.0 | `g_tx_dbi` |
| `L_tx` | Pérdidas TX | dB | 1.0 | `l_tx_db` |
| `FSPL` | Pérdida en espacio libre | dB | calculado | §8.2 |
| `L_m` | Margen de desvanecimiento (fade margin) | dB | 10.0 | `fade_margin_db` (decisión B; 0.0 reproduce legacy v3/v4) |
| `G_rx` | Ganancia antena RX | dBi | 0.0 | `g_rx_dbi` |
| `L_rx` | Pérdidas RX | dB | 1.0 | `l_rx_db` |
| `L_obstacles` | Pérdida por materiales atravesados | dB | 0.0 | `engine/obstacles.py::trace_walls` |
| `Sensibilidad` | Sensibilidad del receptor | dBm | −75.0 | `sensitivity_dbm` |

**DÓNDE SE CALCULA:** `engine/link_budget.py::link_budget`, `system_operating_margin`.
**CÓMO SE USA:** `evaluate_link` lo convierte en `LinkEvaluation` (por punto): `rx_power_dbm` (RSSI), `som_db`, calidad, veredicto.
**REDAONDEO:** `rx_power` y `som` a 2 decimales.
**CASO d = 0:** si el punto coincide con el AP se usa `MIN_FSPL_DISTANCE_M = 0.1 m` **solo para FSPL** (decisión T; no modifica la fórmula).

### 8.4 Pérdidas por obstáculos (paredes, huecos, mobiliario)
**NOMBRE:** wall_attenuation_db / obstacle_attenuation_db / trace_walls
**FÓRMULA (pared):** `L_wall = L_ref(material, banda) · (t_actual / t_ref)`
- `t_ref = material.thickness_default_m`; `L_ref = material.attenuation_db[band_id]`.
- Si `wall.thickness_m is None` → `t_actual = t_ref` → `L = L_ref`.
- `blocks_signal=False` → 0 dB.

**FÓRMULA (hueco, decisión BG):** si el cruce cae dentro de un `Opening` (unión de intervalos cerrados con ε = 1e‑9, orden canónico `(start, id)`):
`L_cruce = override(banda) o 0 dB` — **sustituye** a la del material (nunca suma). Un cruce en hueco **no** consulta el catálogo de materiales (6 GHz atraviesa huecos con 0 dB).

**FÓRMULA (objeto, decisión BM):**
`L_obstáculo = override(banda)` si existe, si no `L_ref(material, banda)` **sin escalar por espesor**.
- **Un solo atravesamiento por objeto** (≥1 cruces de borde → 1 pérdida con la menor distancia; decisión BN).
- Orden fusionado canónico: `(distancia, tipo (pared=0 < objeto=1), id)`.

**TOTAL:** `L_obstacles = Σ L_cruces_pared/hueco + Σ L_objetos`.
**DÓNDE:** `engine/obstacles.py`. **CÓMO SE USA:** como `L_obstacles` del link budget.
**6 GHz:** una pared/objeto sólido cruzado sin datos de atenuación para `band_6` lanza `MaterialAttenuationError` (`core/material.py`). **No se inventan valores** ni hay conversión 5→6 GHz.
**APROXIMACIÓN DECLARADA:** el escalado lineal por espesor es una **aproximación de ingeniería**, no una curva de atenuación medida por capas (`docs/formulas.md`).

**Valores de referencia del catálogo** (`config/default_config.yaml` — estimaciones configurables, no catálogos de fabricante):

| Material (id) | Nombre | 2.4 GHz | 5 GHz | Espesor ref. |
|---|---|---:|---:|---:|
| drywall | Muro de yeso | 3 dB | 4 dB | 12 mm |
| wood | Madera | 3 dB | 4 dB | 40 mm |
| glass | Vidrio | 3 dB | 4 dB | 8 mm |
| brick | Ladrillo | 6 dB | 8 dB | 120 mm |
| concrete | Concreto | 12 dB | 15 dB | 150 mm |
| reinforced_concrete | Concreto reforzado | 15 dB | 20 dB | 200 mm |
| metal | Metal | 25 dB | 30 dB | 5 mm |

*(Sin datos para `band_6`: consulta → `MaterialAttenuationError`.)*

### 8.5 SNR, interferencia y SINR
**NOMBRE SNR:** signal_to_noise_ratio
**FÓRMULA:** `SNR(dB) = P_rx − Noise Floor`
**VARIABLES:** `P_rx` (dBm, §8.3), `Noise Floor` (dBm, default −95).
**DÓNDE:** `engine/link_budget.py`. **USO:** `LinkEvaluation.snr_db`, métrica `snr`, stats.

**NOMBRE Interferencia:** modelo espectral (F11)
**FÓRMULAS:**
- Ocupación de una emisión: `[f_c − W/2, f_c + W/2)` MHz (intervalos **semiabiertos**).
- Solapamiento: `overlap = max(0, min(hi_a,hi_b) − max(lo_a,lo_b))`; `overlap_ratio = overlap / min(W_a, W_b)`.
- Contribución por interferente (PSD **plana**): `I_i = P_rx,i + 10·log10(overlap / W_i)` dBm si `overlap > 0`; `None` si 0.
- Agregación en dominio lineal: `I_total = 10·log10( Σ 10^(I_i/10) )` dBm; `None` si no hay contribuyentes.
**VARIABLES:** `f_c` = centro del canal (catálogo F10), `W` = `channel_width_mhz` del AP.
**DÓNDE:** `engine/interference.py`. **USO:** `LinkEvaluation.interference_dbm` (+ `interferer_count`, `dominant_interferer_ap_id`), métrica `interference`.
**ALCANCE (decisión CB):** solo interactúan APs del **mismo `band_id`** y **con canal configurado**.
**APROXIMACIONES DECLARADAS:** rectángulo ideal (sin lobulaciones, guard bands ni máscara PHY), PSD plana, sin CCA/CSMA/captura/delay spread. Es estimación de planificación.

**NOMBRE SINR:** signal_to_interference_noise_ratio (F12)
**FÓRMULA:** `SINR = P_rx − 10·log10( 10^(N/10) + 10^(I_total/10) )` dB
**FORMA NUMÉRICAMENTE ESTABLE:** con `D = max(N, I)`, `m = min(N, I)`: `denominador = D + 10·log10(1 + 10^((m−D)/10))` (exponente ≤ 0 → sin overflow).
**CASO SIN INTERFERENCIA (decisión CG):** `I_total = None` → `SINR = SNR` **exactamente** (misma aritmética redondeada).
**UMBRAL:** `cumple ⇔ SINR ≥ sinr_target_db` (default 25 dB, rango [−20, 60]).
**DÓNDE:** `engine/sinr.py`. **USO:** `LinkEvaluation.sinr_db`, métrica `sinr`, optimización de canales (F13).
**NOTA:** SINR **nunca** cambia el ganador multi‑AP (sigue siendo MAX RSSI).

### 8.6 Clasificación y veredictos
**Clases de calidad** (`engine/classifier.py::classify_quality`, sobre `P_rx`): Excelente `≥ −50`, Buena `≥ −67`, Regular `≥ −75`, Débil `≥ −85`, Sin cobertura útil `< −85` dBm (umbrales configurables).
**Veredicto SOM** (`classify_som`): APROBADO `SOM ≥ 20`; RIESGO `10 ≤ SOM < 20`; FALLIDO `< 10` (decisión D: comparación `≥`).
**RSSI objetivo** (`meets_rssi_target`): cumple si `P_rx > −67` dBm (**estricto**, decisión C).
**SNR objetivo** (`meets_snr_target`): `SNR ≥ 25` dB (decisión AW).
**Diagnóstico RF** (`rf_diagnostic`): 4 cuadrantes RSSI×SNR (decisión BC).
**Diagnóstico SINR** (`sinr_diagnostic`): "SINR adecuado" / "SINR bajo" (no toca el anterior).

### 8.7 Multi‑AP y estadísticas
- Combinación (`engine/combine.py`): por punto gana **mayor `rx_power_dbm`**; empate → menor `access_point_id`. Rechaza mezclar bandas distintas (contrato F5).
- Estadísticas: `%` de cobertura (denominador = todos los puntos del grid), dominancia por AP, min/max/avg de la métrica, ratios `rssi_ratio`/`snr_ratio`/`sinr_ratio` (puntos que cumplen / total). En combinación multi‑AP el SNR/SINR es el del **AP ganador** (nunca se promedia, decisión BB/CF).

### 8.8 Validación numérica (evidencia)
- Golden data legacy (Tablas 2 y 3 del DOCX) validada en `tests/test_link_budget.py` vía `tests/fixtures/golden_data.py`. Ejemplo verificado: 10 m @ 5180 MHz → `FSPL = 66.74 dB`, `P_rx = −55.74 dBm`, `SOM = 19.26 dB → RIESGO`.
- Auditoría funcional 2026‑09 (scripts temporales): **28/28 comprobaciones numéricas** correctas (FSPL exacto; P_tx +6 dB → RSSI +6 dB; piso de ruido cambia solo SNR; 5 GHz −6.55 dB vs 2.4 GHz a igualdad de parámetros; concreto 12 dB; doble espesor = doble pérdida; `blocks_signal=False` → 0 dB; monotonía por distancia; multi‑AP gana el mayor RSSI; SINR ≤ SNR; invariancia ante resolución del grid; medida de distancia 3‑4‑5 = 5.00 m).

---

## 9. Parámetros RF configurables

Todos viven en `core/` (defaults) y en `config/default_config.yaml`; se editan desde la UI donde se indica.

| Parámetro | Tipo / Unidad | Default | Rango | Se configura en | Se persiste en | Se consume en | Efecto en el cálculo |
|---|---|---|---|---|---|---|---|
| `p_tx_dbm` | float, dBm | 20.0 | [NO DETERMINADO] | Panel "Configuración RF del AP" → Potencia TX | `access_points[].radio` | `link_budget` | Suma directa a P_rx (lineal en dB) |
| `g_tx_dbi` | float, dBi | 3.0 | [NO DETERMINADO] | Solo código/YAML | `radio` | `link_budget` | Suma a P_rx |
| `l_tx_db` | float, dB | 1.0 | [NO DETERMINADO] | Solo código/YAML | `radio` | `link_budget` | Resta a P_rx |
| `g_rx_dbi` / `l_rx_db` | float | 0.0 / 1.0 | [NO DETERMINADO] | Solo código/YAML | `radio` | `link_budget` | Suma/resta a P_rx |
| `sensitivity_dbm` | float, dBm | −75.0 | [NO DETERMINADO] | No editable por cliente desde UI (solo modelo) | `radio`, `clients[]` | `system_operating_margin` | Define SOM y veredicto |
| `fade_margin_db` (`L_m`) | float, dB | 10.0 | [NO DETERMINADO] | Solo código/YAML | `radio` | `link_budget` | Resta a P_rx (0 = legacy v3/v4) |
| `noise_floor_dbm` | float, dBm | −95.0 | [−200, 0] (`core/radio.py`) | Diálogo `Config RF…` | `radio.noise_floor_dbm` | `signal_to_noise_ratio`, SINR | Baja/sube SNR y SINR; **no** cambia RSSI |
| `channel_width_mhz` | int, MHz | 20 | {20,40,80,160}; 2.4 GHz solo 20/40 | Diálogo `Config RF…` + panel del AP | `radio.channel_width_mhz` | Validación + modelo espectral (F11) | **No** entra en FSPL (decisión AY); define el ancho de la emisión para interferencia |
| `wifi_standard` | str | "802.11ax" | 802.11n/ac/ax/be | Diálogo `Config RF…` | `radio.wifi_standard` | `wifi_generation()` | Metadato (etiqueta "Wi‑Fi 4/5/6/7", 6E si `ax` y f ≥ 5925); **sin efecto RF** (decisión AX) |
| `rssi_target_dbm` | float, dBm | −67.0 | [NO DETERMINADO] | Diálogo `Config RF…` | `thresholds` | `meets_rssi_target` | Umbral de cumplimiento (comparación `>`) |
| `som_aprobado_min_db` / `som_riesgo_min_db` | float, dB | 20.0 / 10.0 | [NO DETERMINADO] | Código/YAML | `thresholds` | `classify_som` | Veredicto APROBADO/RIESGO/FALLIDO |
| `excellent/good/regular/weak_min_dbm` | float, dBm | −50/−67/−75/−85 | [NO DETERMINADO] | Código/YAML | `thresholds` | `classify_quality` | Clases de calidad y colores del heatmap |
| `snr_target_db` | float, dB | 25.0 | [−20, 60] | Diálogo `Config RF…` | `thresholds.snr_target_db` | `meets_snr_target` | Cumplimiento de SNR (`≥`) |
| `sinr_target_db` | float, dB | 25.0 | [−20, 60] | Diálogo `Config RF…` (6.º campo) | `thresholds.sinr_target_db` | `meets_sinr_target` | Cumplimiento de SINR (`≥`) |
| Banda (`band_id`) | str | `band_2_4` activa; bandas: 2437 / 5180 / 6135 MHz | 3 bandas del catálogo | Selector `Banda:` + panel del AP | `access_points[].band_id`, `editor_state` | `resolve_band_for_ap` → frecuencia de FSPL | Cambia la frecuencia de propagación (2.4 vs 5 GHz: 6.55 dB de diferencia medidos) |
| Canal (`channel`) | int | sin configurar (`None`) | 1…233 según familia | Panel del AP | `access_points[].channel` | Solo validación + interferencia (F11) | **No** altera RSSI/SOM/SNR (decisión BR); sí define `f_c` para interferencia/SINR |
| Espesor de pared | float, m | `material.thickness_default_m` | > 0 | Panel de la pared | `walls[].thickness_m` | `wall_attenuation_db` | Escala lineal de la pérdida |
| Atenuación por banda de hueco/objeto | dict banda→dB | 0 dB (hueco) / material (objeto) | [0, 200] | Panel Apertura / Objeto | `openings[]`, `obstacles[]` | `trace_walls` | **Reemplaza** la del material (nunca suma) |
| Resolución del grid | float, m | 0.5 (UI) | ≥ 0.05 (`MIN_RESOLUTION_M`); ≤ 100 000 puntos | Selector `Res.:` | `editor_state.grid_resolution_m` | `CoverageGrid` | Más/menos puntos de muestreo; **no** cambia la física (verificado) |
| Umbral de clasificación de clientes | float, dBm | −55/−67/−75/−85 | fijo en `ui/client_signal.py` | Solo código | no se persiste | `state_for_rssi` | 5 estados visuales del cliente |

---

## 10. Heatmaps y visualización RF

### 10.1 Qué representan
Mapa de color de una **métrica RF sobre los puntos del `CoverageGrid`** (una estimación predictiva, no EM). Métricas registradas (`ui/coverage_renderer.py:83`): `rssi`, `snr`, `interference`, `sinr`.
- `rssi`/`snr`/`sinr`: escala de "peor → mejor" (verde = mejor).
- `interference`: **dirección invertida** (más alto = peor); `None` → color "sin interferencia".

### 10.2 Cómo se generan
1. `EditorSession.run_heatmap()` (`ui/session.py:1326`) resuelve el ámbito (`HEATMAP_ALL_APS` o un AP) y construye el grid (`build_coverage_grid`).
2. Por cada AP: `engine.simulator.simulate_coverage(...)` con `walls/openings/obstacles` del piso activo y la banda resuelta por AP.
3. Si hay ≥2 resultados y canales: `annotate_interference` → `annotate_sinr` → `combine_results` (MAX RSSI).
4. `ui.coverage_renderer.build_heatmap_image(result, viewport, cell_size_m, metric)` → imagen RGBA; `ui/editor_canvas.draw_heatmap(image)` la coloca **debajo** de paredes/APs.
5. Se pintan estadísticas y leyenda.

### 10.3 Actualización, invalidación y caché (optimizaciones vigentes)
| Mecanismo | Comportamiento verificado | Dónde |
|---|---|---|
| **Debounce** | 150 ms (`HEATMAP_DEBOUNCE_MS`) — no recalcula en cada evento de arrastre | `ui/app.py:31,1028,1054` |
| **Invalidación** | `invalidate_heatmap()` marca `heatmap_dirty` y **vacía la caché de cobertura por AP**. Es el punto único por el que pasa toda mutación de RF (geometría, APs, banda, config, resolución, undo/redo) | `ui/session.py:893` |
| **Caché de cobertura del AP seleccionado** (F15.1, sin commitear) | `_ap_coverage_cache` con clave `_ap_coverage_key(ap)` (AP + banda + posición + parámetros de radio/umbrales + piso + resolución). `selected_ap_coverage()` reutiliza el `SimulationResult` (y `ui/app.py` reutiliza también la imagen) mientras la clave no cambie | `ui/session.py:1239,1278`; `ui/app.py:1058` |
| **Cambio de métrica = solo repintado** | `set_heatmap_metric` **no** invalida ni marca `dirty`; `ui/app.py::_recolor_heatmap` repinta desde `last_heatmap` sin RF | `ui/session.py:931`; `ui/app.py:705` |
| **Selección sin recálculo de fondo** | Seleccionar un AP solo añade/actualiza la capa de resaltado; el heatmap de fondo queda intacto (test `test_app_does_not_rescope_the_background_on_selection`) | `ui/app.py:1097` (`_run_heatmap_now`) |
| **Mover cliente sin RF** | Los clientes no irradian: mover uno **no** recalcula ni el heatmap ni la cobertura del AP; solo se invalida **su** estado de señal | `ui/session.py::move_client` (2027) |
| **Heatmap apagado** | No ejecuta RF; la capa del AP seleccionado sigue visible | `ui/app.py:1098-1103` |
| **Estados de cliente cacheados** | `client_states()` con caché que `mark_dirty()` vacía; autocuración (añade faltantes, borra eliminados) | `ui/session.py:1503` |

**Tiempos medidos (auditoría 2026‑09, escenario 100×100 @ 0,5 m):** seleccionar AP 4329 ms → 26 ms con caché; re‑selección 0 ms; mover cliente 3923 ms → 27 ms; cambiar métrica 8791 ms → 292 ms; mover AP y cambiar banda siguen recalculando (correcto).

**Rendimiento del motor (medido):** el coste dominante es `trace_walls` (~76 % del tiempo de RF); 50×50 @ 0,5 m ≈ 0,3 s; 100×100 @ 0,5 m ≈ 8,8 s; 200×200 @ 1,0 m ≈ 29,7 s (bloqueado antes por `MAX_GRID_POINTS`). El cálculo corre en el hilo de la UI (sin hilos) → ver §15.

### 10.4 Capa de cobertura del AP seleccionado (F15.1, sin commitear)
- Overlay construido **desde los RSSI ya calculados** (`selected_ap_coverage`) con los umbrales configurados del proyecto (−50/−67/−75/−85 dBm): sin fórmulas nuevas.
- Paleta deliberadamente distinta del fondo (cian → violeta) para que se distinga la capa; el **límite de cobertura** se dibuja con trazo blanco/contorno reforzado.
- Independiente del heatmap: se refresca aunque el heatmap esté apagado o acotado a otro AP.

---

## 11. Fases de desarrollo

> Fuente: historial de git (27 commits, mensajes "phase N") + `docs/decisions.md` + árbol de trabajo sin commitear.
> El orden y numeración **se conserva tal cual** aparece en git.

| FASE | OBJETIVO | CAMBIOS / NUEVAS FUNCIONALIDADES | ARCHIVOS AFECTADOS | TESTS | RESULTADO |
|---|---|---|---|---|---|
| **baseline** | Estado legacy previo | Scripts v1–v4 en la raíz | `CalculadoraWLAN_Visual.py`, `CalculoWifi2.py`, `calculo_wifi_biblioteca.py`, `CODIGO(Interactivo).py` | — | Base congelada |
| **F1** | Fundación: dominio, motor RF, config, tests, docs | `core/`, `engine/` (FSPL, link budget, classifier), `config/`, golden data | `core/*`, `engine/*`, `config/*`, `tests/*`, `docs/*` | suite inicial | Completada |
| **F2** | Geometría de paredes, intersección de rayos, atenuación | `trace_walls`, `intersection.py`, modelo de espesor | `engine/obstacles.py`, `engine/intersection.py` | `test_intersection.py`, `test_wall_materials.py` | Completada |
| **F3** | UI 2D (editor Tkinter) | `ui/` (viewport, canvas, paneles, sesión) | `ui/*`, `main.py` | `test_editor_session.py` | Completada |
| **F4** | Grid de cobertura + heatmap + leyenda + stats | `CoverageGrid`, `coverage_renderer` | `engine/coverage_grid.py`, `ui/coverage_renderer.py` | `test_coverage_grid.py`, `test_heatmap.py` | Completada |
| **F5** | Cobertura multi‑AP | `combine_results` (MAX RSSI), selector de AP | `engine/combine.py`, `ui/session.py` | `test_multi_ap.py` | Completada |
| **F6** | Persistencia local JSON | schema v1, guardar/abrir/nuevo, dirty state | `persistence/json_project_repository.py` | `test_persistence.py` | Completada |
| **F6.1** | Endurecimiento de persistencia | Parser duro, límites, invariantes, escritura atómica | `persistence/*` | `test_persistence_hardening.py` | Completada |
| **F7** | Extensión RF básica | noise floor, SNR, estándar, ancho de canal, métrica SNR, diálogo `Config RF` | `core/radio.py`, `engine/link_budget.py`, `ui/dialogs/rf_dialog.py` | `test_rf_extension.py` | Completada |
| **F8** | Geometría arquitectónica | `Space` (zonas), `Opening` (puertas/ventanas, reemplazo de atenuación) | `core/wall.py`, `core/space.py`, `engine/obstacles.py` | `test_spaces_openings.py` | Completada |
| **F9** | Obstáculos y mobiliario | `Obstacle` (footprint rect.), un atravesamiento por objeto | `core/obstacle.py`, `engine/obstacles.py` | `test_obstacles.py` | Completada |
| **F10** | Canales y config RF por AP | catálogo de canales, `band_id`/`channel` por AP, panel de radio | `core/channel.py`, `core/access_point.py`, `ui/panels/properties.py` | `test_channels.py` | Completada |
| **F11** | Interferencia espectral | modelo de ocupación/solapamiento/agregación, métrica `interference` | `engine/interference.py`, `core/result.py` | `test_interference.py` | Completada |
| **F12** | SINR + diagnóstico RF | `engine/sinr.py`, métrica `sinr`, umbral `sinr_target_db` | `engine/sinr.py`, `ui/coverage_renderer.py` | `test_sinr.py` | Completada |
| **F13** | Optimización de canales | `engine/channel_optimization.py`, diálogo de propuesta | `engine/channel_optimization.py`, `ui/dialogs/channel_optimization_dialog.py` | `test_channel_optimization.py` | Completada |
| **F14 (a–i)** | Editor 2D agnóstico del edificio | 14a tests A/B/C de escenario; 14b sin dimensiones implícitas; 14c `geometry_view`; 14d edición interactiva; 14e zoom/pan/snap; 14f herramienta medir; 14g undo/redo; 14h persistencia de geometría editada; 14i RF sobre geometría editada | `ui/geometry_view.py`, `ui/viewport.py`, `ui/session.py`, `ui/editor_canvas.py` | `test_scenario_ab.py`, `test_no_implicit_dimensions.py`, `test_geometry_view.py`, `test_geometry_editing.py`, `test_grid_snap.py`, `test_viewport.py`, `test_measure_tool.py`, `test_undo_redo.py`, `test_persistence_f14.py`, `test_rf_after_editing.py` | Completada |
| **F14.1** | Estabilización de undo por gesto | un arrastre = UNA entrada de historial (`begin/commit/cancel_edit`) | `ui/session.py`, `ui/editor_canvas.py` | `test_gesture_undo.py` | Completada |
| **F14.2** | Flujo de configuración de AP y simulación | panel de config RF atómico, refresh tras simular | `ui/panels/properties.py`, `ui/session.py` | `test_ap_config_flow.py` | Completada |
| **F15** (commit `3f1c751`) | Manipulación directa + cobertura por AP | manijas en extremos de pared, anillo de selección de AP, cierre de gesto en `ButtonPress`, **sincronización del selector de heatmap al seleccionar un AP** | `ui/app.py`, `ui/editor_canvas.py`, `tests/test_drag_and_coverage.py` | 13 pruebas | Completada. **⚠️ parte obsoleta:** el comportamiento "seleccionar AP re‑escala el heatmap" fue **reemplazado** por la capa de resaltado (15.1) — `[OBSOLETO / REEMPLAZADO]` |
| **F15.1** (sin commitear) | Capa de cobertura del AP seleccionado + caché + repintado de métrica | overlay `build_ap_coverage_overlay` (cian→violeta + límite), `selected_ap_coverage` + `_ap_coverage_cache`, `_recolor_heatmap`, reutilización de imagen | `ui/app.py`, `ui/session.py`, `ui/editor_canvas.py`, `tests/test_drag_and_coverage.py`, `tests/test_ap_coverage_cache.py` | +11 overlay, +12 caché | Completada, **pendiente de commit** |
| **F15.2** (sin commitear) | Estados de señal de los clientes | `ui/client_signal.py` (5 niveles), colores en `theme`, indicador en canvas, bloque en panel, caché por cliente | `ui/client_signal.py`, `ui/theme.py`, `ui/editor_canvas.py`, `ui/panels/properties.py`, `ui/session.py`, `tests/test_client_signal.py` | +16 | Completada, **pendiente de commit** |
| **Trabajo posterior** (sin commitear) | Pulido | pan con clic izquierdo (`_on_drag`/`_on_pan_*`), arreglo de estilos ttk (`STYLE_MAP` + `TCheckbutton`/`TSeparator`), nombre visible "Muro de yeso", reorganización de la toolbar en 2 filas, refresco del panel de simulación al cambiar de banda | `ui/app.py`, `ui/editor_canvas.py`, `ui/theme.py`, `ui/panels/toolbar.py`, `core/material.py`, `config/default_config.yaml` | incluidas en las anteriores | Completado, **pendiente de commit** |
| **Docs de usuario** (sin commitear) | Material de uso y presentación | `Documentos/manual_de_uso.md`, `Documentos/como_presentar_el_programa.md` | `Documentos/` | — | Completado |

**Cambios de arquitectura relevantes a lo largo de las fases:**
- F6/F6.1: el archivo JSON se convierte en representación externa única; el dominio ignora los archivos.
- F7–F12: los resultados RF se amplían con campos **paralelos** (SNR, interferencia, SINR) sin alterar los históricos (regresión byte‑idéntica exigida por tests).
- F14: el editor deja de acoplarse a un edificio concreto (sin clase `Scenario`/`Building`).
- F14.1: historial de undo por gesto.
- F15.1 (sin commitear): separación entre **fondo** (heatmap del ámbito) y **capa** (cobertura del AP seleccionado), con caché dedicada.

---

## 12. Testing

- **Framework:** pytest (`wifi_planner/pytest.ini`: `testpaths = tests`, `pythonpath = .`, `-q`).
- **Estado actual verificado hoy (27/09/2026): `955 passed / 0 failed` en 18.82 s** — árbol de trabajo completo (incluye las pruebas sin commitear). `[IMPLEMENTADO Y PROBADO]`
- **Contexto del número:** 955 corresponde al estado **actual** (con F15.1/F15.2 sin commitear). El commit `phase 15` (último commit) tenía ≈916 pruebas `[INFERIDO por resta: 955 − 12 (caché) − 16 (cliente) − 11 (ampliación de drag_and_coverage)]`.
- **Advertencia de interpretación (obligatoria en el documento final):** una suite en verde **no garantiza ausencia de errores**; demuestra que el comportamiento especificado se cumple en los casos probados.

### Pruebas por archivo (conteo real de hoy)

| Archivo | # | Área |
|---|---:|---|
| `test_obstacles.py` | 84 | Obstáculos/mobiliario (F9) |
| `test_spaces_openings.py` | 69 | Espacios y aperturas (F8) |
| `test_interference.py` | 72 | Interferencia espectral (F11) |
| `test_sinr.py` | 51 | SINR (F12) |
| `test_rf_extension.py` | 45 | Extensión RF: SNR, ruido, estándar (F7) |
| `test_persistence_hardening.py` | 43 | Persistencia endurecida (F6.1) |
| `test_channel_optimization.py` | 38 | Optimización de canales (F13) |
| `test_persistence.py` | 37 | Persistencia JSON (F6) |
| `test_editor_session.py` | 36 | Sesión del editor |
| `test_heatmap.py` | 35 | Heatmap (F4) |
| `test_channels.py` | 34 | Canales Wi‑Fi (F10) |
| `test_multi_ap.py` | 28 | Multi‑AP (F5) |
| `test_drag_and_coverage.py` | 24 | Manipulación directa + overlay + pan (F15/15.1) |
| `test_core.py` | 24 | Dominio |
| `test_geometry_editing.py` | 23 | Edición de geometría (F14‑D) |
| `test_viewport.py` | 21 | Viewport/zoom/pan (F14‑E) |
| `test_ap_config_flow.py` | 21 | Flujo de config de AP (F14.2) |
| `test_classifier.py` | 18 | Clasificación |
| `test_undo_redo.py` | 19 | Undo/redo (F14‑G) |
| `test_gesture_undo.py` | 18 | Undo por gesto (F14.1) |
| `test_client_signal.py` | 16 | Estados de cliente (F15.2, sin commitear) |
| `test_link_budget.py` | 16 | Link budget + golden data |
| `test_intersection.py` | 15 | Intersecciones |
| `test_geometry_view.py` | 15 | Instantánea de geometría (F14‑C) |
| `test_grid_snap.py` | 15 | Snap a rejilla (F14‑E) |
| `test_wall_materials.py` | 15 | Materiales/espesor (F2) |
| `test_scenario_ab.py` | 14 | Escenarios A/B/C (F14‑A) |
| `test_propagation.py` | 13 | FSPL/λ |
| `test_ap_coverage_cache.py` | 12 | Caché de cobertura (F15.1, sin commitear) |
| `test_coverage_grid.py` | 19 | Grid (F4) |
| `test_measure_tool.py` | 10 | Medir (F14‑F) |
| `test_no_implicit_dimensions.py` | 16 | Sin dimensiones implícitas (F14‑B) |
| `test_rf_after_editing.py` | 10 | RF tras editar (F14‑I) |
| `test_rf_integration.py` | 9 | Integración RF |
| `test_simulator.py` | 8 | Simulador |
| `test_persistence_f14.py` | 7 | Persistencia de geometría editada (F14‑H) |
| `test_config.py` | 5 | Configuración |
| **TOTAL** | **955** | |

*(Conteos obtenidos con `pytest --collect-only` hoy; la suma total cuadra: 955.)*

### Qué cubre cada bloque
- **RF puro:** `test_propagation`, `test_link_budget` (incluye la **golden data del DOCX**: Tablas 2 y 3), `test_classifier`, `test_rf_extension`, `test_sinr`, `test_interference`.
- **Geometría y atenuación:** `test_intersection`, `test_wall_materials`, `test_spaces_openings`, `test_obstacles`.
- **Simulación/combinación:** `test_simulator`, `test_coverage_grid`, `test_heatmap`, `test_multi_ap`, `test_rf_integration`, `test_rf_after_editing`.
- **Persistencia:** `test_persistence`, `test_persistence_hardening`, `test_persistence_f14`.
- **UI (con Tk real):** `test_editor_session`, `test_geometry_view`, `test_geometry_editing`, `test_grid_snap`, `test_viewport`, `test_measure_tool`, `test_undo_redo`, `test_gesture_undo`, `test_ap_config_flow`, `test_drag_and_coverage`, `test_client_signal`, `test_ap_coverage_cache`.
- **Optimización de canales:** `test_channel_optimization`.
- **Regresión "byte‑idéntica":** varios tests exigen que las fases nuevas **no** alteren los resultados históricos (FSPL/RSSI/SOM) — p. ej. A/B entre configurado y baseline (`test_channels.py`).

### Auditoría funcional independiente (2026‑09‑26/27)
Scripts temporales ejecutados contra la aplicación real (eventos de Tk y API):
- Flujo completo de UI: 79 comprobaciones (mayoría OK; fallos eran limitaciones del arnés, no del producto).
- RF numérico: **28/28 OK** (ver §8.8).
- Evidencia visual: 27 capturas de pantalla + análisis con visión de los estados clave.
- Hallazgos de comportamiento recogidos en §15 (limitaciones y problemas conocidos).

---

## 13. Decisiones técnicas (selección de las más relevantes)

Formato: DECISIÓN / PROBLEMA / SOLUCIÓN / MOTIVACIÓN / ALTERNATIVAS / IMPACTO.
Todas están documentadas con su letra en `docs/decisions.md` (A…CU). Se citan las claves.

1. **(A) Golden data del DOCX, no del XLSX.** PROBLEMA: las fuentes legacy divergen en distancias máximas. SOLUCIÓN: usar las tablas del DOCX (3.80/4.88/5.42/5.58 m). ALTERNATIVAS: valores de v3/v4 (5.72/8.92/6.87/9.65 m). IMPACTO: la validación numérica usa el conjunto DOCX.
2. **(B) `L_m = 10 dB` por defecto, configurable.** PROBLEMA: unos archivos legacy incluían el margen y otros no. SOLUCIÓN: default 10 dB (0 reproduce v3/v4). IMPACTO: los SOM coinciden con el DOCX.
3. **(C) RSSI objetivo con comparación estricta `>`.** PROBLEMA: v2 usaba `≥`. SOLUCIÓN: `>` (DOCX/v1/v3/v4).
4. **(D) Veredicto SOM con `≥` y suelos configurables.** PROBLEMA: v2 usaba `>` estricto. SOLUCIÓN: `≥` (20/10 dB).
5. **(T) Piso `MIN_FSPL_DISTANCE_M = 0.1` cuando el punto está sobre el AP.** PROBLEMA: `log10(0)` indefinido. SOLUCIÓN: piso solo para FSPL. IMPACTO: el heatmap no falla en la posición del AP.
6. **(K/L/M/P) Muestreo del grid.** Puntos en múltiplos de `resolution_m` + punto de borde; un AP por corrida simple; `%` de cobertura sobre **todos** los puntos.
7. **(O) Invalidación + debounce (~150 ms).** PROBLEMA: recalcular en cada evento de arrastre. SOLUCIÓN: `invalidate_heatmap()` + `after(150)`.
8. **(AZ/BE/BG/BO/BV/CH) Schema v1 con claves opcionales.** PROBLEMA: cada fase añade campos sin romper archivos anteriores. SOLUCIÓN: leer como opcional (ausente → default), escribir siempre; `schema_version` sigue siendo 1. IMPACTO: compatibilidad total hacia atrás.
9. **(BG) Los huecos reemplazan la atenuación del muro (nunca suman).** PROBLEMA: ambigüedad `material + override`. SOLUCIÓN: sustitución. IMPACTO: un hueco de 0 dB es físicamente una abertura.
10. **(BM/BN) Objetos: override sustituye material; un solo atravesamiento por footprint.** PROBLEMA: doble conteo al entrar y salir. SOLUCIÓN: 1 pérdida con la distancia de entrada; orden fusionado `(distancia, tipo, id)`.
11. **(BQ/BR) Canal = identificador lógico; frecuencia central derivada y jamás persistida.** PROBLEMA: inconsistencias canal↔frecuencia. SOLUCIÓN: catálogo único en `core/channel.py`; **el canal no entra en FSPL** (solo alimenta el modelo de interferencia). IMPACTO: A/B prueba que cambiar de canal no altera RSSI/SOM/SNR.
12. **(BS) `band_id` por AP con resolución `ap.band_id o banda de la corrida o activa`.** Un AP = un radio = una banda (sin multi‑radio).
13. **(AY) Ancho de canal no entra en FSPL.** PROBLEMA: FSPL no tiene término de ancho. SOLUCIÓN: el ancho es metadata de configuración (y define la ocupación espectral en F11). IMPACTO: honestidad física.
14. **(AX) El estándar Wi‑Fi es metadata.** Sin efecto RF; solo etiqueta ("Wi‑Fi 4/5/6/7", 6E).
15. **(BY/BZ/CA) Interferencia con rectángulo ideal, PSD plana y agregación lineal.** PROBLEMA: dBm no son aditivos. SOLUCIÓN: convertir a mW, sumar, volver a dBm; ausencia de contribución = `None` (nunca `−∞`).
16. **(BX/CF) Información paralela.** PROBLEMA: añadir interferencia/SINR sin romper lo existente. SOLUCIÓN: campos con default en `LinkEvaluation`; `combine_results` sigue eligiendo **MAX RSSI**; SINR nunca decide ganadores.
17. **(CG) SINR = SNR exactamente sin interferencia modelada.** PROBLEMA: inventaría precisión. SOLUCIÓN: igualdad bit a bit cuando `I = None`.
18. **(CF) Fórmula SINR única y numéricamente estable.** `D + 10·log10(1 + 10^((m−D)/10))` evita overflow; no finitos → `ValueError`.
19. **(CJ/CL/CK/CM/CN) Optimización de canales:** coste = `sinr_avg_db` (física ya modelada), orden total `(-sinr_avg, -sinr_min, nº de cambios, (ap_id, canal))`, búsqueda exhaustiva si ≤ 64 candidatos o descenso coordinado, **propuesta sin auto‑aplicar**.
20. **(CP/CQ/CR) Editor agnóstico del edificio:** no existe clase `Scenario`/`Building`; sin dimensiones implícitas (12×8 es solo el valor inicial explícito); instantánea `GeometryView`.
21. **(CS/CU) Undo por snapshots con tope 50; un arrastre = un paso (`begin/commit/cancel_edit`).** PROBLEMA: cada `motion` empujaba un snapshot y agotaba el historial.
22. **(BH) Espacios sin RF.** Las zonas son organizativas; los muros ya modelan la atenuación.
23. **(F15.1, sin commitear) Cobertura del AP seleccionado como capa aparte con caché.** PROBLEMA: seleccionar un AP recalculara el heatmap completo (4,3 s en 100×100@0,5). SOLUCIÓN: overlay independiente + `_ap_coverage_cache` + repintado de métrica sin RF. IMPACTO: selección en ~26 ms; cambio de métrica sin motor.
24. **(F15.2, sin commitear) Estado de cliente = lectura del motor en su posición exacta.** PROBLEMA: ¿cómo mostrar la señal real del cliente sin inventar física? SOLUCIÓN: `simulate_coverage` con `sample_points=[client.position]` para cada AP; "AP asociado" = mayor RSSI (no hay estado de asociación guardado).
25. **Sin caché/hilos en `engine/`** (decisión CE): determinismo y testabilidad; los grids son pequeños frente al coste del propio cálculo.

---

## 14. Problemas corregidos

| PROBLEMA | CAUSA | SOLUCIÓN | ARCHIVOS AFECTADOS | RESULTADO | TEST QUE LO VERIFICA |
|---|---|---|---|---|---|
| Distancias `d_max` contradictorias entre fuentes legacy | v1/v2 vs v3/v4 | Golden data = DOCX (decisión A) | `tests/fixtures/golden_data.py` | Valores fijos y documentados | `test_link_budget.py` |
| `L_m` presente en unas fuentes y ausente en otras | Legacy inconsistente | Default 10 dB configurable (B) | `core/radio.py` | Coincide con DOCX | `test_link_budget.py` |
| Operador RSSI `>` vs `≥` inconsistente | Divergencia v2 | `>` estricto (C) | `engine/classifier.py` | Semántica única | `test_classifier.py` |
| Veredicto SOM divergente (v2 con `>`) | Divergencia v2 | `≥` (D) | `engine/classifier.py` | Coincide con DOCX/v1/v3/v4 | `test_classifier.py` |
| FSPL sin validar frecuencia (v1) | Validación ausente | `ValueError` si f ≤ 0 | `engine/propagation.py` | Contrato estricto | `test_propagation.py` |
| `RSSI_OBJETIVO_MIN` definido y no usado (v1) | Código muerto | Siempre se evalúa el objetivo | `engine/link_budget.py` | Completitud | `test_link_budget.py` |
| XLSX con fórmulas rotas (`#REF!`) | Referencias corruptas | Golden data extraída del DOCX | `tests/fixtures/golden_data.py` | Fuente fiable | — |
| Undo agotado con un solo arrastre | Un snapshot por `mouse_motion` | Gestos `begin/commit/cancel_edit` (CU) | `ui/session.py`, `ui/editor_canvas.py` | Un arrastre = 1 paso | `test_gesture_undo.py` |
| Botones/etiquetas negros o ilegibles en la UI | `theme.STYLE_MAP` mezclaba opciones escalares con especificaciones de estado; pasar listas a `configure` guardaba cadenas `"{active #…}"` como color → `TclError: unknown color name` y widget negro | Separar `configure` (escalares) y `map` (estados); añadir estilos faltantes de `TCheckbutton`/`TSeparator` | `ui/theme.py`, `ui/app.py` | UI legible | Verificado visualmente en auditoría 2026‑09 |
| Recálculos masivos al seleccionar AP / mover cliente / cambiar métrica | Todo pasaba por `simulate_coverage` | Caché `_ap_coverage_cache` + `set_heatmap_metric` sin invalidación (F15.1) | `ui/session.py`, `ui/app.py` | 4,3 s → 26 ms (selección); 8,8 s → 0,29 s (métrica) | `test_ap_coverage_cache.py` (12) |
| No se veía qué AP está seleccionado / qué extremo es arrastrable | Falta de feedback visual | Anillo de selección + manijas en extremos (F15) | `ui/editor_canvas.py` | Feedback visual | `test_drag_and_coverage.py` |
| Estado del cliente desconocido en el plano | Sin métrica de usuario final | 5 estados con indicador (F15.2) | `ui/client_signal.py` et al. | Estado visible y en panel | `test_client_signal.py` (16) |
| Huecos (puertas/ventanas) no representables | Solo existían paredes sólidas | `Opening` con reemplazo de atenuación (F8/BG) | `core/wall.py`, `engine/obstacles.py` | RF correcta en aberturas | `test_spaces_openings.py` |
| Archivos corruptos podían romper la app | Confianza en la entrada | Validación estricta + escritura atómica (F6.1) | `persistence/json_project_repository.py` | Entrada no confiable | `test_persistence_hardening.py` |

---

## 15. Limitaciones actuales (obligatorio — sin ocultar nada)

### 15.1 Limitaciones del modelo RF (declaradas por el propio proyecto)
1. **Es una estimación predictiva, no una simulación electromagnética.** No hay método de los elementos finitos, trazado de rayos múltiple, reflexión/difracción, ni propagación por techo entre plantas.
2. **FSPL + atenuación de materiales con escalado lineal de espesor** — aproximación de ingeniería, no curvas medidas por capas.
3. **Materiales sin datos para 6 GHz:** el catálogo solo tiene 2.4/5 GHz; una consulta en `band_6` lanza `MaterialAttenuationError`. **No se inventan valores** (comportamiento deliberado y honesto).
4. **Interferencia con rectángulo ideal y PSD plana**: sin máscara PHY, guard bands, lobulaciones, captura, hidden node, DFS, temporizaciones.
5. **SINR = RSSI vs ruido+interferencia**: no modela CCA/CSMA, MCS, throughput, balanceo de carga, roaming, band steering, MLO/OFDMA.
6. **El canal no afecta al RSSI** (solo a la interferencia): no hay penalización por canal adyacente fuera del solape rectangular.
7. **Una banda por emisión; un AP = un radio = una banda.** No hay APs multi‑radio ni band steering.
8. **El cliente no emite**: su "estado" es la señal recibida; no hay uplink ni sensibilidad de AP.
9. **Sin asociación persistente AP↔cliente**: el "AP asociado" es el de mejor RSSI en ese instante.
10. **Sin modelo de piso/techo**: solo geometría 2D de una planta.

### 15.2 Limitaciones de la representación 2D
- Solo plantas alineadas a ejes (paredes = segmentos; objetos = rectángulos); sin rotación de objetos, sin polígonos arbitrarios, sin altura ni plantas en 3D (`Floor.elevation_m` existe en el modelo pero sin UI ni render 3D).
- Multiplanta **en el modelo** pero **sin selector de piso en la interfaz** `[IMPLEMENTACIÓN PARCIAL]`.
- Sin CAD: sin snaps angulares, sin operaciones booleanas, sin manijas de redimensionado de objetos.

### 15.3 Limitaciones de interfaz y producto
1. **Sin exportación** de imagen/PDF/CSV ni impresión `[PLANEADO / NO IMPLEMENTADO]`.
2. **Sin menú Ayuda ni tooltips**; la documentación está en `Documentos/*.md` (fuera de la app).
3. **Diálogos nativos del sistema** para `Abrir…`/`Guardar como…` (del SO) y para algunos mensajes (`messagebox` de Tk → ventana nativa Win32, clase `#32770`): estilo visual distinto al resto; **no automatizables en la auditoría** `[NO VERIFICADO visualmente]`.
4. **La herramienta "Cliente" vuelve sola a "Seleccionar"** tras cada clic (comportamiento del editor; sorprende al usuario nuevo).
5. **Etiquetas del plano que se solapan** (cliente/cliente, AP/cliente) y etiquetas de material en inglés (`concrete`) sobre el heatmap, ilegibles en algunos casos.
6. **Barra de estado**: `Herramienta: select` queda en inglés mientras el resto de la app está en español.
7. **Cliente `SIN SEÑAL` muestra `Banda: 2.4 GHz` con `AP asociado: Ninguno`** (la banda del intento fallido): confuso.
8. **Al cambiar la banda de un AP desde el panel, la app cambia también la banda activa**; los APs sin banda explícita se re‑simulan en la banda nueva sin aviso (el mensaje de "bandas mixtas" es difícil de alcanzar desde la UI).
9. **Tras un error de cálculo del heatmap (p. ej. 6 GHz) la barra de estado queda en `Heatmap: recalculando…` de forma permanente** (`heatmap_dirty` no se limpia en las ramas de error de `_run_heatmap_now`, `ui/app.py:1114-1140`).
10. **El cálculo corre en el hilo de la UI**: en planos grandes (100×100 m @ 0,5 m ≈ 8,8 s; 200×200 @ 1,0 m ≈ 29,7 s) la ventana deja de responder; `Opt. canal…` tarda ~5 s en abrirse.
11. **La primera selección de un AP** ejecuta una pasada completa de RF (después se cachea).
12. Parámetros **no editables desde la UI**: sensibilidad del cliente, ganancias/pérdidas de antena, fade margin, umbrales SOM/calidad (solo ruido, objetivos RSSI/SNR/SINR, estándar y ancho en el diálogo `Config RF…`).
13. Sin **exportación de resultados comparativos**, sin reporte automático, sin importación de mediciones de campo.

### 15.4 Limitaciones de alcance (fuera de la funcionalidad, por decisión)
- No hay simulación de tráfico, capacidad de usuario, QoS, ni dimensionado por número de clientes simultáneos.
- No hay base de datos, multiusuario, ni despliegue en red.

---

## 16. Estado actual

Fotografía al **27/09/2026** (rama `master`, commit `3f1c751` + trabajo sin commitear descrito en §11).

| FUNCIONALIDAD | ESTADO | EVIDENCIA | OBSERVACIONES |
|---|---|---|---|
| Modelo de dominio (geometría, materiales, radios, bandas, canales) | IMPLEMENTADO Y PROBADO | `test_core.py`, `test_channels.py` | — |
| Cálculos FSPL / link budget / SOM / SNR / SINR | IMPLEMENTADO Y PROBADO | `test_link_budget.py`, `test_rf_extension.py`, `test_sinr.py`; auditoría 28/28 | Fórmulas verificadas en §8 |
| Pérdidas por paredes, huecos y objetos | IMPLEMENTADO Y PROBADO | `test_wall_materials.py`, `test_spaces_openings.py`, `test_obstacles.py` | 6 GHz sin datos de material (error controlado) |
| Interferencia espectral + métrica `interference` | IMPLEMENTADO Y PROBADO | `test_interference.py` (72) | Requiere canales configurados |
| Heatmap RSSI/SNR/Interferencia/SINR | IMPLEMENTADO Y PROBADO | `test_heatmap.py`, `test_drag_and_coverage.py` | Estimación predictiva |
| Combinación multi‑AP | IMPLEMENTADO Y PROBADO | `test_multi_ap.py` | MAX RSSI; rechaza bandas mixtas |
| Editor 2D (crear/editar/arrastrar/medir/zoom/pan) | IMPLEMENTADO Y PROBADO | `test_geometry_editing.py`, `test_measure_tool.py`, `test_viewport.py` | Pan con clic izquierdo (sin commitear) |
| Undo/redo por gesto | IMPLEMENTADO Y PROBADO | `test_undo_redo.py`, `test_gesture_undo.py` | 50 pasos |
| Persistencia JSON (guardar/abrir/nuevo) | IMPLEMENTADO Y PROBADO | `test_persistence*.py` (87) | schema v1, escritura atómica |
| Optimización de canales | IMPLEMENTADO Y PROBADO | `test_channel_optimization.py` (38) | Propuesta; aplicación manual |
| Configuración RF por AP | IMPLEMENTADO Y PROBADO | `test_ap_config_flow.py` | — |
| Estados de señal de clientes (5 niveles) | IMPLEMENTADO Y PROBADO | `test_client_signal.py` (16) | **Sin commitear** |
| Capa de cobertura del AP seleccionado + caché | IMPLEMENTADO Y PROBADO | `test_ap_coverage_cache.py` (12), `test_drag_and_coverage.py` | **Sin commitear** |
| Configuración RF global (ruido/objetivos/estándar/ancho) | IMPLEMENTADO Y PROBADO | `test_rf_extension.py`, auditoría con diálogo real | — |
| Simulación puntual (`Simular`) | IMPLEMENTADO Y PROBADO | `test_simulator.py`, auditoría | Errores controlados |
| Selección de métrica sin recalcular | IMPLEMENTADO Y PROBADO | `test_ap_coverage_cache.py::test_changing_the_metric_only_repaints` | — |
| Multiplanta (varios `Floor`) | PARCIAL | `core/space.py`, `ui/session.py` | **Sin selector de planta en la UI** |
| Sensibilidad del cliente editable | PARCIAL | `core/client.py` | Solo modelo |
| Atenuación de huecos por banda editable | PARCIAL | `core/wall.py` | Panel parcial (tipo/offsets) |
| Exportación / impresión | NO IMPLEMENTADO | grep = 0 resultados | — |
| Menú Ayuda / tooltips | NO IMPLEMENTADO | solo 3 menús | — |
| Diálogo de catálogo de materiales | PLANEADO | `ui/dialogs/material_dialog.py` (stub vacío) | — |
| Editor de paredes avanzado (diálogo) | PLANEADO | `ui/dialogs/wall_dialog.py` (stub vacío) | — |
| 6 GHz operativo | PLANEADO / NO IMPLEMENTADO | `MaterialAttenuationError` | Por diseño: sin datos inventados |
| Roaming / asociación persistente | NO IMPLEMENTADO | — | "AP asociado" dinámico |
| 3D / multiplanta visual | PLANEADO | `Floor.elevation_m` existe | Sin UI ni render |

### Problemas conocidos abiertos (auditoría 2026‑09)
- Estado `recalculando…` permanente tras error de heatmap (§15.3.9).
- Cambio implícito de banda activa al configurar la banda de un AP (§15.3.8).
- Solapes de etiquetas y etiquetas de material en inglés (§15.3.5).
- Congelación de la UI en planos grandes (§15.3.10).

---

## 17. Flujo completo de usuario (pasos reales, verificados)

1. **Iniciar:** `python main.py` → `ui.run_app()` → ventana `WifiPlannerApp`.
2. **Crear proyecto:** `Archivo → Nuevo` → diálogo de dimensiones (p. ej. 30 × 15 m) → plano con rejilla.
3. **Definir la planta:** herramienta `Pared` (tecla `w`) → 2 clics por pared → seleccionarla → elegir **Material** y **Espesor** → `+ Puerta` / `+ Ventana` si hace falta. Herramienta `Zona` (tecla `e`) para espacios; herramienta `Objeto` (tecla `o`) para mobiliario.
4. **Añadir APs:** herramienta `AP` (tecla `a`) → 1 clic por AP.
5. **Configurar RF:** seleccionar el AP → panel "Configuración RF del AP" (banda, canal, ancho, estándar, potencia TX) → `Aplicar`. Opcional: `Config RF…` para ruido y objetivos globales.
6. **Ver la cobertura:** el heatmap se calcula solo (debounce 150 ms) → colores + leyenda + estadísticas en el panel; barra de estado: `Heatmap: actualizado`.
7. **Analizar:** selector `Métrica:` (RSSI / SNR / Interferencia / SINR); selector `AP:` (todos o uno); seleccionar un AP muestra su **capa de cobertura**.
8. **Añadir clientes:** herramienta `Cliente` (tecla `c`) → 1 clic → indicador de color (5 estados) y bloque "Estado RF" en el panel.
9. **Medir:** herramienta `Medir` (tecla `m`) → 2 clics → distancia en metros.
10. **Modificar y recalcular:** mover AP/pared/objeto → el heatmap se recalcula; `Ctrl+Z` deshace (un arrastre = 1 paso).
11. **Optimizar canales:** `Opt. canal…` → propuesta → `Aplicar propuesta` (solo si se confirma).
12. **Guardar:** `Archivo → Guardar` → JSON (`.tmp` + `fsync` + `os.replace`).
13. **Abrir:** `Archivo → Abrir` → diálogo del sistema → el proyecto se reconstruye y se recalcula todo.

*(No hay paso de "exportar": no existe esa función.)*

---

## 18. Glosario (definiciones adaptadas al uso del proyecto)

- **AP (Access Point):** punto de acceso Wi‑Fi modelado como una posición en metros + una configuración de radio (potencia, ganancias, pérdidas, banda, canal, ancho). Fuente de la señal en la simulación.
- **RSSI (Received Signal Strength Indicator):** potencia recibida estimada `P_rx` en dBm en un punto. En este proyecto **es el resultado del presupuesto de enlace** (FSPL + atenuación + márgenes).
- **P_tx / TX Power:** potencia de transmisión del AP en dBm (default 20 dBm).
- **Ganancia de antena (G_tx/G_rx):** en dBi (defaults 3 / 0).
- **Path Loss / FSPL:** pérdida en espacio libre `20log10(d) + 20log10(f) − 27.55` dB (d en m, f en MHz).
- **L_m / fade margin:** margen de desvanecimiento restado al presupuesto (default 10 dB).
- **L_obstacles:** suma de pérdidas por paredes, huecos y objetos atravesados por la trayectoria AP→punto.
- **SOM (System Operating Margin):** `P_rx − sensibilidad` en dB; margen sobre la sensibilidad del receptor. Veredicto APROBADO/RIESGO/FALLIDO.
- **Noise Floor / piso de ruido:** potencia de ruido de referencia del receptor (default −95 dBm). Base del SNR.
- **SNR:** `P_rx − Noise Floor` en dB.
- **Interferencia (I_total):** potencia agregada recibida de otros APs que solapan espectralmente, en dBm (modelo de rectángulo ideal + PSD plana).
- **SINR:** `P_rx − 10log10(10^(N/10) + 10^(I/10))` dB. Con I ausente, SINR = SNR.
- **Canal (channel):** identificador lógico (1–233) cuya frecuencia central se deriva del catálogo. **No** cambia RSSI; define la ocupación espectral.
- **Banda (band):** `band_2_4` (2437 MHz), `band_5` (5180 MHz), `band_6` (6135 MHz) — frecuencias de referencia usadas por FSPL.
- **Ancho de canal (W):** 20/40/80/160 MHz; define el intervalo ocupado `[f_c − W/2, f_c + W/2)`.
- **Ocupación/solapamiento espectral:** fracción de la potencia de un interferente que cae dentro del intervalo de interés (`overlap_ratio`).
- **Heatmap:** imagen de color por punto del grid con la métrica elegida. **Estimación predictiva**, no medida ni simulación EM.
- **Cobertura (%):** puntos del grid que cumplen el criterio / puntos totales del grid.
- **Dominancia:** porcentaje de puntos donde un AP es el de mayor RSSI.
- **Métrica:** `rssi` | `snr` | `interference` | `sinr` — vista del mismo resultado, no un recálculo.
- **Grid / resolución:** malla de puntos en metros (`resolution_m` ≥ 0,05 m; ≤ 100 000 puntos).
- **Opening (hueco):** puerta/ventana/pass‑through sobre una pared; **reemplaza** la atenuación del muro en su tramo.
- **Obstacle (objeto):** mobiliario/columna con footprint rectangular que **sí** atenúa la señal.
- **Space (zona):** región identificable; **sin efecto RF**.
- **`schema_version`:** versión del formato JSON (siempre 1; nuevas claves opcionales).
- **Invalidación / debounce:** marcar el cálculo como obsoleto y retrasar el recálculo 150 ms.
- **Golden data:** valores numéricos de referencia extraídos del DOCX legacy usados para validar el motor.

---

## 19. Información para el documento académico

Material factual disponible para construir cada sección (sin redactarlas):

- **Introducción:** qué es Wi‑Fi Planner (§1), su alcance real (§7) y su naturaleza de estimación predictiva (§8, §15.1).
- **Planteamiento del problema:** §3; datos de apoyo: dependencia de RSSI de distancia/frecuencia/paredes (§8), discrepancias de los métodos legacy (§13.1–13.3 y "Discrepancias" de `docs/decisions.md`).
- **Justificación:** ahorro iterativo frente a instalación por ensayo‑error; el proyecto valida su motor contra golden data históricas (§12).
- **Objetivos:** general y específicos de §2 (todos verificables).
- **Marco técnico:** §4 (tecnologías), §8 (modelo RF completo con fórmulas), §18 (glosario). Se pueden citar FSPL, link budget, SOM, SNR, SINR con sus fuentes (ITU‑abreviada para FSPL según `engine/propagation.py`).
- **Metodología:** desarrollo por fases con regresión byte‑idéntica entre fases (§11), decisiones documentadas (§13), tests deterministas + golden data (§12). Principio rector: separación de capas y "sin números mágicos".
- **Desarrollo:** evolución F1→F15.2 (§11), con hitos: motor RF (F1–F2), UI (F3), heatmap (F4), multi‑AP (F5), persistencia (F6), RF extendido (F7), geometría arquitectónica (F8–F9), canales (F10), interferencia/SINR (F11–F12), optimización (F13), editor completo (F14–F15.2).
- **Arquitectura:** §5 (capas y flujo de datos), §6 (estructura). Diagramas ya existentes en `docs/architecture.md`.
- **Diseño:** decisiones §13 (25 decisiones con alternativas), invariantes (canal↔banda, schema v1, sin fórmulas en la UI).
- **Implementación:** §6 (ficheros y responsabilidades), §10 (heatmaps y optimizaciones), §9 (parámetros).
- **Pruebas:** §12 (955 pruebas, desglose por área, golden data, auditoría independiente con 28/28 numéricos).
- **Resultados:** §12 (suite en verde), §10.3 (rendimiento medido: selección de AP 4,3 s→26 ms; métrica 8,8 s→0,29 s), §8.8 (validación numérica).
- **Limitaciones:** §15 completo (RF, 2D, producto, alcance) — **debe reproducirse con honestidad**.
- **Conclusiones:** síntesis de §21.
- **Trabajo futuro:** lo que está planeado y no implementado (§16): exportación, ayuda integrada, multiplanta en UI, 6 GHz con materiales propios, edición de sensibilidad/ganancias, sustitución de la PSD plana por una máscara real, CCA/CSMA, medida en sitio para calibración.

---

## 20. Trazabilidad (afirmación → evidencia)

| Afirmación | Archivo / función | Test |
|---|---|---|
| FSPL = 20log10(d)+20log10(f)−27.55 | `engine/propagation.py::path_loss_fspl_db` | `test_propagation.py`, `test_link_budget.py` |
| P_rx = P_tx+G_tx−L_tx−FSPL−L_m+G_rx−L_rx−L_obstacles | `engine/link_budget.py::link_budget` | `test_link_budget.py` |
| SOM = P_rx − sensibilidad | `engine/link_budget.py::system_operating_margin` | `test_link_budget.py` |
| SNR = P_rx − noise floor | `engine/link_budget.py::signal_to_noise_ratio` | `test_rf_extension.py` |
| SINR = P_rx − 10log10(10^(N/10)+10^(I/10)); SINR=SNR sin I | `engine/sinr.py::signal_to_interference_noise_ratio` | `test_sinr.py` |
| I_total con agregación lineal (mW) | `engine/interference.py::aggregate_dbm` | `test_interference.py` |
| L_wall = L_ref·(t/t_ref) | `engine/obstacles.py::wall_attenuation_db` | `test_wall_materials.py` |
| Huecos reemplazan la atenuación del muro | `engine/obstacles.py::trace_walls` | `test_spaces_openings.py` |
| Objetos: un solo atravesamiento, override sustituye | `engine/obstacles.py::obstacle_attenuation_db`, `trace_obstacles` | `test_obstacles.py` |
| Combinación multi‑AP = mayor RSSI | `engine/combine.py::combine_results` | `test_multi_ap.py` |
| Heatmap = estimación sobre el grid | `engine/simulator.py::simulate_coverage`, `engine/coverage_grid.py` | `test_heatmap.py`, `test_coverage_grid.py` |
| Canal no altera RSSI | `core/channel.py` + A/B | `test_channels.py` |
| Caché de cobertura por AP | `ui/session.py::_ap_coverage_key`, `selected_ap_coverage` | `test_ap_coverage_cache.py` |
| Cambio de métrica sin RF | `ui/session.py::set_heatmap_metric`, `ui/app.py::_recolor_heatmap` | `test_ap_coverage_cache.py::test_changing_the_metric_only_repaints` |
| Estados de cliente (5 niveles) | `ui/client_signal.py::state_for_rssi` | `test_client_signal.py` |
| Undo por gesto = 1 paso | `ui/session.py::begin_edit/commit_edit/cancel_edit` | `test_gesture_undo.py` |
| Persistencia schema v1 + escritura atómica | `persistence/json_project_repository.py::save_project` | `test_persistence*.py` |
| Optimización de canales sin auto‑aplicar | `engine/channel_optimization.py::optimize_channels`, `EditorSession.apply_channel_assignment` | `test_channel_optimization.py` |
| Límites del grid | `engine/coverage_grid.py::MIN_RESOLUTION_M, MAX_GRID_POINTS` | `test_coverage_grid.py` |
| 955 pruebas / 0 fallos hoy | ejecución `python -m pytest` (27/09/2026) | — |
| Sin exportación/imprimir/ayuda | grep sobre el código (2026‑09) | — |

---

## 21. Resumen ejecutivo para otro modelo

**Wi‑Fi Planner V1** es una aplicación de escritorio en **Python 3.14 + Tkinter** que modela plantas 2D (paredes con material/espesor, puertas/ventanas, mobiliario) y **predice la cobertura Wi‑Fi** con un motor RF propio: FSPL + presupuesto de enlace + atenuación por materiales, con métricas **RSSI, SOM, SNR, Interferencia y SINR**, combinación multi‑AP (mayor RSSI por punto) y **optimización de canales** basada en el SINR medio.

Estado: **completo y probado en su alcance** — 955 pruebas automatizadas en verde (27/09/2026), validación numérica 28/28 en auditoría independiente, y golden data histórica (DOCX) reproducida por el motor. El desarrollo está organizado en **fases numeradas** (F1–F15.2) con la disciplina de que cada fase nueva **no altera** los resultados históricos (regresión byte‑idéntica) y toda decisión técnica está documentada en `docs/decisions.md`.

Lo que **no** debe afirmarse como implementado: exportación/imprimir, ayuda integrada, 6 GHz operativo (sin datos de materiales), multiplanta en la interfaz, edición de sensibilidad/ganancias desde la UI, asociación persistente AP↔cliente, y cualquier simulación EM/3D/CCA‑CSMA/throughput. El modelo tiene simplificaciones declaradas (FSPL, escalado lineal de espesor, rectángulo ideal de espectro, PSD plana) que deben presentarse como **aproximaciones de ingeniería**, nunca como precisión física.

Problemas conocidos abiertos (auditoría de septiembre 2026): estado `recalculando…` permanente tras error de cálculo, cambio implícito de banda activa al configurar un AP, solapes de etiquetas, y congelación de la UI en planos grandes. Hay además trabajo **sin commitear** (caché de cobertura, estados de cliente, pan, pulido de UI) equivalente a las "fases" 15.1/15.2.

---

# INSTRUCCIONES PARA EL MODELO QUE RECIBA ESTE CONTEXTO

Este documento es la **fuente principal de verdad** sobre el proyecto Wi‑Fi Planner V1. Al redactar el documento técnico final (Word):

1. **No inventes información.** Todo lo que afirmes debe estar en este contexto o en los archivos citados. Si un dato no está, indícalo como `[NO DETERMINADO]` o simplemente no lo incluyas. No rellenes huecos con conocimiento genérico de redes inalámbricas.
2. **Mantén consistencia técnica.** Usa las mismas fórmulas, unidades (m, MHz, dBm, dBi, dB), nombres de parámetros y terminología que aquí (§8, §9, §18). Si este documento dice que FSPL usa `−27.55` con d en metros, no escribas otra forma sin la aclaración de equivalencia.
3. **Diferencia siempre implementación real de trabajo futuro.** Usa los marcadores (§0) y la clasificación A–E. Nunca presentes como funcionando algo que está en §15 (limitaciones) o en §16 como PARCIAL/NO IMPLEMENTADO/PLANEADO.
4. **Usa la terminología técnica correctamente.** RSSI ≠ SNR ≠ SINR; estimación predictiva ≠ simulación electromagnética; "propuesta de optimización de canales" ≠ "asignación automática"; "AP asociado (dinámico)" ≠ "asociación persistente".
5. **Mantén coherencia entre arquitectura, funcionalidades, pruebas y resultados.** Si en Arquitectura dices que `engine/` no importa UI, no describas una función que lo haga. Si dices 955 pruebas, usa ese número y su fecha; no lo mezcles con estados anteriores sin indicarlo.
6. **Reproduce las limitaciones con honestidad** (§15): el documento técnico debe ser técnicamente honesto; el mérito está en el rigor, no en prometer más de lo que hay.
7. **No alteres los hechos al redactar.** Puedes reorganizar, resumir y redactar con buen estilo académico, pero no cambies valores, fórmulas, resultados ni alcances. Si necesitas matizar algo, usa los marcadores.
8. **Cita la trazabilidad** cuando corresponda (§20): el documento académico gana credibilidad si las afirmaciones apuntan a módulos/funciones/pruebas concretas.
9. **Respecto al estado del repositorio:** distingue entre lo commiteado (F1–F15) y el trabajo sin commitear (F15.1/F15.2, §11). No afirmes que todo está commitado.
10. **Las cifras de rendimiento** (§10.3) y los conteos de pruebas (§12) son mediciones reales; si las usas, respétalas y añade su contexto (fecha, escenario, hardware [NO DETERMINADO]).

Cuando el documento final esté redactado, ninguna sección debería contener capacidades que un usuario no pueda reproducir siguiendo el flujo de §17.
