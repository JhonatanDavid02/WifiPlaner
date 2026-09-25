# Decisiones técnicas — Wi-Fi Planner V1

Este documento registra las decisiones aprobadas y las discrepancias
encontradas entre el código legacy, el DOCX y el XLSX. Ninguna
discrepancia se resolvió de forma silenciosa.

---

## Decisiones aprobadas

### Decisión A — `d_max` histórico, no geométrico

- **Decisión:** conservar como referencia histórica las distancias del
  DOCX/v1/v2: **3.80 / 4.88 / 5.42 / 5.58 m**.
- **Razón:** son las distancias que aparecen en el informe académico
  (Tabla 3) y en `calculo_wifi_biblioteca.py` y `CalculoWifi2.py`.
- **Las distancias divergentes de v3/v4** (5.72 / 8.92 / 6.87 / 9.65 m)
  **quedan congeladas como legacy** en
  `tests/fixtures/golden_data.LEGACY_V3_V4_DISTANCIAS`.
- **Importante:** `d_max` **NO** es la base geométrica del nuevo
  simulador. El futuro simulador calculará distancias reales con
  coordenadas en metros (`Point2D.distance_to`).

### Decisión B — Fade margin (`L_m`)

- **Decisión:** `L_m = 10 dB` por defecto, **configurable**.
- **Razón:** el DOCX y el XLSX incluyen `L_m = 10 dB` en el presupuesto
  de enlace. Las versiones v3/v4 lo omitían (modo "demo simplificado").
- **Para reproducir legacy v3/v4:** `fade_margin_db = 0.0`.

### Decisión C — Comparación RSSI estricta

- **Decisión:** `P_rx > −67 dBm` (operador **estricto** `>`, no `>=`).
- **Razón:** el DOCX y las versiones v3/v4 usan `>`. Solo `CalculoWifi2.py`
  (v2) usaba `>=`. Se adopta la mayoría + DOCX.
- Centralizado en `CoverageThresholds.rssi_target_dbm` y
  `engine.classifier.meets_rssi_target`.

### Decisión D — Umbrales SOM

- **Decisión:**
  - `SOM ≥ 20 dB` → APROBADO
  - `10 ≤ SOM < 20 dB` → RIESGO
  - `SOM < 10 dB` → FALLIDO
- **Razón:** coincide con DOCX, v1, v3, v4. `CalculoWifi2.py` (v2) usaba
  una variante parametrizada con `>` estricto (SOM = 20 exacto caía a
  RIESGO); se descarta a favor de `≥` (DOCX).
- Centralizado en `CoverageThresholds`.

### Unidades físicas en metros

- Todas las coordenadas de `core/geometry` y de entidades (AP, cliente,
  pared, espacio) están en **metros**.
- Los píxeles no existen en `core/` ni `engine/`. Pertenecen al futuro
  viewport/UI.
- `Project.units` está restringido a `"m"`; otras unidades lanzan
  `ValueError`.

### Materiales como estimaciones configurables

- Los valores de atenuación (drywall 3/4 dB, etc.) son **estimaciones de
  referencia**, no verdades físicas universales.
- Están centralizados en `config/default_config.yaml` y
  `core.material.default_materials()`.
- Son editables y extensibles sin tocar el motor.

### Legacy congelado

- Los 4 scripts legacy (`calculo_wifi_biblioteca.py`, `CalculoWifi2.py`,
  `CODIGO(Interactivo).py`, `CalculadoraWLAN_Visual.py`) **no se
  modifican**. Funcionan como referencia histórica y de validación.
- El commit base de Git (`baseline: legacy project state...`) permite
  volver al estado anterior en cualquier momento.

### `d_max` no es geometría

- El nuevo simulador calcula distancias reales entre `Point2D`.
- `d_max` solo se usa en la golden data para validar que el motor
  reproduce los resultados del DOCX.

### 6 GHz preparada, no simulada aún

- `FrequencyBand` y la configuración incluyen `band_6` (6135 MHz).
- Los materiales V1 solo tienen atenuación para `band_2_4` y `band_5`.
  Consultar `band_6` en un material lanza `MaterialAttenuationError`.
- Esto es intencional: no se inventan valores de atenuación para 6 GHz.
- **Fase 2:** `wall_attenuation_db` y `trace_walls` propagan esa
  excepción de forma explícita; no hay fallback 5 → 6 GHz.

---

## Decisiones Fase 2 (geometría y paredes)

### Decisión E — EPSILON geométrico centralizado

- **Decisión:** `EPSILON_GEOMETRY = 1e-9` en `core/geometry.py`.
- **Razón:** única tolerancia para intersecciones; evita comparaciones
  exactas de float. Parámetros `t`/`u` normalizados en [0, 1] usan la
  misma epsilon (1e-9 ≈ milímetros de margen en escalas de edificio
  se tratan como "en el extremo").
- `engine/intersection.py` la importa; no se redefine en otro módulo.

### Decisión F — Cruce interior estricto (extremos no cuentan)

- **Decisión:** solo cuenta la intersección si
  `ε < t < 1−ε` **y** `ε < u < 1−ε` (parámetros de trayecto y pared).
- **Razón:**
  - Tocar un extremo de la pared no debe provocar doble conteo en
    esquinas compartidas (dos paredes, un mismo punto).
  - AP o punto exactamente sobre una pared no "cruza" esa pared
    (t = 0 o t = 1).
- **Comportamiento en esquina:** un trayecto que pasa exactamente por
  la esquina compartida de una L cuenta **0** paredes (ambas tocan
  extremo). Un trayecto que cruza el interior de ambas cuenta **2**.

### Decisión G — Paralelos y colineales no cuentan

- **Decisión:** `|path × wall| ≤ ε` ⇒ paralelo o colineales ⇒ sin cruce.
- **Razón:** sin cruce propio único y determinista; una pared alineada
  con el trayecto no se "atraviesa" de forma unívoca en el modelo de
  segmentos de espesor cero.

### Decisión H — Orden reproducible del trazado

- **Decisión:** paredes cruzadas se ordenan por
  `(distancia_desde_origen, wall.id)`.
- **Razón:** el detalle y el total deben ser reproducibles ante empates
  (p. ej. dos paredes en el mismo punto de cruce).

### Decisión I — Escalado lineal de espesor

- **Decisión:**
  `L = L_ref(banda) × (espesor_actual / espesor_referencia)`
- **Razón:** modelo sencillo, configurable y coherente con el catálogo
  de Fase 1 (`thickness_default_m` + `attenuation_db`).
  Si `thickness_m = None`, la pared usa el espesor de referencia
  (`L = L_ref`); la mayoría de paredes "de catálogo" no cambian.
- **Advertencia:** aproximación de ingeniería para predicción V1,
  **NO** simulación electromagnética. No se afirma relación lineal
  física universal (p. ej. no se asume "10 cm = 10 dB" salvo que el
  dato de referencia lo diga).
- Validaciones: espesor actual > 0, espesor ref > 0, material con
  datos para la banda.

### Decisión J — Comportamiento 6 GHz sin datos

- **Decisión:** `MaterialAttenuationError` explícita (misma excepción
  de Fase 1) al consultar `wall_attenuation_db` / `trace_walls` /
  `simulate_coverage(walls=...)` con `band_6`.
- **Razón:** no inventar atenuaciones; no convertir silenciosamente
  5 GHz → 6 GHz. El llamador decide si habilita datos de 6 GHz.

### Decisión K — Prioridad de fuentes de obstáculos en el simulador

- **Decisión:** si `simulate_coverage(..., walls=[...])` recibe paredes,
  el `L_obstacles` sale de `trace_walls` (geometría real). El mapa
  legado `obstacle_materials_by_point` (Fase 1) solo se usa si
  `walls is None`.
- **Razón:** la fuente de verdad en Fase 2+ es la geometría; la ruta
  de materiales explícitos se mantiene por compatibilidad con los
  tests y usos de Fase 1.

---

## Decisiones Fase 4 (heatmap y simulación espacial)

### Decisión L — Criterio de puntos del `CoverageGrid`

- **Decisión:**
  - Puntos en múltiplos enteros de `resolution_m` desde el origen
    `(0,0), (r,0), (2r,0), …`.
  - Si la dimensión **no** es múltiplo exacto, se añade un punto final
    en el borde (`width_m` o `height_m`) para no dejar una franja sin
    muestrear.
  - Todos los puntos cumplen `0 ≤ x ≤ width_m` e idem para y.
- **Ejemplo (aceptado):** piso 12 × 8 m a `0.50 m` → ejes
  0, 0.5, …, 12 (25 valores) × 0, 0.5, …, 8 (17 valores) = **425**
  puntos (25 × 17).
- **Límites de estabilidad V1:**
  - `resolution_m ≥ MIN_RESOLUTION_M = 0.05 m`
  - `point_count ≤ MAX_GRID_POINTS = 100_000`
  - Resolución y límites **configurables/documentedos**, no mágicos.
- **Razón:** malla regular, reproducible y con tope para no congelar
  la UI en la V1 (sin hilos/GPU complejos).

### Decisión M — Heatmap con UN solo AP

- **Decisión:** el heatmap V1 simula **un** AP: el seleccionado, o el
  primero del proyecto si no hay selección (`resolve_ap_for_heatmap`).
- **Razón:** Fase 5 combinará multi-AP con `combine_results`. Mezclar
  varios AP en el heatmap de Fase 4 sin combinar rompería la
  semántica de `SimulationResult` (un AP por evaluación).

### Decisión N — Disclaimer obligatorio de estimación

- **Decisión:** la UI y la documentación del heatmap deben indicar
  que es una **estimación predictiva** del modelo configurado
  (FSPL + presupuesto de enlace + atenuación de materiales),
  **no** una simulación electromagnética completa ni un sustituto
  de mediciones en sitio.
- **Razón:** honestidad del modelo; evita interpretar el mapa de
  color como medición real.

### Decisión O — Invalidación del heatmap

- **Decisión:** el heatmap se marca `heatmap_dirty` (y se borra de la
  capa Canvas) al cambiar: posición de AP, banda, resolución de grid,
  dimensiones del piso, añadir/eliminar pared o AP, material o
  espesor de pared. La App lo recalcula con **debounce ~150 ms**
  (sin hilos complejos en Fase 4).
- **Razón:** evitar mostrar un mapa obsoleto tras editar el modelo.
  Durante el recálculo se muestra «Calculando cobertura…».

### Decisión P — Denominador de % de cobertura

- **Decisión:** el porcentaje de cobertura usa como denominador
  **todos los puntos del grid** (no solo los que superan un umbral).
  Las clases se reportan como % del total de puntos evaluados.
- **Razón:** evita métricas engañosas (p. ej. 100 % “Excelente”
  sobre un subconjunto vacío o sesgado).

### Decisión Q — Capas del editor y heatmap

- **Decisión:** orden de pintado: suelo + rejilla → **heatmap** →
  paredes → APs / clientes → selección / leyenda. El hit-testing
  (selección) **no** se bloquea por la capa del heatmap (usa
  coordenadas de mundo, no ids del Canvas para decidir el target).
- **Razón:** el heatmap es decorativo/informativo; la interacción
  del editor no debe cambiar.

### Decisión R — 6 GHz en el heatmap

- **Decisión:** si el usuario elige `band_6` y hay paredes que
  requieren atenuación, el heatmap muestra un error comprensible
  (sin ocultar `MaterialAttenuationError`) y **no** pinta un mapa
  falso. No hay fallback 5 → 6 GHz.
- **Razón:** coherencia con decisiones J / 6 GHz de Fase 1–2.

### Decisión S — Clientes no sustituyen el grid

- **Decisión:** los clientes son puntos de interés **adicionales**
  (RSSI/SOM en su posición si coinciden o se aproximan a un punto
  del grid). El heatmap **siempre** se calcula sobre el
  `CoverageGrid` completo, no solo sobre clientes.
- **Razón:** el mapa de cobertura debe ser espacialmente continuo;
  unos pocos clientes dejarían huecos enormes.

### Decisión T — Piso de distancia cuando el punto está sobre el AP

- **Decisión:** si la distancia AP → punto es **exactamente 0**
  (punto del grid que cae en la posición del AP), `evaluate_link`
  evalúa FSPL con `MIN_FSPL_DISTANCE_M = 0.1 m` (piso numérico).
  La distancia reportada en `LinkEvaluation.distance_m` sigue siendo
  la geométrica real (0.0).
- **Razón:** `FSPL = 20·log10(d) + …` no está definida en `d = 0`
  (`path_loss_fspl_db` lanza `ValueError`, comportamiento correcto y
  congelado). El heatmap no puede fallar por un punto sobre el AP.
- **No se reescribe la fórmula FSPL:** el piso vive solo en
  `evaluate_link` y es documentado. Para `d > 0` no hay cambio.

---

## Decisiones Fase 5 (multi-AP y cobertura combinada)

### Decisión U — Combinación multi-AP = mejor RSSI por punto (no interferencia)

- **Decisión:** para cada punto del **mismo** `CoverageGrid`, el heatmap
  combinado (`HEATMAP_ALL_APS`) evalúa **todos** los APs con
  `simulate_coverage` y fusiona con `combine_results`: gana el mayor
  `rx_power_dbm`. **No** se modela interferencia (sin SINR, canal,
  ruido, roaming ni handoff).
- **Razón:** la combinación representa **cobertura disponible**. La
  interferencia es una fase futura; inventar fórmulas de SINR en V1
  sería incorrecto.

### Decisión V — Empates deterministas por `access_point_id`

- **Decisión:** si dos (o más) APs dan el **mismo** RSSI exacto en un
  punto, gana el `access_point_id` **menor** en orden lexicográfico
  (p. ej. `AP-001` antes que `AP-002`). La política vive en
  `engine.combine._better` y no depende del orden de llegada de un
  diccionario.
- **Razón:** reproducibilidad total ante empates (misma entrada →
  misma salida en cualquier orden de iteración).

### Decisión W — SOM / quality / veredicto = los del AP ganador

- **Decisión:** el resultado combinado **no** promedia SOM ni RSSI de
  varios APs. El punto toma **completo** la `LinkEvaluation` del AP con
  mejor RSSI (su distancia, su `path_loss`, su `obstacle_loss`, su SOM,
  su quality y su veredicto). El `access_point_id` de esa evaluación es
  el `best_ap_id` del punto.
- **Razón:** los clasificadores (calidad, SOM) son la autoridad y solo
  tienen sentido relativos a un enlace real AP→punto. Promediar SOM
  entre APs no tiene significado físico en este modelo.

### Decisión X — Mismo grid para todos los APs

- **Decisión:** todos los APs se evalúan sobre **una sola** lista de
  puntos (`CoverageGrid.points()` generada una vez). No se crea un
  grid por AP ni se re-muestrea.
- **Razón:** la correspondencia espacial punto↔punto debe ser exacta
  para poder elegir el mejor RSSI por coordenada.

### Decisión Y — Selector de AP en la UI

- **Decisión:** la toolbar expone un combo `AP:` con
  `Todos los AP` + `AP-001`, `AP-002`, …
  - **Todos los AP** → heatmap combinado (mejor RSSI por punto).
  - **AP-xxx** → heatmap exclusivamente de ese AP (reutiliza el mismo
    `CoverageGrid`, `simulate_coverage`, renderer y stats de F4).
- **Razón:** reutiliza la pila de F4 sin crear un segundo renderer ni
  un segundo motor. El valor interno es `HEATMAP_ALL_APS` o el id.

### Decisión Z — Dominancia por AP en estadísticas

- **Decisión:** el resultado combinado incluye en `stats`:
  - `ap_dominance_counts`: `{ap_id: puntos donde es el mejor}`
  - `ap_dominance_percent`: mismos conteos ÷ puntos totales del grid
  La suma de porcentajes ≈ 100 % (redondeo a 2 decimales). Se muestra
  en el panel de estadísticas del heatmap.
- **Razón:** permite ver qué AP “cubre” cada zona sin añadir una capa
  visual compleja (el heatmap sigue siendo de RSSI).

### Decisión AA — Invalidación multi-AP reutiliza la de F4

- **Decisión:** el sistema `heatmap_dirty` + debounce ~150 ms de F4 se
  extiende a F5: agregar/eliminar AP, cambiar el selector de AP, mover
  un AP, cambiar banda/resolución/paredes/dimensiones → invalidación
  → recálculo. **No** hay un segundo mecanismo de invalidación.
- **Razón:** un solo camino de frescura de datos; menos superficie de
  bugs.

---

## Fase 6 — Persistencia local

### Decisión AB — JSON local como representación externa del proyecto

- **Decisión:** la persistencia local utiliza **JSON** como
  representación externa del estado editable del proyecto. La
  simulación y el estado visual de la UI se **reconstruyen** a partir
  del proyecto: `JSON → Project → simulate → SimulationResult → UI`.
- **Razón:** legible, portable, versionable y sin dependencias extra.
  `Project` sigue siendo la única fuente de verdad; el archivo no
  guarda nada que pueda recalcularse.

### Decisión AC — Capa nueva `persistence/` (extensión 🟢)

- **Decisión:** la serialización vive en una capa propia
  (`persistence/`), no en `core/`, `engine/` ni en la UI.
  `core/` y `engine/` **no importan** `persistence/`; la UI solo pide
  “guardar/abrir” a `EditorSession`.
- **Problema actual:** no existía serialización; ponerla en la UI
  habría mezclado formato con presentación, y en `core/` habría
  acoplado el dominio a un archivo.
- **Beneficio:** el formato es reemplazable (Database/API/Cloud) sin
  tocar dominio ni motor; testable sin Tkinter.
- **Riesgo/alternativas descartadas:** `to_dict`/`from_dict` en cada
  entidad de `core/` (extiende el formato por 10 archivos) y
  serialización en `ui/` (contamina la presentación).

### Decisión AD — Documento autocontenido

- **Decisión:** el archivo guarda bandas, materiales, radio, umbrales,
  pisos, paredes, APs y clientes **del propio proyecto** (no hace
  falta `config/default_config.yaml` para abrirlo).
- **Razón:** si la configuración por defecto cambia después, un
  proyecto guardado sigue abriendo y simulando igual (round-trip
  determinista). Las paredes referencian materiales por
  `material_id` dentro de ese mismo catálogo (una sola tabla).

### Decisión AE — Coordenadas en metros

- **Decisión:** todas las coordenadas persistidas usan `x_m` / `y_m`
  en **metros**. La conversión metros ↔ píxeles sigue siendo
  responsabilidad exclusiva de `Viewport`.
- **Razón:** el archivo describe el dominio, no la pantalla; así se
  mantiene portabilidad entre resoluciones/monitores.

### Decisión AF — `schema_version` obligatoria

- **Decisión:** todo documento incluye `"schema_version": 1`. Una
  versión distinta (ausente, no entera o mayor) ⇒ `ProjectFormatError`
  con mensaje claro: no se carga nada parcial ni se sobrescribe el
  proyecto en memoria. **No** hay sistema de migraciones todavía.
- **Razón:** permite evolucionar a v2/v3 sin romper en silencio.

### Decisión AG — Qué se persiste y qué no

- **Se persiste:** `Project` completo (nombre, unidades, bandas,
  materiales, radio, umbrales, floors + dimensiones + paredes, APs,
  clientes, metadata) y `EditorState` (banda activa y resolución del
  grid) en una sección `editor` separada.
- **No se persiste:** selección, herramienta, heatmap visible,
  selector de AP, debounce, callbacks, coordenadas en píxeles,
  imágenes ni `SimulationResult`.
- **Razón:** esos son estado de UI/temporal; se regeneran al abrir.
  `SimulationResult` es derivado, jamás fuente de verdad.

### Decisión AH — Escritura atómica + revalidación previa

- **Decisión:** `save_project` revalida el documento completo antes de
  escribir y usa archivo temporal (`.tmp`) + `os.replace`. Si algo
  falla, el archivo anterior queda intacto y el temporal se elimina.
- **Razón:** nunca dejar en disco un proyecto que la propia aplicación
  no podría abrir; los fallos de escritura no destruyen datos.

### Decisión AI — El JSON es entrada no confiable

- **Decisión:** al abrir se valida: `schema_version`, secciones
  obligatorios, tipos, números finitos (sin NaN/Inf), dimensiones
  (0 < v ≤ 10 000 m), coordenadas (|v| ≤ 100 000 m), espesores
  (0 < t ≤ 10 m), ids no vacíos/únicos/duplicados, material
  referenciado existente, banda del `editor` existente, resolución que
  produzca un grid usable, listas dentro de límites y tamaño máximo de
  archivo (20 MB).
- **Razón:** un archivo dañado produce un error comprensible, nunca un
  estado parcial ni un cuelgue.

### Decisión AJ — Dirty state en `EditorSession`

- **Decisión:** `session.dirty` (False al abrir/guardar/nuevo) se
  marca en mutaciones de modelo o configuración persistible (mover/
  crear/eliminar pared, AP o cliente; material/espesor; dimensiones;
  banda; resolución) y **no** en acciones visuales (selección,
  herramienta, toggle heatmap, selector de AP, simular).
- **Razón:** el prompt “¿Desea guardar los cambios?” solo aparece
  cuando hay pérdidas reales posible.

### Decisión AK — Ámbito del formato v1

- **Decisión:** v1 serializa: `floors` (id, nombre, nivel, dimensiones,
  elevación, metadata, `walls`), `access_points`, `clients`, catálogos
  y configuración. **No** serializa aún `spaces`, `openings` y
  `obstacles` de `Floor`: el editor actual no los crea ni los edita.
- **Razón:** no persistir estructuras sin productor/consumidor evita
  formatos inventados; si el editor las incorpora, el esquema crece a
  v2 con esos campos (documentado como pendiente real).

---

## Fase 6.1 — Endurecimiento de persistencia

Auditoría de F6 sin cambiar el contrato del formato: `schema_version`
sigue siendo **1**. Solo se corrigieron debilidades comprobadas
empíricamente (sondas de parser, invariantes y residuales).

### Decisión AL — El documento exige ≥ 1 piso

- **Decisión:** `project.floors` debe contener al menos un piso;
  una lista vacía ⇒ `ProjectFormatError` al cargar, y `save_project`
  rechaza (sin escribir) un proyecto sin pisos.
- **Problema previo:** un archivo sin pisos se abría y el editor
  creaba un piso “lazy” al primer acceso, sin marcar `dirty` → la
  memoria divergía del disco con el proyecto aparentemente limpio.
- **Razón:** el editor v1 no puede operar sin piso; exigirlo en
  validación mantiene simétrico guardar/cargar (objetivo: nunca se
  escribe algo que no se puede abrir).

### Decisión AM — Invariante «dimensiones + resolución ⇒ grid»

- **Decisión:** `set_floor_dimensions` comprueba con un `CoverageGrid`
  de sondeo que la resolución **actual** siga produciendo un grid
  usable; si no, revierte y lanza `ValueError` (el diálogo lo muestra).
  El invariante ya estaba al cambiar resolución (F6); ahora se
  mantiene en **ambos** cambios de entrada.
- **Problema previo:** dimensiones gigantes (p. ej. 10000×10000 m con
  res. 0.5 m) se aplicaban sin más y dejaban el proyecto **inguardable**
  (la revalidación de `save` fallaba tarde) y sin heatmap.
- **Razón:** un proyecto editable debe ser siempre simulable y
  guardable; el error aparece en el momento de la edición.

### Decisión AN — Banda validada antes de mutar + dirty en `run_*`

- **Decisión:** `run_heatmap`/`run_simulation` validan la banda con
  `project.get_band()` **antes** de asignar `session.band_id`; un
  cambio real de banda (aunque ocurra vía argumento de `run_*`) marca
  `dirty`.
- **Problema previo:** la asignación ocurría antes de validar → una
  banda desconocida dejaba `band_id` corrupto en la sesión; y el
  cambio de configuración persistible no se reflejaba en `dirty`.
- **Relación con AJ:** ejecutar una simulación **con la banda activa**
  sigue sin marcar `dirty` (el resultado no se persiste); lo que marca
  es el cambio de la banda en sí, que sí se persiste en `EditorState`.

### Decisión AO — Escritura durable: `.tmp` + `fsync` + `replace`

- **Decisión:** la escritura atómica de F6 ahora hace `flush` +
  `os.fsync` sobre el temporal **antes** de `os.replace`.
- **Razón:** sin `fsync`, un corte de energía justo después del
  `replace` puede dejar un archivo vacío/incompleto en disco. El
  journaling complejo y el `fsync` de directorio se descartan (no
  portable en Windows).

### Decisión AP — El parser JSON también es entrada no confiable

- **Decisión:** en `load_project`, además de `JSONDecodeError`, los
  `ValueError`/`RecursionError` que pueda lanzar `json.loads` (p. ej.
  entero con > 4300 dígitos, anidamiento excesivo) se convierten en
  `ProjectFormatError`; `document_from_dict` comparte esa red.
- **Problema previo:** esos errores escapaban del manejo de la UI
  (que solo captura `ProjectFormatError`/`OSError`) y reventaban.
- **Razón:** “archivo = entrada no confiable” incluye la fase de
  parseo, no solo la validación del árbol resultante.

### Decisión AQ — Punto de extensión por versión (sin migraciones)

- **Decisión:** la lectura se estructura como
  `detectar schema_version → _document_v1(...)`; existe **solo** el
  lector v1 y cualquier otra versión sigue produciendo error claro.
- **Clasificación:** 🟢 (estructura interna; contratos y mensajes
  idénticos, sin nuevas capacidades).
- **Razón:** F6.1 solo deja preparada la futura ruta
  `load → detectar versión → migrar → validar → construir` sin
  implementarla ni obligar a reconstruir la persistencia en F7+.

### Decisión AR — Sensibilidad de radio acotada como la de clientes

- **Decisión:** `radio.sensitivity_dbm` se valida en `[-200, 0]` dBm,
  exactamente el rango ya usado para `ClientDevice.sensitivity_dbm`.
- **Razón:** la misma magnitud física debe tener la misma regla en
  ambos lugares (consistencia, no límite nuevo arbitrario).
- **No acotados a propósito:** `frequency_mhz`, `p_tx_dbm` y ganancias
  solo exigen número finito: son absurdos pero no rompen cálculo ni
  validación, y acotarlos añadiría reglas sin beneficio (F6.1 evita
  sobreingeniería).

### Decisión AS — Sin residuales de UI al cambiar de documento

- **Decisión:** `_after_document_change` limpia la imagen del heatmap
  del canvas y el estado de arrastre (`reset_interaction`) además del
  reset de sesión de F6.
- **Problema previo:** `render_project` re-colocaba el heatmap del
  proyecto anterior sobre el recién abierto hasta el próximo cálculo.
- **Razón:** “abrir B no debe mostrar nada de A” también aplica a la
  capa visual, no solo al modelo.

### Decisión AT — Tolerancias documentadas del formato v1

- **Decisión:** dentro de `schema_version = 1` se **ignoran** claves
  desconocidas (compatibilidad futura dentro de la misma versión) y
  `editor: null` se trata como sección ausente (defaults).
- **Razón:** hacerlo explícito evita que un lector futuro “arregle”
  estos comportamientos y rompa archivos existentes; la evolución real
  pasa por subir `schema_version`, no por cambiar reglas en v1.

---

## Fase 7 — Extensión RF básica

### Decisión AU — Piso de ruido configurable por radio

- **Decisión:** `RadioConfiguration.noise_floor_dbm` con default
  centralizado `-95.0` dBm y rango `[-200, 0]` (finito obligatorio).
  El piso es **propiedad de la radio**, no un literal de UI ni una
  constante universal.
- **Razón:** el piso de ruido depende del entorno y del receptor; vive
  en `core/` para que motor, UI y persistencia compartan la única fuente
  de verdad. Por radio (y no como clave `project`) permite en el futuro
  configuración por AP sin romper el key-set F6.

### Decisión AV — El SNR complementa a RSSI/SOM, no los reemplaza

- **Decisión:** `SNR = P_rx − noise_floor` se añade a
  `LinkEvaluation` (`snr_db`, `noise_floor_dbm`, `snr_meets_target`).
  `classify_quality`, `classify_som` y `meets_rssi_target` **no cambian**.
- **Razón:** RSSI mide potencia y SOM margen frente a sensibilidad; el
  SNR mide relación señal/ruido. Son tres preguntas distintas y F7 es
  extensión, no revisión (congelación de F1–F6).

### Decisión AW — Umbral de SNR con `>=` y default 25 dB

- **Decisión:** `CoverageThresholds.snr_target_db` (default `25.0`,
  rango `[-20, 60]`, finito) con comparación `snr_db >= objetivo`
  (`meets_snr_target`). Default 25 dB porque con piso −95 y objetivo
  RSSI −67 el SNR en el umbral RSSI es 28 dB: cumplir RSSI implica
  cumplir SNR y no aparece el cuadrante contradictorio en los defaults.
- **Razón:** el objetivo de SNR es “alcanzar” sí/no (>=), a diferencia
  del RSSI objetivo que sigue estricto por la decisión C (`>`); ambas
  convivencias quedan documentadas en el docstring.

### Decisión AX — Estándar Wi-Fi como metadato (sin efecto RF)

- **Decisión:** `RadioConfiguration.wifi_standard` ∈
  `802.11n/ac/ax/be` (default `802.11ax`), etiquetado por
  `wifi_generation()` → “Wi-Fi 4/5/6/7” y “Wi-Fi 6E” si `ax` y
  `f >= 5925 MHz`. No altera ninguna fórmula.
- **Razón:** era un hueco informativo (mostrar “qué red planificamos”)
  que no exige PHY; cualquier efecto real de estándar pertenece a fases
  posteriores explicitamente excluidas de F7.

### Decisión AY — Ancho de canal: propiedad de la radio, validado contra la banda, fuera de FSPL

- **Decisión:** `RadioConfiguration.channel_width_mhz` ∈
  `(20, 40, 80, 160)` (default 20, normalizado a `int`); se valida
  **una sola vez** al entrar en `simulate_coverage` con
  `allowed_channel_widths_mhz(f)`: `<3000 MHz → (20, 40)`, si no
  `(20, 40, 80, 160)`. `ValueError` claro capturado por la UI.
- **Razón:** FSPL es una fórmula de espacio libre y no tiene término
  de ancho de canal; meter el ancho en el link budget sería física
  inventada. Su único papel en F7 es coherencia de configuración
  (un AP de 160 MHz en 2.4 GHz es un error de usuario, no un cálculo).

### Decisión AZ — Compatibilidad F6: claves opcionales en schema v1

- **Decisión:** dentro de `schema_version = 1`, `radio` gana
  `noise_floor_dbm`/`channel_width_mhz`/`wifi_standard` y `thresholds`
  gana `snr_target_db` como claves **opcionales al leer** (ausentes ⇒
  defaults centralizados de `core/`) y **siempre escritas**. No se añade
  ninguna clave de nivel `project`.
- **Razón:** el paso 18 exigía detenerse si el schema se rompía; las
  claves opcionales cumplen el requisito de “sin migración” y conservan
  el key-set exacto de `document["project"]` (decisión AF/AT intacta).

### Decisión BA — Métrica del heatmap es vista, no configuración

- **Decisión:** `HeatmapMetric` (`rssi`/`snr`) en `EditorSession` con
  `heatmap_metric` (default `rssi`), que invalida el heatmap pero **no**
  marca `dirty` ni se persiste; se resetea a `rssi` al cargar/crear un
  documento. Escala de color propia (`_SNR_STOPS`, 0–45 dB) con la
  misma paleta; `legend_rows/legend_title/build_heatmap_image` ganan
  el parámetro opcional `metric`.
- **Razón:** es una lente de visualización sobre el mismo
  `SimulationResult`; persistirla haría que abrir un proyecto “cambie
  lo que ves” sin que el usuario editara nada.

### Decisión BB — Estadísticas de SNR con el mismo ganador

- **Decisión:** `_compute_stats` y `_merged_stats` añaden
  `snr_min/max/avg_db`, `snr_target_db`, `points_meeting_snr_target`
  y `snr_ratio`. En multi-AP el SNR sale de las evaluaciones ganadoras
  (mejor RSSI, decisión U): nunca se promedian SNR entre APs.
- **Razón:** mezclar SNR de APs distintos en un punto sería
  interferencia encubierta, que F7 prohíbe; las stats antiguas no
  cambian, solo se amplían.

### Decisión BC — Diagnóstico RF básico en cuatro cuadrantes

- **Decisión:** `rf_diagnostic(rx, snr, thresholds)` →
  “RSSI adecuado/bajo / SNR adecuado/bajo”. Describe el estado medido
  sin causas (nada de interferencia, canales ni hidden node).
- **Razón:** es lo único que F7 puede afirmar con lo que modela;
  inventar causas sería exactamente el tipo de física no justificada
  que este proyecto evita.

### Decisión BD — `apply_rf_settings` atómico y sincronizador

- **Decisión:** `EditorSession.apply_rf_settings(...)` construye
  radio y thresholds con `replace()` **antes** de tocar el proyecto
  (un `ValueError` no deja estado parcial), después sincroniza la
  radio de los APs existentes (F7 sin config por AP), invalida el
  heatmap y marca `dirty`. El diálogo RF captura `ValueError` con
  `showerror`.
- **Razón:** cinco campos a la vez es la entrada más propensa a
  errores de todo F7; la atomicidad en sesión (no en UI) garantiza que
  la regla valga también para futuros llamadores no interactivos.

---

## Fase 8 — Geometría arquitectónica: spaces + openings

### Decisión BE — El schema sigue siendo **v1** con claves opcionales (revisión de AK)

- **Decisión:** F8 añade `floors[].spaces[]` y `floors[].openings[]`
  como claves **opcionales** dentro de `schema_version = 1` (ausentes ⇒
  listas vacías, misma técnica que AZ en F7). **No** se crea
  `schema_version = 2`. Con esto se **revisa** la previsión de la
  decisión AK («si el editor las incorpora, el esquema crece a v2»):
  tras auditar, v2 queda reservado para cambios *breaking*.
- **Análisis (Opción A = extender v1 · Opción B = v2):**
  1. *Compatibilidad F6/F6.1/F7:* A la abre todo sin migración (clave
     ausente ⇒ `[]`). B exige lector dual o migración `v1 → v2 → Project`
     solo para un cambio que es aditivo.
  2. *Semántica de versionado:* el dispatcher actual hace coincidencia
     **exacta** (`version != SCHEMA_VERSION ⇒ error`); subir a 2
     rompería **todos** los archivos F1–F7 salvo mantener además el
     lector v1 — complejidad sin beneficio para el usuario.
  3. *Contrato del lector v1 ya tolera claves desconocidas:* existe test
     `test_unknown_keys_ignored_same_version` — una app F7 abre un
     archivo F8 e ignora `spaces`/`openings` (mismo patrón que F6
     ignorando las claves F7).
  4. *Evidencia de tests congelados:* hay tests **que F8 prohíbe
     modificar** que fijan `SCHEMA_VERSION == 1`,
     `raw["schema_version"] == SCHEMA_VERSION == 1` y
     `raw["schema_version"] == 1` (`test_persistence.py:195`,
     `test_rf_extension.py:609,679`): bajo las reglas de F8, v2
     implicaría reescribir tests anteriores.
  5. *Mantenibilidad:* v2 debería reservarse para renombres, cambios
     de tipo, campos **obligatorios** nuevos o cambio de semántica —
     ninguno ocurre en F8.
- **Razón:** ninguna propiedad de un campo existente cambia; la
  adición cumple exactamente el patrón ya aceptado en AZ. El caso
  teórico en contra (una app F7 que re-guarda un F8 y descarte los
  espacios) es el mismo que F7 creó hacia F6 y solo aplica a editors
  de versiones distintas conviviendo: fuera de alcance de una
  herramienta de versión única.

### Decisión BF — `Opening` muro-relativo (Modelo A), sin segmento flotante

- **Decisión:** `core.wall.Opening` pasa a ser
  `id + wall_id + start_offset_m + end_offset_m + kind +
  attenuation_override_db`. Se **elimina** el campo `segment` (y el
  nunca usado `blocks_signal`): la geometría del hueco se deriva con
  `opening_segment(wall, opening)` (helper puro en `core/wall.py`).
- **Análisis de modelos:** A (`wall_id` + posición relativa), B
  (segmento independiente vinculado), C (ya existente). Evidencia:
  `engine/intersection.py` ya calcula `u` = parámetro normalizado sobre
  la pared; evaluar el hueco en ese mismo espacio (metros desde
  `wall.start`) es determinista y reutiliza la intersección sin
  proyecciones nuevas. El `segment` actual del dominio **no tiene ni
  productor ni consumidor** (scaffolding muerto: ni tests, ni engine, ni
  UI, ni persistencia lo usan) — dos fuentes de verdad (segmento +
  offsets) crearían la validación duplicada que la auditoría prohíbe.
- **Razón:** 🟡 refactor de un scaffolding sin consumidores que
  completa la intención de la clase («Hueco **en una pared**»). `Space`
  no se toca: su `Rect` ya es la representación correcta.

### Decisión BG — Semántica RF del hueco: **reemplazo**, nunca suma

- **Decisión:** si el cruce cae dentro de la unión de los openings de
  la pared, la pérdida de **ese cruce** es
  `attenuation_override_db.get(banda, 0.0)` (vacío ⇒ 0 dB) y **sustituye**
  —no suma— a la atenuación del material. Reglas:
  - *Límite cerrado:* un cruce en `start − ε ≤ d ≤ end + ε` pertenece
    al opening (los extremos son del hueco; ε = `EPSILON_GEOMETRY`).
  - *Unión determinista:* si varios openings cubren el cruce, el
    orden canónico `(start_offset_m, id)` elige cuál aporta el
    override; el resultado es independiente del orden de inserción.
  - *Sin consulta de material ⇒ sin dato inventado:* un cruce en hueco
    no llama a `wall_attenuation_db`, así que **6 GHz atraviesa un
    hueco con 0 dB**; un cruce **sólido** sigue lanzando
    `MaterialAttenuationError` exactamente que antes.
  - El cruce sigue registrándose en `walls_crossed` con `loss_db=0` y
    `opening_id` (informativo; `crossings` cuenta atravesamientos de
    pared, no materiales).
- **Razón:** imposible por construcción producir
  `pared + opening` (un único valor por cruce). La distinción
  door/window queda como **metadato visual** (`kind`), no como clase RF
  — no se inventan materiales por tipo de hueco.

### Decisión BH — `Space` es geometría + organización en F8 (sin RF)

- **Decisión:** F8 implementa Spaces como regiones identificables
  (`id`, `name`, `function`, `rect`, `metadata`) con CRUD en sesión,
  dibujo, selección y persistencia. **No** participan en
  `trace_walls` ni en ninguna fórmula: crear/editar/eliminar un
  espacio marca `dirty` pero **no** invalida el heatmap en la sesión.
- **Razón:** ninguna razón sólida convierte una zona semántica en
  atenuación (los muros entre zonas ya modelan la RF). Meter comportamiento
  RF en `Space` «porque se puede» acoplaría dominio a fórmulas y
  contradice el principio de la fase. El `id_space_from/to` de `Wall`
  queda como referencia opcional sin uso en F8 (documentado, sin
  romperlo).

### Decisión BI — Interacción mínima (sin CAD, sin editar endpoints de paredes)

- **Decisión:**
  - *Espacios:* herramienta `Espacio` (radio + tecla `e`) con patrón de
    dos clics idéntico al de pared (esquina → esquina), esquinas
    recortadas al piso, tamaño mínimo 0.1 m; selección por
    `rect.contains` **detrás** de todo lo demás; edición de
    nombre/función desde propiedades; Delete elimina.
  - *Aperturas:* **no** hay herramienta nueva. Con una pared
    seleccionada, propiedades muestra sus openings y los botones
    «+ Puerta» / «+ Ventana» (creación centrada con longitud por
    defecto, recortada a la pared). Seleccionar un opening = clic sobre
    su tramo (hit-test openings **antes** que paredes); edición de
    `kind`/offset/longitud desde propiedades; Delete elimina.
  - *Endpoints de paredes:* siguen sin editarse; los offsets métricos
    hacen innecesario mover extremos.
- **Razón:** reutiliza los patrones exactos del editor (drag de pared,
  hit-test por distancia, panel de propiedades) en vez de construir un
  sub-CAD. Quedan fuera snaps de apertura, manijas de redimensionado,
  layers y booleanos (explícitamente fuera de alcance).

### Decisión BJ — Persistencia de F8 dentro de `floors`, con límites duros

- **Decisión:** `floors[]` gana `spaces` y `openings` (siempre
  escritos; ausentes ⇒ `[]`). Validación por capa:
  - *Dominio (`Opening.__post_init__`):* offsets finitos,
    `0 ≤ start`, `end − start ≥ MIN_OPENING_LENGTH_M (0.01)`,
    `kind ∈ {door, window, pass_through}`, overrides finitos en
    `[0, 200] dB`.
  - *Persistencia:* `wall_id` debe existir **en el mismo piso**,
    `end ≤ longitud de la pared + ε` (rechaza «fuera de la pared»),
    únicos por tipo; límites: `MAX_SPACES = 5000`,
    `MAX_OPENINGS = 10000` por piso, `MAX_OPENINGS_PER_WALL = 32`,
    rects con dimensiones `(0, MAX_DIMENSION_M]` y coordenadas
    acotadas; metadata con el validador existente; sin NaN/Infinity.
  - *Sesión:* recorte/validación al crear (la entrada del usuario no
    puede producir un opening inválido) y validación al editar.
  - Espacios **no** se exigen dentro del rect del piso (un
    `set_floor_dimensions` menor no dejaría el proyecto inguardable —
    invariante AM evitado); su creación sí recorta al piso.
- **Razón:** mismas defensas F6.1 (tipos estrictos, referencias
  existentes, listas acotadas, escritura atómica) aplicadas a las dos
  entidades nuevas; la asimetría espacio/pared es deliberada porque los
  espacios no son RF.

### Decisión BK — Constantes de creación en `core`, no números mágicos en UI

- **Decisión:** `core/wall.py` centraliza
  `OPENING_KINDS`, `MIN_OPENING_LENGTH_M (0.01)`,
  `MAX_OPENING_LENGTH_M (1000)`, `MAX_OPENING_ATTENUATION_DB (200)`,
  `DEFAULT_OPENING_LENGTH_M = {"door": 0.9, "window": 1.2,
  "pass_through": 1.0}`; `core/space.py` añade
  `MIN_SPACE_SIZE_M (0.1)`. La UI y la persistencia referencian
  estas constantes.
- **Razón:** misma regla de F7 (defaults centralizados en `core/`,
  YAML/config solo los referencia si los necesita): el editor no
  hardcodea longitudes de puerta ni tamaños mínimos.

---

## Fase 9 — Obstáculos y mobiliario

### Decisión BL — `Obstacle` con footprint rectangular en `core/obstacle.py`

- **Decisión:** el dominio vive en `core/obstacle.py` como
  `Obstacle` frozen dataclass: `id`, `name`, `rect: Rect` (footprint
  alineado a ejes, en metros), `material` (obligatorio), `kind`
  (`OBSTACLE_KINDS = furniture | equipment | column | other`),
  `attenuation_override_db` (por banda), `blocks_signal` y
  `metadata`. El scaffold muerto de F1 en `core/wall.py`
  (`class Obstacle` segment-based + `ObstacleKind` enum) se **elimina**:
  un solo concepto, una sola clase, cero consumidores divergentes.
- **Constantes:** `MIN_OBSTACLE_SIZE_M = 0.1` (editor),
  `MAX_OBSTACLE_SIZE_M = 1000` (archivo),
  `MAX_OBSTACLE_ATTENUATION_DB = 200` (igual que openings),
  `DEFAULT_OBSTACLE_MATERIAL_ID = "wood"`.
- **Qué NO:** sin altura (`height_m`), sin polígonos arbitrarios, sin
  giro, sin booleanos sobre paredes; los solapes entre obstáculos se
  permiten y sus pérdidas se acumulan. Hit-test:
  AP → Cliente → Opening → Obstáculo → Pared → Espacio.

### Decisión BM — Pérdida por obstáculo: reemplazo del material, sin espesor

- **Decisión (Modelo C con precedencia explícita):** si
  `attenuation_override_db` define la banda evaluada, ese valor
  **sustituye** a `material.attenuation_for(band)`; jamás se suman
  (`metal 25 + override 7` ⇒ **7 dB**, no 32 dB). Si no hay override,
  se usa la atenuación de referencia del catálogo **sin escalar por
  espesor**: el footprint no es un espesor de pared.
- **6 GHz:** el comportamiento es idéntico al de las paredes sólidas —
  obstáculo cruzado sin override `band_6` ⇒ `MaterialAttenuationError`;
  no se inventan valores ni se convierte 5 → 6 GHz. Un obstáculo no
  cruzado no se consulta y por tanto no lanza error.
- **Razón:** una única regla de precedencia (reemplazo, como los
  openings en BG) elimina la ambigüedad «¿material + override o solo
  override?» y hace el desglose del link budget auditable.

### Decisión BN — Un solo atravesamiento por obstáculo y orden fusionado

- **Decisión:** el trayecto AP → punto se evalúa contra los cuatro
  bordes del rect con la MISMA primitiva que las paredes
  (`segment_crossing_parameters`, cruce interior estricto; ver F/G).
  Si hay ≥ 1 cruce de borde se registra **un solo** atravesamiento con
  la menor distancia (la entrada). Tocar una esquina exacta, correr
  por un borde (colineal) o quedar completamente dentro ⇒ 0 cruces.
  Pre-check AABB descarta cajas disjuntas (no cambia la semántica).
- **Orden canónico fusionado:** paredes y obstáculos se fusionan en
  `(distancia, tipo —pared(0) antes que obstáculo(1)—, id)` y la suma
  flotante sigue ese orden, con lo que el resultado es independiente
  del orden de las listas de entrada. Sin obstáculos el orden reduce a
  `(distancia, wall.id)` — idéntico a Fase 2–8.
- **Sin doble atenuación:** la pérdida del obstáculo es
  independiente de la pared u opening de la misma trayectoria; un
  opening sigue reemplazando SOLO su sección de pared. Un solo
  atravesamiento por obstáculo evita contar dos veces la entrada y la
  salida del mismo objeto.
- **Razón:** compartir la primitiva de intersección garantiza que
  paredes y mobiliario no diverjan en casos de borde; el orden
  fusionado preserva la regresión byte-idéntica.

### Decisión BO — `floors[].obstacles` opcional en schema v1

- **Decisión:** misma fórmula que spaces/openings (BE): la clave
  `obstacles` es **opcional al leer** (ausente ⇒ lista vacía; los
  archivos F1–F8 abren sin migración) y **siempre se escribe** al
  guardar, dentro del piso correspondiente. `schema_version` sigue
  siendo **1**. Cada entrada valida: `id` único por piso,
  `material_id` obligatorio y existente en el catálogo, `kind` ∈
  `OBSTACLE_KINDS`, rect con dimensiones (0, `MAX_OBSTACLE_SIZE_M`] y
  coords acotadas, finitos y no booleanos; override por banda en
  `[0, 200]` con claves no vacías; `blocks_signal` booleano; metadata
  dict. Límite `MAX_OBSTACLES = 5000`.
- **Razón:** el lector ya trata el JSON como entrada no confiable
  (AI/AP); los obstáculos heredan exactamente el mismo nivel de
  protección sin ampliar el alcance del formato.

### Decisión BP — Interacción mínima de obstáculos (tecla `o`, 2 clics, arrastre)

- **Decisión:** tool `Tool.OBSTACLE` con radio «Objeto» en la toolbar
  y tecla `o` (el handler ignora Ctrl, sin conflicto con Ctrl+O).
  Creación con **dos clics + preview** (patrón SPACE); en SELECT se
  arrastra el footprint completo con clamp al piso (el tamaño no
  cambia); panel **Objeto** con nombre / tipo / material / override
  `band_id=dB` (separado por `,` o `;`). Escape limpia el trazo.
- **Invalidación RF:** a diferencia de `Space` (BH), **toda** mutación
  de obstáculos — crear, editar nombre/tipo/material/override,
  mover y borrar — llama a `invalidate_heatmap()` y marca `dirty`:
  el mobiliario atenúa la señal y el heatmap debe recalcularse
  (el pipeline con debounce de la app se encarga del recálculo).
- **Qué NO:** sin editor de vértices, sin rotación desde la UI, sin
  catálogo de objetos precargado ni biblioteca BIM; el override se
  escribe a mano por banda y se revalida en `Obstacle.__post_init__`
  (`replace` vuelve a pasar por toda la validación del dominio).

---

## Fase 10 — Canales y configuración RF por AP

### Decisión BQ — `core/channel.py`: fuente única del catálogo de canales

- **Decisión:** el catálogo número lógico ↔ frecuencia central vive en
  `core/channel.py` como `WifiChannel` frozen dataclass
  (`number`, `center_frequency_mhz`) con tres familias generadas por
  fórmula (nunca tablas escritas a mano):
  - **2.4 GHz:** canales 1–13 con centro `2412 + 5·(n−1)` MHz y el
    canal 14 en 2484 MHz (numeración IEEE/JP).
  - **5 GHz:** bloques de 20 MHz — `36…64 → 5180 + 20k`,
    `100…144 → 5500 + 20k`, `149…161 → 5745 + 20k`, `165 → 5825`.
  - **6 GHz:** `n = 1, 5, 9, …, 233` con centro `5950 + 5·n` MHz
    (ch 233 = 7115 MHz; ch 37 = 6135 MHz = banda 6 por defecto).
- **API:** `channels_for_frequency(f)`,
  `channel_numbers_for_frequency(f)` (selectores de la UI),
  `channel_for_band(band, n)`, `default_channel(band)`,
  `validate_channel_config(band, n, width)` y
  `MAX_CHANNEL_NUMBER = 233`. La **familia** se decide con la MISMA
  frontera que los anchos de canal (AY): `f < 2437+…` → 2.4,
  `< 5925` → 5, `≥ 5925` → 6 (se reutilizan los límites privados de
  `core/radio.py`, sin duplicar fronteras).
- **Fuente única:** ni `ui/`, ni `engine/`, ni `persistence/`,
  ni `config/` contienen cifras de frecuencia (2412, 5180, 5950…):
  todo consulta este módulo. La UI solo muestra lo que el catálogo
  devuelve.
- **Qué NO:** sin tablas de canales por país/regulación, sin canales
  de 5/10 MHz, sin DFS/TPC ni listas dinámicas; el catálogo es el
  estándar IEEE de los tres espectros del proyecto.

### Decisión BR — Canal ≠ frecuencia; la frecuencia central se deriva y nunca entra en FSPL

- **Decisión:** `number` es un **identificador lógico** y
  `center_frequency_mhz` un **valor físico derivado** del catálogo. La
  frecuencia central **no se persisten jamás**: se recalcula al leer,
  con lo que es imposible una inconsistencia canal↔frecuencia en el
  archivo.
- **El canal NO altera la física (crítico A/B):** FSPL, pérdida por
  obstáculos, RSSI/P_rx, SOM, SNR, veredicto y calidad usan SOLO
  `FrequencyBand.frequency_mhz` (y el resto del link budget). Cambiar
  un AP del canal 36 al 40 en la misma banda produce evaluaciones
  **idénticas** — verificado por test A/B (`test_channels.py`) y por
  el snapshot `f10_regression_snapshot.py` (configurado vs baseline y
  swap 36→40, RF byte-idéntica). El ancho de canal (AY) tampoco entra
  en el presupuesto de enlace.
- **Independiente del ancho:** el centro del canal no cambia con el
  ancho (canal 36 con 80 MHz ⇒ centro 5180 MHz; el ancho define el
  rastro, no el centro).
- **Razón:** en Fase 10 el canal es **configuración/metadata** para
  planificar y para Fase 11; meterlo en la propagación inventaría
  física no aprobada por el spec.

### Decisión BS — Banda + canal por AP (`band_id` + `channel`), un radio → una banda

- **Decisión:** `AccessPoint` gana `band_id: str | None` junto al
  `channel: int | None` que ya existía como placeholder (F1). El AP
  declara **en qué banda y canal transmite**; la banda activa del
  editor sigue siendo el valor por defecto y el selector del toolbar
  no cambia de semantics (sigue configurando la banda de los APs sin
  banda propia y la corrida puntual).
- **Resolución en simulación:** `resolve_band_for_ap(ap, band_id)` →
  `ap.band_id or banda_resuelta_de_la_corrida or banda_activa`.
  Proyectos F1–F9 (sin `band_id`) producen resultados **idénticos** a
  F9. `run_heatmap`/`run_simulation` usan la banda resuelta por AP.
- **Invariante:** `channel` explícito ⇒ `band_id` obligatorio (validado
  en `AccessPoint.__post_init__` y en el lector). Un AP no puede
  declarar canal «al aire» sin decir en qué banda.
- **Sin multi-radio:** un AP = un radio = una banda (el spec lo
  descarta explícitamente). Un heatmap con APs de banda mixta sigue
  siendo **rechazado** por `combine_results` (contrato F5 congelado,
  dos tests existentes lo exigen); el error queda visible en el panel
  vía `last_heatmap_error`. Ese límite es el puente reportado a F11+.

### Decisión BT — Un único punto de validación del triple (banda, canal, ancho)

- **Decisión:** `core.channel.validate_channel_config(band, channel,
  width)` valida: (1) el canal pertenece al catálogo de la familia de
  la banda (`channel_for_band`), (2) el ancho pasa la regla de familia
  de F7 (`allowed_channel_widths_mhz`: 2.4 → 20/40; 5/6 →
  20/40/80/160) sin duplicar esa lógica. Devuelve el `WifiChannel`
  validado para derivar el centro.
- **Llamadores:** la sesión (`set_ap_rf_config`), la persistencia al
  leer y el guard del engine (`simulate_coverage` valida canal × banda
  además del ancho × banda de F7). La UI **no** valida: arma el triple
  y delega; los errores vuelven como `ValueError` → `showerror`.
- **`apply_rf_settings` (F7) no gana validación de canal × banda:** su
  contrato congelado es sincronizar `radio.channel_width_mhz` aunque
  la banda activa no admita ese ancho (test F7 lo exige); el rechazo
  ocurre al simular, igual que hoy.
- **Nota de numeración:** existen números válidos en dos familias
  (149/153/157/161/165 existen en 5 GHz y en 6 GHz con centros
  distintos): por eso la validación es SIEMPRE contextual al par
  (banda, canal) y nunca «número suelto».

### Decisión BU — Panel «Radio del AP» + etiqueta de canal en el lienzo

- **Decisión:** marco **«Radio del AP (Fase 10)»** en el panel de
  propiedades (bajo Selección): Banda (nombres del catálogo
  `project.bands`), Canal y Ancho — listas dinámicas desde
  `core.channel`/regla de familia —, más Frecuencia central (solo
  lectura, derivada) y Estándar (solo lectura, F7). Botón
  **«Aplicar radio»** = commit atómico vía `session.set_ap_rf_config`
  (valida primero; errores → `messagebox`, sin mutación).
  Cambiar la banda repuebla canales/anchos y selección por defecto
  (`default_channel`: 6 / 36 / 37).
- **Bloque Selección** ampliado con `Banda:` (configurada o «—
  (activa: …)»), `Canal:` (`— (sin configurar)` si es `None`, con
  centro derivado) y `Estándar:`; el lienzo dibuja
  `CH n · w MHz` bajo el AP **solo si** `ap.channel` está configurado
  (sin ruido por defecto).
- **Invalidación:** `set_ap_rf_config` llama a `invalidate_heatmap()`
  (invalidación genérica F4) + `mark_dirty()` **solo si hay cambio
  real** de `band_id`/`channel`/`width` (re-aplicar lo mismo no marca
  nada). El canal no altera RSSI, pero la banda configura la
  frecuencia de simulación del AP y el cambio es persistible; el
  recálculo con debounce lo decide la app como cualquier edición.

### Decisión BV — `access_points[].band_id` opcional en schema v1 (canal ya existía)

- **Decisión:** la clave `band_id` es **opcional al leer** (ausente ⇒
  `None` ⇒ banda activa: los archivos F1–F9 abren sin migración) y
  **siempre se escribe** al guardar. El `channel` existente desde F6
  se conserva con su misma forma (`_require_int`), pero AHORA el lector
  exige: `band_id` presente en `project.bands`; si hay `channel`
  explícito, `band_id` obligatorio y el canal debe pertenecer al
  catálogo de esa banda (`channel_for_band` → `ProjectFormatError`).
  Frecuencia central: nunca en el JSON. `schema_version` sigue en
  **1** (claves opcionales, misma fórmula que BE/BG/BO).
- **Ancho × banda NO se valida al cargar** (contrato F7: la
  configuración de ancho puede existir con la banda activa antigua);
  se valida al simular y al aplicar desde el panel.
- **Razón:** se migra un placeholder F1 a configuración real sin
  romper ningún archivo existente ni tocar la versión de esquema.

### Decisión BW — Frontera F10 / F11: sin interferencia, SINR ni optimización

- **F10 = conocimiento y configuración:** catálogo, validación, UI y
  persistencia de banda+canal+ancho. La física (FSPL, SOM, RSSI, SNR,
  calidad, `MIN_FSPL_DISTANCE_M`, comportamiento 6 GHz) queda
  **intacta** — probado por la regresión F9 byte-idéntica
  (SHA `00E306ADB4EBD5750B9A1E9783925083C43AEC1AD980719CECB96C7C3EDF982B`).
- **F11+ (NO implementado en F10):** colisión/co-adyacencia de
  canales, energía recibida entre emisores, CCA/CSMA, penalización
  por solape, selección/optimización de canal, capacidad y
  planificación de espectro. Ningún `.py` de F10 contiene ese
  vocabulario (lo prohíbe `audit_f10.py`).
- **Razón:** el spec de F10 es explícito: el canal NO cambia RSSI y
  la capa de conflicto/interferencia es la fase siguiente.

---

## Fase 11 — Interacción espectral e interferencia

F11 modela la **interacción entre emisores** sin tocar la física
histórica: FSPL, link budget, RSSI, SOM, SNR, paredes, openings y
obstáculos siguen siendo exactamente los de F1–F10 (A/B byte-idéntico).
La información se calcula **en paralelo** al RSSI y F12 la usará para el
SINR. Archivos nuevos/modificados: `engine/interference.py` (nuevo),
`core/result.py` (+4 campos con default), `engine/combine.py`
(docstring), `engine/__init__.py` (exports), `ui/session.py` (contexto,
anotación, métrica, panel, stats), `ui/coverage_renderer.py` (registro +
escala + leyenda + rama de pintado), `ui/panels/toolbar.py` (etiqueta),
`ui/panels/properties.py` (bloque AP), `ui/app.py` (refresh),
`tests/test_interference.py` (nuevo).

### Decisión BX — Información paralela: `LinkEvaluation` gana 4 campos; RSSI intacto

- **Decisión:** `LinkEvaluation` añade al final, todos con default y
  opcionales: `interference_evaluated: bool = False`,
  `interference_dbm: float | None = None`, `interferer_count: int = 0`,
  `dominant_interferer_ap_id: str | None = None`. La anotación ocurre
  en la **sesión** (con los P_rx ya calculados) y `combine_results`
  sigue eligiendo por **mayor RSSI** sin cambios funcionales: la
  evaluación ganadora *lleva* su interferencia como dato adicional.
- **Razón:** información paralela = cero riesgo para F1/F5/F7/F10:
  `rx_power_dbm`/`som_db`/`snr_db`/`quality`/`verdict` no cambian
  (A/B en tests y `accept_f11` paso 5). Los tests de F1–F10 usan
  fingerprints por proyección de campos, así que ganar campos con
  default es compatible sin tocar ningún test congelado. No se define
  `sinr`: eso es F12 (decisión CD).

### Decisión BY — Ocupación espectral simplificada y solapamiento semiabierto

- **Decisión:** cada emisión ocupa `centro ± ancho/2` (rectángulo
  ideal; centro derivado del catálogo F10 — este módulo no duplica
  tablas). `overlap = max(0, min(hi_a,hi_b) − max(lo_a,lo_b))` con
  intervalos **semiabiertos** `[lo, hi)` y `overlap_ratio =
  overlap / min(w_a, w_b)` (fracción del ancho MENOR; contenido ⇒ 1.0).
  Dos emisiones que solo se tocan en el borde ⇒ `0 MHz / 0 %`.
- **Razón:** determinismo total (sin casos de borde ambiguos), sin
  dependencias nuevas y honestidad documentada: NO es la máscara
  espectral PHY real (sin lobulaciones, guard bands ni ruido
  espectral) — es una aproximación de ingeniería para planificación.

### Decisión BZ — Contribución efectiva con PSD plano rectangular (fórmula derivada)

- **Decisión:** `I = P_rx,i + 10·log10(overlap / W_i)` por interferente,
  aislada en `effective_interference_dbm`. `overlap = 0 ⇒ None` (no
  se usa −∞), acotada arriba por `P_rx,i` (`overlap ≤ W_i ⇒ término ≤
  0 dB`), monótona en `overlap`, redondeada a 2 decimales.
- **Razón:** es la consecuencia física de asumir densidad espectral
  **plana** sobre el ancho del interferente — no una penalización
  mágica. Al estar aislada, F12/F14 puede reemplazarla (p.ej. con PSD
  real) sin tocar el resto del módulo. Sin overlap = sin aporte: la
  ausencia se representa con `None`, jamás con −∞.

### Decisión CA — Agregación en dominio lineal y determinismo total

- **Decisión:** las contribuciones se convierten a mW
  (`dbm_to_mw`/`mw_to_dbm`, centralizados como **única** definición en
  `engine/interference.py`), se suman linealmente y se vuelve a dBm
  (`aggregate_dbm`, 2 decimales). Sin contribuidores ⇒ `None`.
  Orden canónico `(-potencia, ap_id)`; dominante = mayor contribución,
  **empate ⇒ menor `access_point_id`**; la suma sigue ese orden.
- **Razón:** `dBm` no es aditiva (−3 + −3 ≠ −6). Sin resultados no se
  inventa −∞ ni −100 dBm: `None` es el «sin datos / sin contribuidores»
  honesto que la UI distingue de «0 interferentes». El sort por id
  elimina la dependencia del orden del proyecto/JSON.

### Decisión CB — Ámbito: misma banda + APs con canal; sin canal = fuera del modelo

- **Decisión:** solo interactúan APs del **mismo `band_id`** y **con
  canal configurado**. La anotación usa los resultados ya simulados de
  los APs vecinos (contexto): en `run_simulation` y en `run_heatmap`
  con selector individual se simulan esos vecinos y se anota el AP
  deseado; con «Todos los AP» se anota cada uno antes de combinar. La
  métrica visible NO condiciona el contexto (el panel y la métrica
  «interference» siempre tienen datos cuando hay canales). AP sin canal
  ⇒ evaluaciones sin anotar (`interference_evaluated=False`), pero su
  RSSI histórico sigue funcionando igual que en F1–F10.
- **Razón:** nunca hay interacción entre bandas (2.4/5/6 GHz jamás se
  solapan en este modelo), el contrato F5 de bandas mixtas queda
  intacto, y los proyectos **sin canales** (F1–F9) no pagan ningún coste
  extra: la puerta `len(results) >= 2` + `ap.channel is not None`
  además protege los tests con `simulate_coverage` monkeypacheado.

### Decisión CC — UI: bloque en el panel + métrica «interferencia» fuera del enum F7

- **Decisión:** el panel de AP añade un bloque «Interferencia» vía
  `session.ap_interference_lines(ap_id)` con **solo datos reales**:
  `(AP sin canal)` / `0 APs (sin espectro compartido)` / `sin datos de
  corrida` / `APs interferentes (máx)` + `Potencia agregada máx` +
  `Dominante`. El heatmap gana la métrica `interference`: validada
  contra `ui.coverage_renderer.HEATMAP_METRICS` (registro único,
  ahora `("rssi", "snr", "interference")`), **no** contra el enum
  `HeatmapMetric`, que sigue congelado en `{rssi, snr}` (contrato de
  tests F7). Escala visual propia (dirección invertida: más alto = peor;
  `None` ⇒ color de «sin interferencia»), leyenda con bandas de la
  escala (no umbrales RF), header de `heatmap_stats_text` con el
  resumen, y `app` refresca el panel tras simular y tras el heatmap.
- **Razón:** la UI de F7 congeló el enum por contrato; ampliarlo rompería
  `{m.value for m in HeatmapMetric} == {"rssi","snr"}`. El registro del
  renderer es la pieza que ya validaba `build_heatmap_image`, así que
  ahí vive la extensión. Las líneas del panel nunca inventan números:
  «sin datos» ≠ «0».

### Decisión CD — Frontera F11 / F12: sin SINR, sin CCA/CSMA, sin optimización

- **Decisión:** F11 calcula **solo** ocupación, solapamiento y potencia
  recibida/agregada de interferentes. NO se calcula SINR, CCA/CSMA,
  throughput/capacidad, selección ni optimización de canal, roaming,
  MLO, OFDMA/MCS, CAPWAP ni WMM (lo prohíbe `audit_f11.py` con
  negaciones permitidas: «no se calcula sinr», «f12», …). La
  persistencia **no cambia**: schema v1 intacto, cero rastros de
  `interference` en `persistence/`; los campos viven solo en memoria
  de resultados.
- **Razón:** el spec define F11 como la capa de *conocimiento* de
  interferencia y F12 como quien la convierte en métrica de calidad de
  enlace. Mantener el esquema en v1 evita migraciones y romper la
  compatibilidad con archivos F1–F10 sin ganar nada (los resultados no
  se persisten). **Nota:** `audit_f11.py` sustituye a `audit_f10.py`:
  re-ejecuta todas las verificaciones estructurales de F10 (capas,
  catálogo único, herencia) — además corrige su bug latente que
  saltaba el escaneo de `ui/` — y cambia la barrera de vocabulario de
  «prohibir interferencia» (correcta en F10, obsoleta aquí) por la de
  F12. La verificación de capas de `audit_f10.py` sigue pasando bajo
  F11; solo su barrera léxica de F10 queda superada por diseño.

### Decisión CE — Rendimiento: sin caché, sin hilos, coste O(P·N²) de aritmética

- **Decisión:** cero estado compartido: `engine/interference.py` no
  importa `threading`/`concurrent`/`multiprocessing` ni usa
  `lru_cache`; la anotación es `O(puntos × APs²)` de sola aritmética
  (aprox. µs por punto y par) y las simulaciones de contexto solo
  existen donde hay canales. Sin GPU, sin red, sin paralelismo.
- **Razón:** los grids del editor son ≤ miles de puntos y ≤ decenas de
  APs; el coste es despreciable frente a la propia simulación F4.
  Introducir caché/hilos rompería el determinismo y la testabilidad
  puros de la capa engine sin necesidad.

---

## Fase 12 — SINR + diagnóstico RF

### Decisión CF — SINR como capa paralela con fórmula única y estable en `engine/sinr.py`

- **Decisión:** la fórmula
  `SINR = P_rx − 10·log10(10^(NoiseFloor/10) + 10^(I/10))` vive en
  **un solo sitio** (`engine/sinr.py::signal_to_interference_noise_ratio`,
  espejo del naming de `signal_to_noise_ratio`); nadie la replica. La
  suma ruido+I usa la forma estable basada en el máximo
  (`D + 10·log10(1 + 10^((min−D)/10))`, exponente ≤ 0 ⇒ sin overflow,
  sin división por cero, underflow benigno) y rechaza valores no
  finitos con `ValueError`. La sesión anota **después** de
  `annotate_interference` (F11) y **antes** de `combine_results` (F5),
  de modo que la evaluación ganadora por RSSI transporta su propio
  SINR. El bloque de estadísticas (`sinr_stats_block`) también es único
  y lo consumen simulador, combinador, panel y UI.
- **Razón:** decisiones CA/CG exigían dominio lineal y una definición
  canónica reemplazable; el orden de anotación es el único coherente
  (no existen I antes de F11 ni un ganador antes de F5). Combinar
  sigue siendo MAX RSSI: SINR jamás elige ganadores.

### Decisión CG — Sin interferencia modelada ⇒ SINR = SNR exactamente

- **Decisión:** `interference_dbm = None` ⇒ el denominador es el piso
  de ruido y el retorno es `round(P_rx − N, 2)`, **idéntico bit a bit**
  al SNR (misma aritmética redondeada). Vale para proyectos F1–F10,
  AP sin canal, canales sin solapamiento, un solo AP y corridas sin
  contexto; `evaluate_link` rellena `sinr_db` en todos los cases y la
  UI tolera la ausencia de claves `sinr_*` en resultados sintéticos
  antiguos (presencia, no igualdad, es el contrato — patrón F7/F11).
- **Razón:** cualquier otro comportamiento inventaría precisión donde
  el modelo no la tiene y rompería la coherencia SNR/SINR (§14 de
  `docs/formulas.md`). `sinr_db = None` solo existe en constructores
  manuales; la pintura de la métrica `sinr` los muestra en gris neutro.

### Decisión CH — Umbral `sinr_target_db`: comparación `>=`, default 25 dB, diálogo incluido

- **Decisión:** `CoverageThresholds.sinr_target_db` (default
  `DEFAULT_SINR_TARGET_DB = 25.0`, rango [-20, 60] dB validado en
  `__post_init__`) con comparación **`>=`** (`meets_sinr_target`,
  igual que el SNR de AW) y diagnóstico propio de dos estados
  (`sinr_diagnostic`: «SINR adecuado»/«SINR bajo») que **no** toca las
  4 salidas congeladas de `rf_diagnostic`. Se expone en el diálogo
  «Config RF…» (`sinr_target_db` como 6.º elemento del callback y kwarg
  opcional de `apply_rf_settings`: `None` conserva el actual). En
  schema v1 la clave se **escribe siempre** y se **lee opcional**
  (patrón AZ; los archivos F1–F11 abren con default 25.0); los
  resultados derivados (`sinr_db`, `sinr_meets_target`, `sinr_ratio`)
  **nunca** se escriben en el JSON.
- **Razón:** 25 dB = objetivo de SNR de F7; como SINR ≤ SNR siempre
  (el denominador incluye el ruido), cumplir SINR(25) ⇒ SNR(25), y sin
  interferencia ambos umbrales se cumplen o fallan juntos. El diálogo
  es la única superficie donde ya se editan los umbrales RF; no
  duplicarla evita una segunda fuente de verdad.

### Decisión CI — Supersede de la frontera F11 (CD) solo en sus 2 tests congelados

- **Decisión (aprobada por el usuario):** F12 reescribe **exactamente
  dos** tests frontera de F11, supersediendo parcialmente CD:
  `test_no_sinr_field_or_calculation` →
  `test_sinr_fields_present_and_equal_snr_without_interference` (los
  campos existen, SINR = SNR sin I, el nombre corto `sinr` sin sufijo
  sigue sin existir) y
  `test_heatmap_metrics_registry_includes_interference` (el registro
  pasa a `("rssi","snr","interference","sinr")`; el **enum** de F7
  sigue congelado en `{"rssi","snr"}` y `audit_f11.py` queda
  superseded por `audit_f12.py`, igual que `audit_f10` lo quedó por
  `audit_f11` — decisión CD ya documentaba ese precedente).
  Los otros 636 tests de F1–F11 quedan intactos.
- **Razón:** el spec de F12 exige esos campos y esa métrica; los dos
  tests existían precisamente para congelar la ausencia que F12
  levanta. Reescribirlos conservando su espíritu (frontera explícita)
  es preferible a borrarlos, y limitarlo a dos preserva el resto del
  contrato histórico byte a byte.

---

## Discrepancias encontradas (no resueltas silenciosamente)

### 1. Distancias `d_max` contradictorias

| Fuente | AP1 | AP2 | AP3 | AP4 |
|---|---:|---:|---:|---:|
| DOCX Tabla 3 | 3.80 | 4.88 | 5.42 | 5.58 |
| `calculo_wifi_biblioteca.py` / `CalculoWifi2.py` | 3.80 | 4.88 | 5.42 | 5.58 |
| `CODIGO(Interactivo).py` / `CalculadoraWLAN_Visual.py` | 5.72 | 8.92 | 6.87 | 9.65 |

- **Resolución:** decisión A. Se usa el conjunto DOCX/v1/v2 como golden
  data. El conjunto v3/v4 queda documentado como legacy congelado.
- **Pendiente para el usuario:** confirmar si las distancias v3/v4
  representan otra estimación legítima (p.ej. semidiagonal real medida)
  que deba documentarse como variante.

### 2. `L_m` presente en unos archivos y ausente en otros

| Fuente | ¿Incluye L_m = 10 dB? |
|---|---|
| DOCX / XLSX | Sí |
| `calculo_wifi_biblioteca.py` / `CalculoWifi2.py` | Sí |
| `CODIGO(Interactivo).py` / `CalculadoraWLAN_Visual.py` | No |

- **Resolución:** decisión B. `L_m = 10 dB` por defecto, configurable a 0.

### 3. Operador RSSI `>` vs `>=`

| Fuente | Operador |
|---|---|
| DOCX, v3, v4 | `> −67` |
| `CalculoWifi2.py` (v2) | `>= −67` |

- **Resolución:** decisión C. Se usa `>`.

### 4. Algoritmo de veredicto SOM divergente en v2

- `CalculoWifi2.py` usaba `som > criterio` (estricto): `SOM = 20.0`
  exacto era RIESGO, no APROBADO. Además el suelo de RIESGO estaba
  fijado en 10 independientemente del criterio.
- **Resolución:** decisión D. Se usa `≥` (DOCX/v1/v3/v4).

### 5. Validación de frecuencia ausente en v1

- `calculo_wifi_biblioteca.py` solo validaba `distancia > 0` en FSPL,
  no `frecuencia > 0`.
- **Resolución:** el motor nuevo valida ambas (`propagation.py`).

### 6. `RSSI_OBJETIVO_MIN` sin usar en v1

- `calculo_wifi_biblioteca.py` define la constante pero nunca la evalúa.
- **Resolución:** el motor nuevo siempre evalúa el RSSI objetivo en
  `evaluate_link`.

### 7. Esquema de `ZONAS` inconsistente entre archivos

- v1/v2: `{ap, zona, area_m2, distancia_max_m}`
- v3: `{ap, zona, sala_critica, distancia_max_m}` (sin `area_m2`)
- v4: v3 + `{color}`
- **Resolución:** el dominio nuevo no reutiliza `ZONAS`. Las zonas serán
  `Space`/`Floor` con geometría real. Los datos legacy solo viven en la
  golden data.

### 8. XLSX con fórmulas rotas (`#REF!`)

- La hoja `Cálculos` del XLSX tiene referencias de frecuencia rotas
  (celdas `F24`/`F5`), por lo que los resultados cacheados son `#REF!`.
- **Resolución:** la golden data se extrajo del **DOCX** (Tablas 2 y 3),
  no del XLSX. El XLSX no se usa como fuente de verdad numérica.

### 9. Etiquetas de banda inconsistentes en v1/v2

- Las claves de `FRECUENCIAS` incluían el canal ("2.4 GHz (Canal 6)")
  en v1/v2 pero no en v3/v4.
- **Resolución:** `FrequencyBand` separa `name` ("2.4 GHz") de
  `frequency_mhz` (2437). El canal se planea en una fase posterior
  (`AccessPoint.channel` ya existe).

### 10. Resultados 2.4 GHz de la Tabla 3 solo como rango

- El DOCX reporta los SOM de 2.4 GHz de los 4 APs como rango
  "30.88–34.22 dB" en el resumen. Los extremos (AP1 = 34.22,
  AP4 = 30.88) se verifican contra el motor.
- Los valores intermedios (AP2, AP3) en la golden data se recalcularon
  con la fórmula canónica (FSPL + Lm = 10 dB) porque una primera
  transcripción manual resultó imprecisa (32.20/31.23 → 32.04/31.13).
  Tolerancia de validación: `abs=0.05`.

---

## Configuración del entorno de desarrollo

- Python 3.14 instalado en `C:\Users\FAMILIA\.local\bin\python3.14.exe`.
- Dependencias: `pytest`, `PyYAML` (ver `requirements.txt`).
- Ejecutar pruebas desde `wifi_planner/`:
  `python -m pytest`
- Git inicializado con commit base `baseline: legacy project state...`.
