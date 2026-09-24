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
