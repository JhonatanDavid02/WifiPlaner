# Arquitectura — Wi-Fi Planner V1

## Visión general

Wi-Fi Planner es un sistema de diseño y simulación visual de redes Wi-Fi.
La V1 establece la **fundación**: dominio, geometría en metros, motor RF
centralizado, configuración centralizada, pruebas y documentación.

**Fase 8 (actual):** geometría arquitectónica — `Space` (zonas) y
`Opening` (puertas/ventanas/pass-through) sobre paredes. Los openings
son **muro-relativos** (offsets métricos sobre `wall.segment.start`) y
su cruce en el rayo **sustituye** la atenuación de la pared por el
override del hueco (0 dB por defecto; nunca suma). Los espacios son
organizativos: no participan en la propagación. El editor gana la
herramienta `Zona` y la creación de aperturas desde la pared
seleccionada; `persistence/` añade claves opcionales `spaces`/`openings`
dentro de `floors[]` manteniendo `schema_version = 1`.

**Fase 6 + 6.1:** persistencia local de proyectos en **JSON**,
auditada y endurecida (F6.1). El `Project` es la única fuente de verdad
editable: se guarda a archivo y se regenera todo lo derivado
(simulación, heatmap, UI) al abrir. La capa `persistence/` aísla el
formato del dominio y de la UI, trata el archivo como **entrada no
confiable** (incluido el parser) y escribe de forma atómica y durable.

**Fase 5:** editor 2D + **heatmap multi-AP** sobre el mismo
`CoverageGrid`. Cada AP se evalúa con `simulate_coverage` y se combinan
con `combine_results` (mejor RSSI por punto; **no** es interferencia).
El heatmap es una **estimación predictiva** del modelo configurado;
no es una simulación electromagnética completa.

## Separación de capas

```
┌─────────────────────────────────────────────┐
│  UI (Fase 3–10)                             │
│  editor 2D (Tkinter), heatmap (Pillow),     │
│  viewport (metros→píxeles), paneles,        │
│  menú Archivo (Nuevo/Abrir/Guardar)         │
│  CONSUME SimulationResult / LinkEvaluation  │
│  NUNCA serializa el proyecto por su cuenta  │
│  NUNCA contiene fórmulas de RF              │
├─────────────────────────────────────────────┤
│  persistence/  (Fase 6, 6.1, 7, 8)          │
│  Project ↔ JSON (schema_version), validación│
│  de entrada no confiable, escritura atómica │
│  Importa core/ (+ engine solo para validar  │
│  límites del grid). NO importa UI           │
├─────────────────────────────────────────────┤
│  engine/  (motor RF)                       │
│  propagation, link_budget (FSPL+Lm+SNR),    │
│  classifier (calidad/SOM/SNR/diagnóstico),  │
│  obstacles, intersection, coverage_grid,    │
│  simulator, combine                         │
│  Funciones puras, deterministas, testeables │
│  NO importa tkinter ni PIL                 │
├─────────────────────────────────────────────┤
│  core/  (modelo de dominio)                │
│  geometry (metros), space, wall, material,  │
│  band, radio, channel (canales F10),        │
│  access_point, client, project, result      │
│  NO contiene fórmulas de RF                │
│  NO importa UI ni persistence              │
├─────────────────────────────────────────────┤
│  config/  (configuración central)          │
│  default_config.yaml: umbrales, radios,     │
│  bandas, materiales (+ campos F7)           │
│  NO hay números mágicos en el código        │
├─────────────────────────────────────────────┤
│  tests/  (pruebas del motor + UI sin Tk)   │
│  pytest, deterministas, sin abrir ventana   │
│  golden data del DOCX legacy               │
└─────────────────────────────────────────────┘
```

## Responsabilidades por módulo

### `core/`
Representa el dominio. Entidades puras, sin lógica de RF ni de UI.

| Módulo | Responsabilidad |
|---|---|
| `geometry.py` | `Point2D`, `Segment2D`, `Rect` — **unidades: metros**; `Rect.edge_segments` (F9) |
| `band.py` | `FrequencyBand` — 2.4 / 5 / 6 GHz desde V1 |
| `channel.py` | **Fase 10:** `WifiChannel` (número lógico + centro derivado) y catálogo por familia — `channels_for_frequency`, `channel_numbers_for_frequency`, `channel_for_band`, `default_channel`, `validate_channel_config` (triple banda/canal/ancho), `MAX_CHANNEL_NUMBER = 233` (decisión BQ: **fuente única**; nadie más tabular frecuencias) |
| `material.py` | `Material` — atenuación por banda, valores centralizados |
| `radio.py` | `RadioConfiguration` — P_tx, ganancias, pérdidas, Lm, sensibilidad, **ruido/ancho/estándar (F7)** + `allowed_channel_widths_mhz`, `wifi_generation` |
| `access_point.py` | `AccessPoint` — posición en metros + configuración de radio + **`band_id`/`channel` por AP (F10)**: invariante canal ⇒ banda, canal ∈ [1, 233] (decisión BS) |
| `client.py` | `ClientDevice` — posición + sensibilidad |
| `wall.py` | `Wall`, `Opening` — geometría + material + espesor. **F8:** `Opening` muro-relativo con validación (límites BK), `OPENING_KINDS`, `wall_point_at_offset`, `opening_segment`, `group_openings_by_wall` (orden canónico). **F9:** el scaffold de `Obstacle` se mudó a `core/obstacle.py` (un solo concepto) |
| `obstacle.py` | **Fase 9:** `Obstacle` (footprint `Rect` en metros, material obligatorio, `kind`, `attenuation_override_db`, `blocks_signal`) + `OBSTACLE_KINDS`, `MIN/MAX_OBSTACLE_SIZE_M`, `MAX_OBSTACLE_ATTENUATION_DB`, `DEFAULT_OBSTACLE_MATERIAL_ID` (decisión BL) |
| `space.py` | `Space`, `Floor` — zonas y pisos (`width_m`/`height_m`, `obstacles` en F9); `MIN_SPACE_SIZE_M` (F8) |
| `project.py` | `Project`, `CoverageThresholds` — contenedor raíz + umbrales (RSSI/SOM/calidad + `snr_target_db` + **`sinr_target_db` (F12)**, default 25.0, rango [-20, 60]) |
| `result.py` | `LinkEvaluation` (con `snr_db`/`noise_floor_dbm`) + **4 campos de interferencia F11 con default (decisión BX)**: `interference_evaluated`, `interference_dbm`, `interferer_count`, `dominant_interferer_ap_id` + **2 campos SINR F12 (CF)**: `sinr_db`, `sinr_meets_target` — información paralela; `rx_power_dbm`/`som_db`/`snr_db` intactos, `SimulationResult`, `QualityClass`, `Verdict` |

### `engine/`
Motor de cálculo. Funciones puras que reciben geometría, parámetros y
devuelven resultados. **La UI solo consume estos resultados.**

| Módulo | Responsabilidad |
|---|---|
| `propagation.py` | Longitud de onda y FSPL |
| `link_budget.py` | Presupuesto de enlace, SOM, SNR (`signal_to_noise_ratio`), `evaluate_link` (con `sinr_db`/`sinr_meets_target` desde F12) |
| `classifier.py` | Clasificación SOM / RSSI / calidad + `meets_snr_target`/`rf_diagnostic` (F7) + `meets_sinr_target`/`sinr_diagnostic` (F12, sin tocar las 4 salidas de F7) |
| `intersection.py` | Cruce trayecto ↔ segmento de pared (interior estricto) |
| `obstacles.py` | `trace_walls(..., openings=, obstacles=)` — atenuación por material/espesor, suma; **F8:** un cruce dentro de un hueco **sustituye** la pérdida del material por el override del hueco (decisión BG); `WallCrossing`/`CrossingLoss` llevan `opening_id`. **F9:** `obstacle_attenuation_db` (override sustituye material, BM), `trace_obstacles`, `_obstacle_candidates` (cruce interior estricto, un solo atravesamiento, BN), `ObstacleCrossing`/`ObstacleTraceResult.obstacles_crossed` y `CrossingLoss.obstacle_id` |
| `coverage_grid.py` | **Fase 4:** malla regular de puntos (metros), límites |
| `simulator.py` | `simulate_coverage` — un punto o el grid completo; valida ancho×banda (F7) y **canal×banda vía `channel_for_band` (F10)**, calcula stats con SNR (+ `sinr_stats_block` desde F12) y propaga `openings`/`obstacles` a `trace_walls` (F8/F9) |
| `combine.py` | Combinación de resultados multi-AP (Fase 5) con stats de SNR del ganador (F7, + bloque SINR del ganador en F12); **F11:** no cambia — sigue eligiendo mayor RSSI y recibe los resultados **ya anotados** con interferencia y SINR por la sesión (BX/CF) |
| `interference.py` | **Fase 11 (nuevo):** modelo espectral puro — `occupied_interval_mhz`, `spectral_overlap` (semiabiertos, ratio sobre el ancho menor, BY), `effective_interference_dbm` (PSD plano `P_rx + 10·log10(overlap/W)`, None si overlap=0, BZ), `dbm_to_mw`/`mw_to_dbm`/`aggregate_dbm` (suma lineal, None vacío, CA — única definición en el árbol), `SpectralEmission`/`emission_for_ap` (centro del catálogo F10), `annotate_interference` (reutiliza P_rx, agrupa por banda, dominante con empate ⇒ menor id, CB/CA) e `interference_summary` (CC). Sin hilos/caché (CE); SINR en `sinr.py` (CF) |
| `sinr.py` | **Fase 12 (nuevo):** fórmula única del SINR — `signal_to_interference_noise_ratio` (forma estable con el máximo, CF), `interference_plus_noise_dbm` (None ⇒ ruido exacto, CG), `_with_sinr`, `annotate_sinr` (reemplaza resultados **después** de F11 y **antes** de combinar), `sinr_stats_block` (6 claves, única definición). Sin caché/hilos, sin decisión de ganadores |

### `ui/` (Fase 3–12)
Presentación. Sin fórmulas RF; solo pintar, capturar eventos y llamar
al engine / `EditorSession`.

| Módulo | Responsabilidad |
|---|---|
| `session.py` | `EditorSession`: operaciones puras sobre `Project` (testeable sin Tk): editor + guardar/abrir/nuevo + dirty state + `heatmap_metric`/`apply_rf_settings` (F7) + **CRUD de `Space`/`Opening` (F8)** + **CRUD de `Obstacle` (F9)**: `add_obstacle`/`set_obstacle_properties`/`move_obstacle` (clamps, `replace` revalida el dominio, **invalidan heatmap y dirty** — BP), passthrough de `openings`/`obstacles` a `simulate_coverage` + **configuración RF por AP (F10)**: `set_ap_rf_config` (triple atómico validado en `core.channel`, dirty/invalidación solo con cambio real — BU) y `resolve_band_for_ap` (`ap.band_id` o la de la corrida o la activa — BS), usado por `run_heatmap`/`run_simulation` + **interferencia (F11)**: `_interference_context_aps` (vecinos con canal en la misma banda, CB), `_spectral_emissions`, anotación **antes** de combinar en `run_heatmap`/`run_simulation` con puerta `len(results) >= 2` + `ap.channel is not None` (BX/CB), métrica `interference` validada contra `HEATMAP_METRICS` del renderer (CC), `ap_interference_lines` (panel, solo datos reales) y header de `heatmap_stats_text` + **SINR (F12)**: `apply_rf_settings(..., sinr_target_db=)` opcional atómico (CH), `annotate_sinr` tras F11 en `run_heatmap`/`run_simulation` (CF), `_ap_evaluations` (helper compartido tras refactor de `ap_interference_lines`, salidas F11 idénticas), `ap_sinr_lines`, cabecera SINR en `heatmap_stats_text`/`client_rssi_lines`/`simulation_summary_text` y docstring de `set_heatmap_metric` |
| `viewport.py` | **Único** conversor metros ↔ píxeles (escala isotrópica) |
| `editor_canvas.py` | Canvas: capas floor → heatmap → spaces → **obstacles (F9)** → walls (con huecos) → APs → leyenda (RSSI, SNR, **Interferencia — F11** o **SINR — F12**); hit-test AP → cliente → openings → **obstacles** → paredes → espacios (F9); tools `Zona` y **`Objeto` con dos clics + preview (F8/F9)**; arrastre de obstáculo con clamp (F9); **etiqueta `CH n · w MHz` bajo el AP solo si tiene canal configurado (F10, BU)** |
| `coverage_renderer.py` | `SimulationResult` → imagen Pillow RGBA + leyenda + escalas; registro único `HEATMAP_METRICS = ("rssi", "snr", "interference", "sinr")` (CC + **F12, CF**) + escala/leyenda/rama de interferencia (`interference_to_color`, dirección invertida, `None` ⇒ «sin interferencia») + **escala/leyenda SINR (F12)**: alias de paradas de SNR con dirección directa, `sinr_to_color` (`None` ⇒ gris neutro), fila de leyenda con `sinr_target_db` y bloque de stats condicional; escalas `rssi`/`snr` (F7) |
| `app.py` | Ventana principal, **debounce ~150 ms** del heatmap, menú **Archivo** (Nuevo/Abrir/Guardar/Guardar como) y confirmación de cambios sin guardar; tecla `e` → tool Zona, tecla **`o` → tool Objeto (F9)**, Escape limpia trazos (F8/F9); **`properties.refresh()` tras simular y tras el heatmap (F11)** para que el bloque de interferencia del panel esté siempre al día |
| `panels/toolbar.py` | Herramienta (incl. **Zona** y **Objeto**, F8/F9), banda, resolución, toggle heatmap, selector de AP, **métrica RSSI/SNR/Interferencia/SINR y Config RF… (F7 + F11 + F12, `METRIC_LABEL_BY_ID`)**, **Dimensiones…** (F8 renombra el viejo `Espacio…`) |
| `panels/properties.py` | Propiedades del elemento + resumen simulación/heatmap + bloque RF global (F7, con **`Objetivo SINR` desde F12**) + **Espacio (nombre/función) y Apertura (tipo/offsets) + `+ Puerta`/`+ Ventana` desde la pared (F8)** + **marco Objeto: nombre/tipo/material/override `band_id=dB` (F9)** + **marco «Radio del AP»: banda/canal/ancho desde `core.channel`, frecuencia y estándar de solo lectura, Aplicar atómico con error controlado (F10, BU)** + **bloque «Interferencia» del AP (F11, CC) + líneas SINR (F12): `session.ap_sinr_lines` con datos reales o mensajes honestos de ausencia** |
| `dialogs/rf_dialog.py` | **F7:** diálogo de configuración RF (ruido, objetivos, estándar, ancho); **F12:** fila «Objetivo SINR (dB)» y callback de 6 elementos; captura `ValueError` |

### `persistence/` (Fase 6, endurecida en 6.1)
Representación externa del proyecto en **JSON**. Convierte
`Project → dict → archivo` y `archivo → Project` con validación estricta
(esquema, límites, NaN/Inf, booleans ≠ números, ids únicos, material
referenciado, ≥ 1 piso). El parser también se trata como no confiable
(`ValueError`/`RecursionError` ⇒ `ProjectFormatError`). No conoce
Tkinter ni simula; el dominio (`core/`) no sabe que existen archivos.

| Módulo | Responsabilidad |
|---|---|
| `json_project_repository.py` | `save_project` (revalida + `.tmp` + `fsync` + `os.replace`) / `load_project`, `project_to_dict` / `project_from_dict`, dispatch por `schema_version` (`_document_v1`; punto de extensión para futuras versiones), `ProjectFormatError`, límites; **F8:** `spaces`/`openings` por piso (claves opcionales al leer, siempre escritas) con validación estricta (pared existente, offsets dentro de la pared, límites BJ); **F9:** `obstacles` por piso (misma fórmula, límites BO: material del catálogo, kind soportado, rect ≤ 1000 m, override [0, 200], `MAX_OBSTACLES = 5000`); **F10:** `access_points[].band_id` opcional al leer (ausente ⇒ `None` ⇒ banda activa; archivos F1–F9 sin migración), siempre escrito al guardar; `channel` explícito exige `band_id` existente y canal del catálogo de esa banda; la frecuencia central **nunca** se persiste (BR); `schema_version` sigue en 1 |
| `EditorState` | Preferencias persistibles del editor: banda activa y resolución del grid |

### `config/`
Configuración centralizada en YAML. Radio, umbrales, bandas y materiales
viven aquí. El código los recibe por parámetro o los carga con `load_config()`.
Los defaults de la radio y de los umbrales (incluidos los campos F7:
`noise_floor_dbm`, `channel_width_mhz`, `wifi_standard`,
`snr_target_db`, y el F12 `sinr_target_db`) están **centralizados en
`core/`**: el YAML y el
fallback del loader referencian esas instancias, sin literales
duplicados.

### `tests/`
Pruebas deterministas con pytest. Incluyen golden data extraída del DOCX
legacy (Tablas 2 y 3) y pruebas de grid/heatmap **sin abrir Tkinter**.

## Flujo de datos (editor + paredes + heatmap)

```
UI (metros)                    engine                              UI (píxeles)
┌──────────┐   Project, AP    ┌────────────────────────────┐        ┌────────────┐
│ Editor   │ ───────────────► │ 1. CoverageGrid.points()   │        │ Heatmap    │
│ (canvas) │   band, res.     │ 2. trace_walls(AP → punto) │        │ (viewport) │
│ + walls  │                  │ 3. L_obstacles             │   SimulationResult
└──────────┘                  │ 4. FSPL + link budget      │ ─────► │ rx, quality│
                              │ 5. SOM + clasificación     │        │ verdict    │
                              └────────────────────────────┘        └────────────┘
```

1. El editor construye un `Project` con geometría en **metros**.
2. `EditorSession.run_heatmap()` construye el `CoverageGrid` y llama a
   `engine.simulate_coverage(..., sample_points=grid.points(), walls=floor.walls, openings=floor.openings, obstacles=floor.obstacles)`.
3. Por cada punto, `trace_walls` (paredes + openings + obstáculos) +
   link budget canónico (sin fórmulas nuevas en la UI).
4. `ui.coverage_renderer.build_heatmap_image` pinta cada evaluación como
   celda centrada en su punto, alineada al `Viewport` (metros → píxeles
   solo vía `Viewport`).
5. Capas del Canvas: suelo/rejilla → heatmap → spaces → **obstacles
   (F9)** → paredes → APs/clientes → leyenda. El hit-test del editor
   **no** depende de la capa heatmap.
6. La UI **nunca** recalcula FSPL, SOM, intersecciones ni umbrales.
7. **Fase 10:** antes de simular, cada AP resuelve su banda con
   `resolve_band_for_ap` (`ap.band_id` → banda de la corrida → banda
   activa). El **canal** del AP no entra en el cálculo: solo se valida
   contra su banda (`channel_for_band`) y se muestra como metadata
   (panel y etiqueta del lienzo). Heatmap con APs de banda mixta ⇒
   `combine_results` rechaza (contrato F5) y el error queda visible en
   el panel.
8. **Fase 11 (interferencia, paralela):** si el AP deseado tiene canal,
   la sesión simula también a los vecinos con canal de **su misma banda**
   (`_interference_context_aps`) y llama a
   `engine.interference.annotate_interference(resultados, emisiones)`
   que, **reutilizando los P_rx ya calculados**, anota cada evaluación
   con su `interference_dbm` agregado (dominante, recuento). La anotación
   ocurre **antes** de `combine_results` (el ganador lleva sus datos) y
   solo con `len(results) >= 2` (los proyectos/APs sin canal no pagan
   coste ni cambian). La UI pinta la métrica `interference` y el panel
   del AP vía `ap_interference_lines`.
9. **Fase 12 (SINR, paralela):** en el mismo punto del flujo —
   **después** de la interferencia y **antes** de combinar (CF) — la
   sesión llama a `engine.sinr.annotate_sinr(resultados, umbrales)`,
   que rellena `sinr_db`/`sinr_meets_target` con la fórmula única de
   `engine/sinr.py` (`None` de interferencia ⇒ SINR = SNR exacto, CG).
   La UI pinta la métrica `sinr` y el panel vía `ap_sinr_lines`. RSSI,
   SNR, interferencia, calidad y veredicto **no cambian**.

### `trace_walls` (responsabilidad clave)

```
trace_walls(source, target, walls, band_id, openings=(), obstacles=())
    -> ObstacleTraceResult
```

- Evalúa cada pared con `blocks_signal=True` contra el segmento
  AP → punto.
- Conserva **orden y detalle** por pared (`WallCrossing`).
- Total: `attenuation_db = Σ loss_db` (redondeado a 2 decimales).
- Determinista: empates de distancia se rompen por `wall.id`.
- **Fase 8:** si el cruce cae dentro de la unión de los openings de la
  pared (intervalo cerrado con ε, orden canónico `(start, id)`), la
  pérdida de ese cruce es `override(banda)` o 0 dB — **sustituye** a la
  del material (decisión BG). El cruce lleva `opening_id`. Un cruce en
  hueco no consulta el catálogo de materiales (6 GHz con hueco ⇒ 0 dB);
  los cruces sólidos siguen lanzando `MaterialAttenuationError`. Sin
  `openings` el resultado es idéntico al de Fase 2–7.
- **Fase 9:** los obstáculos con `blocks_signal=True` se evalúan con la
  misma primitiva contra sus cuatro bordes; ≥ 1 cruce interior ⇒ **un
  solo** atravesamiento con la distancia de entrada (decisión BN). El
  `ObstacleTraceResult` añade `obstacles_crossed` (`ObstacleCrossing`
  con `obstacle_id` en el detalle) y la suma fusiona paredes +
  obstáculos en orden `(distancia, tipo, id)`. La pérdida de cada
  obstáculo es `override(banda)` si existe, si no la de referencia del
  material sin espesor (decisión BM); sin `obstacles` el resultado es
  **byte-idéntico** al de Fase 2–8.

### Heatmap (Fase 4–5, métrica en 7)

- **Fase 5:** selector `AP:` en toolbar → `Todos los AP` (combinado) o
  un AP individual. El combinado itera `simulate_coverage` sobre el
  **mismo** `CoverageGrid` y fusiona con `combine_results` (mejor RSSI
  por punto; empate → menor `access_point_id`).
- **Fase 7:** selector `Métrica:` → `RSSI` (default) o `SNR`. Es una
  vista sobre el mismo `SimulationResult` (invalida el heatmap pero no
  marca `dirty` ni se persiste); la leyenda, el título, la escala de
  color y las stats cambian con la métrica.
- **Fase 11:** selector `Métrica:` añade `Interferencia` (id
  `interference`, fuera del enum F7 congelado — se valida contra
  `HEATMAP_METRICS` del renderer, decisión CC). Escala invertida
  (más alto = peor, `None` ⇒ color de «sin interferencia»), leyenda
  propia y stats con el resumen agregado. La anotación se hace en
   cualquier corrida con contexto (selector individual con APs vecinos
   con canal, o «Todos los AP» con ≥ 2 resultados), no solo con esa
   métrica visible.
- **Fase 12 (SINR, paralela):** selector `Métrica:` añade `SINR`
   (id `sinr`, registro `HEATMAP_METRICS` de 4 — el enum F7 sigue
   congelado). `annotate_sinr` corre **después** de la interferencia y
   **antes** de combinar (CF) en toda corrida con contexto; la escala
   usa las mismas paradas que SNR con dirección directa (mayor = mejor,
   `None` ⇒ gris), la leyenda añade la fila con `sinr_target_db` y las
   stats muestran el bloque SINR. SINR jamás cambia el ganador (MAX
   RSSI intacto).
- Invalidación + debounce ~150 ms (F4) reutilizada en F5/F7: mover AP,
  banda, pared, dimensión, resolución, agregar/eliminar AP, cambiar
  selector de AP o métrica.
- `%` de cobertura: denominador = **puntos totales del grid**.
- Dominancia (`ap_dominance_percent`): puntos dominados por cada AP ÷
  total (suma ≈ 100 %). Stats de SNR (min/max/avg/objetivo/ratio) del
  AP ganador por punto.
- Disclaimer: estimación predictiva, no simulación EM.
- 6 GHz: error visible (`MaterialAttenuationError`), sin fallback.
- **F11:** hay información de interferencia **paralela** (nuevos campos
  de `LinkEvaluation`, decisión BX) pero **no** CCA/CSMA,
  roaming ni optimización de canales (decisión CD): el canal configurado
  en F10 sigue sin cambiar ninguna métrica histórica (A/B byte-idéntico;
  regresión F9/F10 intactas). El SINR que F11 dejó previsto se añade en
  F12 como capa paralela (decisión CF), sin alterar nada de lo anterior.

### Persistencia (Fase 6)

```
             ┌──────────────┐
             │   Project    │  fuente de verdad (metros)
             └──────┬───────┘
        ┌───────────┴───────────┐
        ▼                       ▼
  persistence/              engine/
   (JSON, v1)            simulate_coverage
        │                       │
        ▼                       ▼
   archivo .json         SimulationResult
                               │
                               ▼
                         UI (heatmap/paneles)
```

- El archivo guarda **solo** el `Project` + `EditorState` (banda y
  resolución). Al abrir: `JSON → Project → simulate → UI`.
- `schema_version` obligatoria; incompatible ⇒ `ProjectFormatError`
  (error visible, proyecto actual intacto, sin carga parcial). El
  dispatch por versión (`_document_v1`) es el punto donde una futura
  v2 añadiría su lector/migración (F6.1 solo deja la preparación).
- Coordenadas siempre en metros (`x_m`/`y_m`); los píxeles solo existen
  en `Viewport`.
- Las paredes referencian materiales por id dentro del propio catálogo
  del proyecto (el archivo es autocontenido); se exige **≥ 1 piso**
  (simetría guardar/cargar).
- Escritura atómica y durable (`.tmp` + `fsync` + `os.replace`) y
  revalidación previa: no se deja un archivo que la app no pueda abrir,
  y un fallo de escritura no destruye el archivo anterior.
- Todo el JSON es **entrada no confiable**: validación de tipos
  (booleanos nunca pasan por números), NaN/Inf, límites de dimensiones,
  coordenadas, espesores, listas, strings, metadata, resolución del
  grid y tamaño de archivo; incluso los errores del parser
  (`ValueError`/`RecursionError`) se convierten en `ProjectFormatError`.
- Invariante de edición: **dimensiones + resolución ⇒ grid usable** se
  comprueba al cambiar cualquiera de los dos ⇒ el proyecto siempre es
  simulable y guardable.
- Al cambiar de documento la UI se limpia por completo (heatmap,
  selección, herramienta, arrastre, selector de AP): no queda estado
  residual del proyecto anterior.
- **No** se persisten: selección, herramienta, heatmap, resultados de
  simulación ni imágenes (se regeneran; ver `docs/decisions.md` AB–AT).
- **F7 (misma versión 1):** `radio` puede traer `noise_floor_dbm`,
  `channel_width_mhz`, `wifi_standard` y `thresholds` `snr_target_db`
  como claves **opcionales** (ausentes ⇒ defaults de `core/`): los
  archivos F6 abren sin migración (decisión AZ).
- **F8 (misma versión 1, decisión BE):** cada piso puede traer
  `spaces` y `openings` como claves **opcionales** (ausentes ⇒ listas
  vacías): los archivos F6/F7 abren sin migración. Al guardar se
  escriben **siempre**. Validación estricta: `wall_id` debe existir en
  el mismo piso, `end_offset_m` no puede exceder la longitud de la
  pared, offsets finitos, tipo en `OPENING_KINDS`, overrides en
  [0, 200] dB, ids únicos y límites BJ (`MAX_SPACES`,
  `MAX_OPENINGS`, `MAX_OPENINGS_PER_WALL`). Los espacios **no**
  deben caer dentro del rect del piso (decisión BJ).
- **F10 (misma versión 1, decisión BV):** cada AP puede traer
  `band_id` como clave **opcional** (ausente ⇒ `None` ⇒ banda activa):
  los archivos F1–F9 abren sin migración. Al guardar se escribe
  **siempre** (junto al `channel` ya existente). Validación al leer:
  `band_id` debe existir en `project.bands`; un `channel` explícito
  exige `band_id` y pertenecer al catálogo de esa banda
  (`core.channel`); la frecuencia central del canal **nunca** viaja en
  el archivo (se deriva al abrir).
- **F11 (misma versión 1, decisión CD):** la interferencia **no se
  persiste** — vive solo en memoria de resultados (`LinkEvaluation`).
  Ni `persistence/` ni el archivo mencionan `interference`; guardar,
  abrir y los archivos F1–F10 son byte-idénticos a los de F10.
- **F12 (misma versión 1, decisión CH):** `thresholds` puede traer
  `sinr_target_db` como clave **opcional** (ausente ⇒ default 25.0 de
  `core/`): los archivos F1–F11 abren sin migración. Al guardar se
  escribe **siempre** (validado [-20, 60] al leer). Los resultados
  derivados (`sinr_db`, `sinr_meets_target`, ratio) **nunca** se
  persisten; `schema_version` sigue en 1.

## Unidades

| Magnitud | Unidad |
|---|---|
| Coordenadas, distancias, espesores, resolución grid | **metros (m)** |
| Frecuencia | MHz (FSPL) / Hz (longitud de onda) |
| Potencia, sensibilidad | dBm |
| Ganancia | dBi |
| Pérdidas, FSPL, SOM, atenuación | dB |
| Área | m² |
| Píxeles | solo `ui/viewport.py` + Canvas |

Los píxeles **no existen** en `core/` ni `engine/`.

## Preparación para fases posteriores

- **Fase 2 (hecha):** trazado rayo-pared + `L_obstacles` real.
- **Fase 3 (hecha):** editor 2D Tkinter.
- **Fase 4 (hecha):** `CoverageGrid` + heatmap + leyenda + stats.
- **Fase 5 (hecha):** multi-AP — mismo grid, `combine_results`,
  selector Todos/AP, dominancia por AP, estadísticas combinadas.
- **Fase 6 (hecha):** persistencia local JSON — `Project` ↔ archivo,
  schema versionado, guardar/abrir/nuevo, dirty state.
- **Fase 6.1 (hecha):** endurecimiento de persistencia — parser duro,
  límites extremos, invariante dims/resolución, simetría guardar/cargar,
  fsync, limpieza de estado residual, dispatch por versión.
- **Fase 7 (hecha):** extensión RF básica — piso de ruido configurable,
  SNR + umbral de SNR, estándar Wi-Fi y ancho de canal (metadatos con
  validación ancho×banda), heatmap con métrica SNR, stats ampliadas,
  diagnóstico de cuatro cuadrantes, diálogo Config RF y claves
  opcionales en schema v1 (compatibilidad F6).
- **Fase 8 (hecha):** geometría arquitectónica — `Space` (zonas, sin
  RF), `Opening` muro-relativo (puertas/ventanas/pass-through) con
  semántica de **reemplazo** en `trace_walls`, editor (tool `Zona`,
  creación/edición de aperturas, hit-test, preview), claves opcionales
  `spaces`/`openings` en schema v1, tests de dominio/geometría/persistencia.
- **Fase 9 (hecha):** obstáculos y mobiliario — `Obstacle` con
  footprint rectangular (`core/obstacle.py`), pérdida con precedencia
  explícita override ≻ material sin escalar por espesor (BM), un solo
  atravesamiento por footprint y orden fusionado `(distancia, tipo, id)`
  (BN), editor (tool `Objeto`, tecla `o`, dos clics, arrastre con
  clamp, panel), claves opcionales `obstacles` en schema v1 (BO),
  regresión F8 byte-idéntica.
- **Fase 10 (hecha):** canales y configuración RF por AP —
  `core/channel.py` como fuente única del catálogo número ↔ centro
  derivado (BQ/BR), `AccessPoint.band_id + channel` con invariante
  canal ⇒ banda (BS), validación centralizada del triple (BT), panel
  «Radio del AP» + etiqueta de canal en el lienzo (BU), `band_id`
  opcional en schema v1 (BV), A/B y regresión F9 byte-idéntica; la
  física no cambió (BW).
- **Fase 11 (hecha):** interacción espectral e interferencia —
  `engine/interference.py` (ocupación `centro ± ancho/2`, solapamiento
  semiabierto BY, contribución con PSD plano BZ, agregación lineal con
  determinismo CA), 4 campos paralelos en `LinkEvaluation` anotados por
  la sesión **antes** de combinar (BX/CB), métrica `interference` +
  leyenda + bloque del panel (CC), sin persistencia nueva
  (CD), sin caché/hilos (CE); A/B de RSSI byte-idéntico y regresiones
  F9/F10 intactas.
- **Fase 12 (hecha):** SINR + diagnóstico RF — `engine/sinr.py` con la
  fórmula única y estable (CF), SINR = SNR sin I modelada (CG), campos
  `sinr_db`/`sinr_meets_target` + umbral `sinr_target_db` en diálogo/
  persistencia opcional con `>=` y default 25 dB (CH), métrica `sinr`
  en el registro de 4, escala/leyenda/stats/panel/clientes/resumen,
  `sinr_diagnostic` separado de `rf_diagnostic` y supersede acotado a
  los 2 tests frontera de F11 (CI); A/B byte-idéntico y regresiones
  F9/F10/F11 intactas.
- **Futuro:** edición de extremos de pared, CAD (snaps, snaps
  angulares, booleanos); CCA/CSMA y optimización de canales siguen
  fuera de alcance.
- **Futuro 3D:** `Floor.elevation_m` ya existe; geometría 2D no cambia.
- **Otras bases de datos / API / nube:** la capa `persistence/` es el
  punto de sustitución sin tocar `core/` ni `engine/`.
