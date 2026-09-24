# Fórmulas — Wi-Fi Planner V1

Todas las fórmulas viven en `engine/`. La UI no las contiene.

Unidades: distancia `d` en **metros**, frecuencia `f` en **MHz**,
potencia en **dBm**, pérdidas en **dB**, ganancia en **dBi**.

---

## 1. Longitud de onda

```
λ = c / f
```

- `c = 3 × 10⁸ m/s` (velocidad de la luz, aproximación de ingeniería)
- `f` en Hz
- `λ` resulta en metros

Ejemplos:
- 2.4 GHz → λ = 12.5 cm
- 5 GHz → λ = 6 cm

Implementación: `engine.propagation.wavelength_m(frequency_hz)`

---

## 2. Free Space Path Loss (FSPL)

```
FSPL(dB) = 20 · log10(d) + 20 · log10(f_MHz) − 27.55
```

- `d` en metros, debe ser `> 0`
- `f` en MHz, debe ser `> 0`
- Resultado redondeado a 2 decimales (compatibilidad con legacy)

Validaciones: se lanza `ValueError` si `d ≤ 0` o `f ≤ 0`.

Implementación: `engine.propagation.path_loss_fspl_db(distance_m, frequency_mhz)`

---

## 3. Presupuesto de enlace (P_rx / RSSI)

```
P_rx = P_tx + G_tx − L_tx − FSPL − L_m + G_rx − L_rx − L_obstacles
```

| Símbolo | Significado | Unidad | Defecto |
|---|---|---|---|
| `P_tx` | Potencia de transmisión | dBm | 20.0 |
| `G_tx` | Ganancia antena TX | dBi | 3.0 |
| `L_tx` | Pérdidas TX | dB | 1.0 |
| `FSPL` | Pérdida en espacio libre | dB | calculado |
| `L_m` | Fade margin (margen de desvanecimiento) | dB | **10.0** |
| `G_rx` | Ganancia antena RX | dBi | 0.0 |
| `L_rx` | Pérdidas RX | dB | 1.0 |
| `L_obstacles` | Pérdida por materiales atravesados | dB | 0.0 (sin paredes) |

Notas:
- `L_m = 10 dB` por defecto (**decisión B**). Es configurable.
- Para reproducir las versiones legacy v3/v4 (que omitían `L_m`),
  usar `fade_margin_db = 0.0`.
- `L_obstacles` proviene de `trace_walls` cuando se pasan paredes
  (Fase 2); es `0.0` si no hay obstáculos.

Implementación: `engine.link_budget.link_budget(...)`

---

## 4. System Operating Margin (SOM)

```
SOM(dB) = P_rx − Sensibilidad
```

- `P_rx` en dBm
- Sensibilidad en dBm (defecto `-75.0`)
- Resultado en dB, redondeado a 2 decimales

Implementación: `engine.link_budget.system_operating_margin(...)`

---

## 5. Clasificación SOM (veredicto)

| Condición | Veredicto |
|---|---|
| `SOM ≥ 20 dB` | **APROBADO** |
| `10 dB ≤ SOM < 20 dB` | **RIESGO** |
| `SOM < 10 dB` | **FALLIDO** |

Los umbrales 20 y 10 son **configurables** (`CoverageThresholds`),
no números mágicos. Comparación con `≥` (**decisión D**).

Implementación: `engine.classifier.classify_som(som_db, thresholds)`

---

## 6. RSSI objetivo

```
P_rx > −67 dBm   →  CUMPLE
P_rx ≤ −67 dBm   →  NO CUMPLE
```

Comparación **estricta** (`>`), no `≥` (**decisión C**).
El umbral `-67 dBm` es configurable (`CoverageThresholds.rssi_target_dbm`).

Implementación: `engine.classifier.meets_rssi_target(rx_power_dbm, thresholds)`

---

## 7. Clases de cobertura (calidad)

| Clase | Condición (P_rx) |
|---|---|
| Excelente | `≥ −50 dBm` |
| Buena | `≥ −67 dBm` |
| Regular | `≥ −75 dBm` |
| Débil | `≥ −85 dBm` |
| Sin cobertura útil | `< −85 dBm` |

Todos los umbrales son configurables (`CoverageThresholds`).
Esta clasificación prepara el heatmap de fases posteriores.

Implementación: `engine.classifier.classify_quality(rx_power_dbm, thresholds)`

---

## 8. Pérdida por obstáculos (paredes reales)

```
L_total_obstacles = Σ L_wall_i          (por cada pared atravesada)

L_wall = L_referencia(material, banda) × (espesor_actual / espesor_referencia)
```

### Trazado (Fase 2)

Para cada par (AP → punto):

1. Se construye el segmento `path = Segment2D(AP, punto)`.
2. Cada `Wall` con `blocks_signal=True` se evalúa con
   `engine.intersection.segments_cross` (cruce interior estricto).
3. Las paredes cruzadas se ordenan por distancia desde el AP.
4. Cada crice aporta `L_wall` con el modelo de espesor.
5. El total entra al link budget como `L_obstacles`.

### Modelo de espesor (aproximación de ingeniería)

```
L_wall = L_ref × (t_actual / t_ref)
```

- `t_ref = material.thickness_default_m` (espesor de referencia).
- `L_ref = material.attenuation_db[band_id]` (atenuación de referencia).
- Si `t_actual = t_ref` → `L_wall = L_ref` (sin cambio).
- Si `thickness_m = None` en la pared → se usa `t_ref` (`L = L_ref`).
- Validaciones: `t_actual > 0`, `t_ref > 0`, material con datos para la banda.

**Advertencia:** el escalado lineal es una **aproximación de ingeniería**
para el modelo predictivo V1. **NO** es una simulación electromagnética
ni una curva de atenuación medida por capas.

Valores de referencia de materiales (estimaciones configurables,
ver `config/default_config.yaml` y `docs/decisions.md`):

| Material | 2.4 GHz | 5 GHz | Espesor ref. |
|---|---:|---:|---:|
| Drywall | 3 dB | 4 dB | 12 mm |
| Madera | 3 dB | 4 dB | 40 mm |
| Vidrio | 3 dB | 4 dB | 8 mm |
| Ladrillo | 6 dB | 8 dB | 120 mm |
| Concreto | 12 dB | 15 dB | 150 mm |
| Concreto reforzado | 15 dB | 20 dB | 200 mm |
| Metal | 25 dB | 30 dB | 5 mm |

### 6 GHz

No hay `L_ref` configurada para `band_6` en el catálogo V1.
Consultar atenuación lanza `MaterialAttenuationError`. No se inventan
valores ni se convierte silenciosamente 5 → 6 GHz.

### Openings (Fase 8): reemplazo en el hueco

Un `Opening` (puerta / ventana / pass-through) vive sobre una pared con
offsets métricos desde `wall.segment.start` (decisión BF). La posición
del cruce sobre la pared es `d = u × longitud_pared`, con `u` el
parámetro del cruce devuelto por `engine.intersection`.

```
L_cruce = L_wall(banda, espesor)   si d ∉ ningún opening de la pared
        = override(banda) o 0 dB   si d ∈ algún opening (reemplazo)
```

- **Semántica de reemplazo (decisión BG):** el override **sustituye**
  a la atenuación del material; jamás se suman (`L_material +
  L_override` no existe).
- **Unión con intervalo cerrado:** un cruce cuenta como hueco si
  `start − ε ≤ d ≤ end + ε` con `ε = EPSILON_GEOMETRY = 1e-9`
  (los extremos pertenecen al hueco).
- **Orden canónico `(start, id)`:** con openings solapados gana el
  primero en ese orden (resultado independiente del orden de
  inserción; `group_openings_by_wall`).
- **Override por banda:** `opening.attenuation_override_db[band_id]`;
  si la banda no está en el dict ⇒ **0 dB** (sección abierta).
- **6 GHz:** un cruce en hueco no consulta el catálogo de materiales ⇒
  0 dB (o el override si existe). Los cruces **sólidos** siguen
  lanzando `MaterialAttenuationError` como antes.
- El `WallCrossing`/`CrossingLoss` del cruce lleva `opening_id`
  (None si es sección sólida), de modo que el detalle del link
  budget identifica el hueco.
- Sin `openings` (o lista vacía) el resultado es **idéntico** al de
  Fase 2–7: regresión garantizada.

Implementación: `engine.obstacles.trace_walls`,
`core.wall.group_openings_by_wall`.

Implementación: `engine.obstacles.wall_attenuation_db`,
`engine.obstacles.trace_walls`.

---

## 10. Heatmap de cobertura (Fase 4) — estimación, no EM

**Disclaimer:** el heatmap es una **estimación predictiva** del modelo
configurado (FSPL + presupuesto de enlace + atenuación de materiales
configurables). **NO** es una simulación electromagnética completa ni
sustituye mediciones en sitio.

### Muestreo (`engine.coverage_grid.CoverageGrid`)

- Puntos en múltiplos de `resolution_m` desde `(0,0)`, más un punto de
  borde si la dimensión no es múltiplo exacto (decisión L).
- Límites V1: `resolution_m ≥ 0.05 m`, `point_count ≤ 100_000`.
- Ejemplo: 12 × 8 m @ 0.50 m → 25 × 17 = **425** puntos.

### Flujo por punto del grid

Misma cadena canónica que las secciones 1–8, sin fórmulas nuevas:

```
para cada punto p en CoverageGrid.points():
    L_obstacles = Σ L_wall   (trace_walls AP → p, decisión K)
    P_rx = link_budget(..., L_obstacles)
    SOM  = P_rx − sensibilidad
    SNR  = P_rx − piso de ruido      (Fase 7, ver sección 11)
    calidad = classify_quality(P_rx, umbrales)
```

- **Un solo AP** por heatmap (decisión M).
- `%` de cobertura: denominador = **todos los puntos del grid**
  (decisión P).
- Si un punto del grid cae **sobre el AP** (`d = 0`), `evaluate_link`
  usa un piso `MIN_FSPL_DISTANCE_M = 0.1 m` solo para FSPL
  (decisión T); la fórmula FSPL no se modifica.
- Visualización: color continuo de `P_rx` (métrica `rssi`, por
  defecto) o de `SNR` (métrica `snr`, Fase 7) en `ui/coverage_renderer`
  (solo presentación; no altera umbrales RF).
- Invalidación + debounce al editar modelo (decisión O).

---

## 9. Ejemplo del DOCX (validación)

Distancia 10 m, 5 GHz (5180 MHz), con `L_m = 10 dB`:

```
FSPL = 20·log10(10) + 20·log10(5180) − 27.55 = 66.74 dB
P_rx = 20 + 3 − 1 − 66.74 − 10 + 0 − 1     = −55.74 dBm
SOM  = −55.74 − (−75)                       = 19.26 dB  → RIESGO
```

Este caso está incluido en la golden data (`tests/fixtures/golden_data.py`,
Tabla 2) y se valida en `tests/test_link_budget.py`.

---

## 11. SNR, piso de ruido y metadatos RF (Fase 7)

### Relación señal/ruido

```
SNR(dB) = P_rx − Noise Floor
```

- `P_rx` es el RSSI de la sección 3 (mismo valor, misma fórmula).
- `Noise Floor` (piso de ruido) es un parámetro de la radio
  (`RadioConfiguration.noise_floor_dbm`), por defecto **−95 dBm**,
  rango `[-200, 0]`, finito (decisión AU). **No es una constante
  universal**: depende del entorno y del receptor.
- Redondeo a 2 decimales, igual que el resto de la cadena.

Implementación: `engine.link_budget.signal_to_noise_ratio`;
`evaluate_link` lo guarda en `LinkEvaluation.snr_db` junto con el
`noise_floor_dbm` usado.

### Umbral de SNR

```
SNR cumple objetivo  ⟺  SNR ≥ snr_target_db
```

- `CoverageThresholds.snr_target_db`, por defecto **25 dB**
  (rango `[-20, 60]`), comparación `>=` (decisión AW).
- Coherencia de los defaults: con piso −95 y objetivo RSSI −67, el
  SNR en el umbral RSSI es `(−67) − (−95) = 28 dB ≥ 25 dB`; cumplir
  el RSSI implica cumplir el SNR, así que los defaults no generan el
  cuadrante contradictorio “RSSI bueno / SNR malo”.
- El RSSI objetivo **sigue estricto** (`>`, decisión C): son
  comparaciones distintas a propósito.

### Por qué el SNR complementa (y no sustituye) a RSSI/SOM

| Métrica | Responde | Depende de |
|---|---|---|
| RSSI (`P_rx`) | ¿Llega suficiente potencia? | potencia, distancia, paredes |
| SOM | ¿Cuánto margen sobre la sensibilidad? | `P_rx` y sensibilidad |
| SNR | ¿Cuánta potencia hay sobre el ruido? | `P_rx` y piso de ruido |

Son tres preguntas distintas sobre el mismo enlace: F7 las muestra en
paralelo (diagnóstico en cuatro cuadrantes `rf_diagnostic`,
decisión BC) sin alterar las clases de calidad ni el veredicto SOM.

### Ancho de canal y estándar: metadatos, no fórmula

- `channel_width_mhz` ∈ `(20, 40, 80, 160)` (default 20) se valida
  **contra la banda** al simular (`allowed_channel_widths_mhz`):
  familia 2.4 GHz (`f < 3000 MHz`) admite 20/40 MHz; 5/6 GHz admite
  20/40/80/160 MHz. Un ancho incompatible ⇒ `ValueError` (decisión AY).
- **FSPL no recibe el ancho de canal.** FSPL es pérdida en espacio
  libre y no tiene término de ancho; usar el ancho en el link budget
  sería física inventada. Su papel en F7 es solo coherencia de
  configuración.
- `wifi_standard` ∈ `802.11n/ac/ax/be` (default `802.11ax`) es un
  metadato etiquetado por `wifi_generation()` (“Wi-Fi 4/5/6/7”,
  “Wi-Fi 6E” con `ax` a `f ≥ 5925 MHz`). Sin efecto RF (decisión AX).

### Estadísticas de SNR (Fase 7)

Además de las de RSSI/clases/dominancia (secciones 7 y 10):

```
snr_min_db, snr_max_db, snr_avg_db, snr_target_db,
points_meeting_snr_target, snr_ratio = points / point_count
```

En combinación multi-AP el SNR proviene del AP **ganador por RSSI**
(decisión BB): nunca se promedian SNR entre APs (eso sería
interferencia encubierta, fuera del alcance de F7).
