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
│  UI (Fase 3–8)                              │
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
│  band, radio (ruido/ancho/estándar F7),     │
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
| `material.py` | `Material` — atenuación por banda, valores centralizados |
| `radio.py` | `RadioConfiguration` — P_tx, ganancias, pérdidas, Lm, sensibilidad, **ruido/ancho/estándar (F7)** + `allowed_channel_widths_mhz`, `wifi_generation` |
| `access_point.py` | `AccessPoint` — posición en metros + configuración de radio |
| `client.py` | `ClientDevice` — posición + sensibilidad |
| `wall.py` | `Wall`, `Opening` — geometría + material + espesor. **F8:** `Opening` muro-relativo con validación (límites BK), `OPENING_KINDS`, `wall_point_at_offset`, `opening_segment`, `group_openings_by_wall` (orden canónico). **F9:** el scaffold de `Obstacle` se mudó a `core/obstacle.py` (un solo concepto) |
| `obstacle.py` | **Fase 9:** `Obstacle` (footprint `Rect` en metros, material obligatorio, `kind`, `attenuation_override_db`, `blocks_signal`) + `OBSTACLE_KINDS`, `MIN/MAX_OBSTACLE_SIZE_M`, `MAX_OBSTACLE_ATTENUATION_DB`, `DEFAULT_OBSTACLE_MATERIAL_ID` (decisión BL) |
| `space.py` | `Space`, `Floor` — zonas y pisos (`width_m`/`height_m`, `obstacles` en F9); `MIN_SPACE_SIZE_M` (F8) |
| `project.py` | `Project`, `CoverageThresholds` — contenedor raíz + umbrales (RSSI/SOM/calidad + `snr_target_db`) |
| `result.py` | `LinkEvaluation` (con `snr_db`/`noise_floor_dbm`), `SimulationResult`, `QualityClass`, `Verdict` |

### `engine/`
Motor de cálculo. Funciones puras que reciben geometría, parámetros y
devuelven resultados. **La UI solo consume estos resultados.**

| Módulo | Responsabilidad |
|---|---|
| `propagation.py` | Longitud de onda y FSPL |
| `link_budget.py` | Presupuesto de enlace, SOM, SNR (`signal_to_noise_ratio`), `evaluate_link` |
| `classifier.py` | Clasificación SOM / RSSI / calidad + `meets_snr_target` y diagnóstico `rf_diagnostic` (F7) |
| `intersection.py` | Cruce trayecto ↔ segmento de pared (interior estricto) |
| `obstacles.py` | `trace_walls(..., openings=, obstacles=)` — atenuación por material/espesor, suma; **F8:** un cruce dentro de un hueco **sustituye** la pérdida del material por el override del hueco (decisión BG); `WallCrossing`/`CrossingLoss` llevan `opening_id`. **F9:** `obstacle_attenuation_db` (override sustituye material, BM), `trace_obstacles`, `_obstacle_candidates` (cruce interior estricto, un solo atravesamiento, BN), `ObstacleCrossing`/`ObstacleTraceResult.obstacles_crossed` y `CrossingLoss.obstacle_id` |
| `coverage_grid.py` | **Fase 4:** malla regular de puntos (metros), límites |
| `simulator.py` | `simulate_coverage` — un punto o el grid completo; valida ancho×banda (F7), calcula stats con SNR y propaga `openings`/`obstacles` a `trace_walls` (F8/F9) |
| `combine.py` | Combinación de resultados multi-AP (Fase 5) con stats de SNR del ganador (F7) |

### `ui/` (Fase 3–9)
Presentación. Sin fórmulas RF; solo pintar, capturar eventos y llamar
al engine / `EditorSession`.

| Módulo | Responsabilidad |
|---|---|
| `session.py` | `EditorSession`: operaciones puras sobre `Project` (testeable sin Tk): editor + guardar/abrir/nuevo + dirty state + `heatmap_metric`/`apply_rf_settings` (F7) + **CRUD de `Space`/`Opening` (F8)** + **CRUD de `Obstacle` (F9)**: `add_obstacle`/`set_obstacle_properties`/`move_obstacle` (clamps, `replace` revalida el dominio, **invalidan heatmap y dirty** — BP), passthrough de `openings`/`obstacles` a `simulate_coverage` |
| `viewport.py` | **Único** conversor metros ↔ píxeles (escala isotrópica) |
| `editor_canvas.py` | Canvas: capas floor → heatmap → spaces → **obstacles (F9)** → walls (con huecos) → APs → leyenda (RSSI o SNR); hit-test AP → cliente → openings → **obstacles** → paredes → espacios (F9); tools `Zona` y **`Objeto` con dos clics + preview (F8/F9)**; arrastre de obstáculo con clamp (F9) |
| `coverage_renderer.py` | `SimulationResult` → imagen Pillow RGBA + leyenda + stats; escalas `rssi`/`snr` (F7, parámetro `metric`) |
| `app.py` | Ventana principal, **debounce ~150 ms** del heatmap, menú **Archivo** (Nuevo/Abrir/Guardar/Guardar como) y confirmación de cambios sin guardar; tecla `e` → tool Zona, tecla **`o` → tool Objeto (F9)**, Escape limpia trazos (F8/F9) |
| `panels/toolbar.py` | Herramienta (incl. **Zona** y **Objeto**, F8/F9), banda, resolución, toggle heatmap, selector de AP, **métrica RSSI/SNR y Config RF… (F7)**, **Dimensiones…** (F8 renombra el viejo `Espacio…`) |
| `panels/properties.py` | Propiedades del elemento + resumen simulación/heatmap + bloque RF global (F7) + **Espacio (nombre/función) y Apertura (tipo/offsets) + `+ Puerta`/`+ Ventana` desde la pared (F8)** + **marco Objeto: nombre/tipo/material/override `band_id=dB` (F9)** |
| `dialogs/rf_dialog.py` | **F7:** diálogo de configuración RF (ruido, objetivos, estándar, ancho); captura `ValueError` |

### `persistence/` (Fase 6, endurecida en 6.1)
Representación externa del proyecto en **JSON**. Convierte
`Project → dict → archivo` y `archivo → Project` con validación estricta
(esquema, límites, NaN/Inf, booleans ≠ números, ids únicos, material
referenciado, ≥ 1 piso). El parser también se trata como no confiable
(`ValueError`/`RecursionError` ⇒ `ProjectFormatError`). No conoce
Tkinter ni simula; el dominio (`core/`) no sabe que existen archivos.

| Módulo | Responsabilidad |
|---|---|
| `json_project_repository.py` | `save_project` (revalida + `.tmp` + `fsync` + `os.replace`) / `load_project`, `project_to_dict` / `project_from_dict`, dispatch por `schema_version` (`_document_v1`; punto de extensión para futuras versiones), `ProjectFormatError`, límites; **F8:** `spaces`/`openings` por piso (claves opcionales al leer, siempre escritas) con validación estricta (pared existente, offsets dentro de la pared, límites BJ); **F9:** `obstacles` por piso (misma fórmula, límites BO: material del catálogo, kind soportado, rect ≤ 1000 m, override [0, 200], `MAX_OBSTACLES = 5000`) |
| `EditorState` | Preferencias persistibles del editor: banda activa y resolución del grid |

### `config/`
Configuración centralizada en YAML. Radio, umbrales, bandas y materiales
viven aquí. El código los recibe por parámetro o los carga con `load_config()`.
Los defaults de la radio y de los umbrales (incluidos los campos F7:
`noise_floor_dbm`, `channel_width_mhz`, `wifi_standard`,
`snr_target_db`) están **centralizados en `core/`**: el YAML y el
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
- Invalidación + debounce ~150 ms (F4) reutilizada en F5/F7: mover AP,
  banda, pared, dimensión, resolución, agregar/eliminar AP, cambiar
  selector de AP o métrica.
- `%` de cobertura: denominador = **puntos totales del grid**.
- Dominancia (`ap_dominance_percent`): puntos dominados por cada AP ÷
  total (suma ≈ 100 %). Stats de SNR (min/max/avg/objetivo/ratio) del
  AP ganador por punto.
- Disclaimer: estimación predictiva, no simulación EM.
- 6 GHz: error visible (`MaterialAttenuationError`), sin fallback.
- **No** hay interferencia, SINR, roaming ni optimización de canales.

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
- **Futuro:** canales/interferencia, edición de extremos de pared,
  CAD (snaps, snaps angulares, booleanos).
- **Futuro 3D:** `Floor.elevation_m` ya existe; geometría 2D no cambia.
- **Otras bases de datos / API / nube:** la capa `persistence/` es el
  punto de sustitución sin tocar `core/` ni `engine/`.
