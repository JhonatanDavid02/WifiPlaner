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
L_total_obstacles = Σ L_wall_i  +  Σ L_obstáculo_j     (Fase 9)

L_wall = L_referencia(material, banda) × (espesor_actual / espesor_referencia)
L_obstáculo = override(banda) o L_referencia(material, banda)   (sin espesor)
```

Sin obstáculos de mobiliario (`obstacles = ()`) la segunda suma es 0 y
la fórmula es exactamente la de Fase 2–8.

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

### Obstáculos de mobiliario (Fase 9)

Un `Obstacle` (mesa, rack, columna…) es un footprint `Rect` alineado a
ejes en metros, sin altura ni giro (decisión BL). Se traza con la MISMA
primitiva de intersección que las paredes: `segment_crossing_parameters`
contra los cuatro bordes del rect (`Rect.edge_segments`).

```
L_obstáculo = override(banda)    si attenuation_override_db lo define
            = L_material(banda)  si no (atenuación de referencia)

L_total = Σ L_cruce_i (paredes + openings) + Σ L_obstáculo_j
          en orden canónico: (distancia, tipo —pared antes que
          obstáculo—, id) — decisión BN
```

- **Un solo atravesamiento por obstáculo:** si el trayecto tiene ≥ 1
  cruce interior estricto con los bordes, se registra UNA sola pérdida
  con la menor distancia (la entrada en el footprint). Tocar
  exactamente una esquina, correr por encima de un borde (colineal) o
  quedar completamente dentro del rect ⇒ **0 cruces** — misma
  convención que las paredes (decisiones F y G, decisión BN).
- **Reemplazo, nunca suma (BM):** el override **sustituye** a la
  atenuación de referencia del material. Metal (25 dB) con override
  `band_2_4 = 7` ⇒ 7 dB, no 32 dB.
- **Sin escala de espesor:** el footprint no es un espesor de pared;
  se usa la referencia del material tal cual.
- **Sin doble atenuación (BN):** la pérdida del obstáculo es
  independiente de la pared u opening de la misma trayectoria. Un
  opening sigue reemplazando SOLO la pérdida de su sección de pared;
  el total de un cruce en hueco + obstáculo es `0 + L_obstáculo`.
- **6 GHz:** un obstáculo **cruzado** sin override `band_6` lanza
  `MaterialAttenuationError` (igual que una pared sólida). Un
  obstáculo no cruzado no se consulta en absoluto ⇒ no lanza error.
- **Descarte AABB previo:** los obstáculos con caja envolvente disjunta
  del trayecto se descartan antes de las cuatro intersecciones (no
  cambia la semántica; solo evita trabajo).
- El `ObstacleCrossing`/`CrossingLoss` del cruce lleva `obstacle_id`
  (None en los cruces de pared), de modo que el detalle del link
  budget distingue paredes de mobiliario.
- Sin `obstacles` (o lista vacía) el resultado es **idéntico** al de
  Fase 2–8: regresión byte-idéntica verificada.

Implementación: `engine.obstacles.obstacle_attenuation_db`,
`engine.obstacles.trace_obstacles`, `engine.obstacles.trace_walls`.

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

---

## 12. Canales Wi-Fi (Fase 10): número lógico ↔ frecuencia central derivada

### Catálogo por familia (fuente única: `core/channel.py`)

El **número de canal** es un identificador lógico; la **frecuencia
central** es un valor físico que se **deriva** (nunca se almacena ni se
recibe del archivo). Fórmulas (decisión BQ):

```
2.4 GHz:  f_c(n) = 2412 + 5·(n−1) MHz   para n = 1…13   (n = 14 ⇒ 2484)
5 GHz:    f_c(36…64)  = 5180 + 20·((n−36)/4)
          f_c(100…144)= 5500 + 20·((n−100)/4)
          f_c(149…161)= 5745 + 20·((n−149)/4)
          f_c(165)    = 5825
6 GHz:    f_c(n) = 5950 + 5·n   para n = 1, 5, 9, …, 233  (233 ⇒ 7115)
```

La **familia** de una banda se decide con la misma frontera que los
anchos de canal (decisión AY): `f < 3000 MHz` → 2.4 GHz;
`3000 ≤ f < 5925` → 5 GHz; `f ≥ 5925` → 6 GHz. Referencias: canal 6 =
2437 MHz, canal 36 = 5180 MHz, canal 37 = 6135 MHz (= banda 6 por
defecto).

Referencia por banda (`default_channel`): el canal cuyo centro coincide
con `FrequencyBand.frequency_mhz` (2437 → 6, 5180 → 36, 6135 → 37);
si no hay coincidencia exacta, el más cercano (empate → menor número).

### El canal NO entra en ninguna fórmula de propagación

```
FSPL(d) = 20·log10(d) + 20·log10(f_banda) + 32.44     (sección 2)
P_rx    = P_tx + G_tx − L_tx + G_rx − L_rx − FSPL − Σ pérdidas   (sección 3)
```

`f_banda` es **`FrequencyBand.frequency_mhz`** (2437 / 5180 / 6135).
La frecuencia central del canal elegido no aparece en FSPL, en el
presupuesto de enlace, en SOM, en SNR ni en la calidad: cambiar un AP
del canal 36 al 40 produce evaluaciones **idénticas** (decisión BR;
probado por el test A/B de `tests/test_channels.py` y por el snapshot
`f10_regression_snapshot.py`). Lo mismo vale para el ancho de canal
(sección 11): es metadato de configuración.

### Centro independiente del ancho; validación del triple

- El centro **no cambia con el ancho**: canal 36 con 80 MHz ⇒ centro
  5180 MHz (el ancho define el rastro ocupado, no el centro).
- El triple `(banda, canal, ancho)` se valida en un solo punto
  (`validate_channel_config`, decisión BT): el canal debe pertenecer
  al catálogo de la familia de la banda y el ancho a la regla de
  familia de la sección 11 (2.4 → 20/40; 5/6 → 20/40/80/160).
- Los números **se solapan entre familias** (149 y 165 existen en
  5 GHz y en 6 GHz con centros distintos): la validación es siempre
  contextual al par (banda, canal).

### Configuración por AP (Fase 10)

`AccessPoint.band_id + channel + radio.channel_width_mhz` declaran dónde
transmite cada AP. La simulación resuelve
`ap.band_id o banda de la corrida o banda activa` (decisión BS); los
proyectos sin `band_id` (F1–F9) se comportan exactamente como antes.
La frecuencia central derivada es **metadata visible** (panel y
lienzo), no un parámetro de la fórmula.

---

## 13. Interferencia espectral (Fase 11): ocupación, solapamiento y agregación

> F11 añade **interacción entre emisores** como información paralela.
> Nada de esta sección modifica las secciones 1–12: RSSI, SOM, SNR,
> calidad y veredicto de F1–F10 son idénticos (A/B byte-idéntico).
> Implementación: `engine/interference.py`.

### Ocupación espectral (decisión BY)

Cada emisión se modela como un rectángulo ideal centrado en la
frecuencia central derivada del catálogo (sección 12):

```
intervalo = [ f_c − W/2 , f_c + W/2 )          (MHz)
```

- `f_c` = `WifiChannel.center_frequency_mhz` del canal del AP (F10).
- `W`  = `radio.channel_width_mhz` del AP (20/40/80/160).
- Intervalos **semiabiertos**: dos emisiones que solo se tocan en un
  borde no se solapan (determinismo).

### Solapamiento entre dos emisiones (decisión BY)

```
overlap       = max(0, min(hi_a, hi_b) − max(lo_a, lo_b))
overlap_ratio = overlap / min(W_a, W_b)          ∈ [0, 1]
```

- `overlap_ratio = 1.0` cuando son idénticas, o cuando el ancho menor
  queda contenido en el mayor.
- `overlap = 0` para emisiones disjuntas o solo tocadas: **no hay
  contribución** (nunca se usa −∞).

### Contribución efectiva de un interferente (decisión BZ)

Con **densidad espectral de potencia plana** sobre el ancho del
interferente, la fracción de su potencia que cae dentro del intervalo
interesado es `overlap / W_i`:

```
I_i = P_rx,i + 10·log10( overlap / W_i )        [dBm]   si overlap > 0
I_i = None                                        si overlap = 0
```

- `P_rx,i` es la potencia recibida del interferente calculada con el
  **mismo** pipeline F1–F10 (FSPL, paredes, openings, obstáculos): no
  hay física nueva, solo una combinación posterior.
- Propiedades: monótona creciente en `overlap`, acotada
  `I_i ≤ P_rx,i` (pues `overlap ≤ W_i`), `overlap = W_i ⇒ I_i = P_rx,i`.
- Redondeo a 2 decimales. Fórmula aislada en
  `effective_interference_dbm` (reemplazable en F12/F14).

### Agregación en dominio lineal (decisión CA)

Los dBm **no se suman**; se convierten a mW, se suman y se vuelve a dBm:

```
I_total = 10·log10( Σ_i 10^(I_i / 10) )          [dBm]
I_total = None        si Σ no tiene términos
```

- Implementación: `dbm_to_mw` / `mw_to_dbm` / `aggregate_dbm`
  (única definición en `engine/interference.py`), 2 decimales.
- Orden canónico de suma: `(-potencia, ap_id)`; **dominante** = mayor
  contribución, empate ⇒ menor `access_point_id` (determinismo total).

### Supuestos y limitaciones (honestidad del modelo)

- Rectángulo ideal: **sin** lobulaciones, guard bands, ruido
  espectral ni máscara PHY real.
- PSD **plana** dentro del ancho del interferente (hipótesis de la
  fórmula anterior).
- Solo bandas **iguales** y APs **con canal** interactúan (decisión
  CB); un AP sin canal queda fuera del modelo espectral pero su RSSI
  histórico sigue funcionando.
- No se modela delay spread, temporización, captura, ni ganancia
  direccional: es una **estimación de planificación**, no una
  simulación electromagnética.

### RSSI ≠ interferencia (información paralela)

```
LinkEvaluation:
  rx_power_dbm       ← F1–F10 (SEÑAL deseada; intocable, decisión BX)
  interference_dbm   ← F11 (INTERFERENCIA agregada percibida; paralela)
```

- La anotación **no altera** `rx_power_dbm`, `som_db`, `snr_db`,
  `quality` ni `verdict` (A/B en `tests/test_interference.py` y en
  `accept_f11.py` paso 5).
- `interference_dbm = None` ⇒ sin contribuidores o sin modelo;
  `interference_evaluated = False` ⇒ el modelo F11 no corrió.
- `combine_results` sigue eligiendo el **mayor RSSI** por punto: la
  interferencia viaja como dato de la evaluación ganadora.

### Frontera F11 → F12 (decisión CD, ejecutada en F12/CF)

La fórmula que F11 dejó prevista:

```
SINR(dB) = P_rx_deseado − 10·log10(10^(NoiseFloor/10) + 10^(I_total/10))
```

**no estaba implementada en F11** (sin campo `sinr`, sin CCA/CSMA, ni
umbral de colisión, ni optimización de canal). F12 la implementa como
capa paralela — véase la **sección 14**. CCA/CSMA, throughput, roaming
y optimización de canales **siguen fuera de alcance** (lo comprueba
`audit_f12.py`).

---

## 14. SINR (Fase 12): señal sobre ruido + interferencia

> F12 convierte la interferencia de F11 en métrica de calidad de
> enlace. Nada de esta sección modifica las secciones 1–13: RSSI, SOM,
> SNR, calidad, veredicto e interferencia siguen siendo idénticos
> (A/B byte-idéntico; regresiones F9/F10/F11 intactas).
> Implementación única: `engine/sinr.py` (decisión CF).

### Relación señal / (ruido + interferencia)

```
SINR = P_rx − 10·log10( 10^(NoiseFloor/10) + 10^(I_total/10) )    [dB]
```

- `P_rx` es el RSSI deseado (sección 3, **intocable**), `NoiseFloor`
  el piso de ruido de la radio (sección 11) y `I_total` la
  interferencia agregada de F11 (`interference_dbm`, sección 13).
- Los dBm **no se suman**: el denominador se combina en el dominio
  lineal (mismas utilidades dBm↔mW, decisión CA).
- **Estabilidad numérica (decisión CF):** con
  `D = max(N, I)` y `m = min(N, I)`:

  ```
  denominador = D + 10·log10( 1 + 10^((m − D)/10) )
  ```

  el exponente es siempre ≤ 0 (`10^x ∈ (0, 1]`): sin overflow, sin
  división por cero y con underflow benigno (`10^x → 0 ⇒ log10(1)=0`).
  Valores no finitos ⇒ `ValueError` (nunca se propaga `nan`/`inf`).
- Redondeo a **2 decimales** en la función (patrón SNR/SOM).

### Caso sin interferencia modelada (decisión CG)

```
interference_dbm = None   ⇒   denominador = NoiseFloor   ⇒   SINR = SNR
```

con igualdad **exacta** (misma aritmética redondeada que
`signal_to_noise_ratio`): vale para proyectos F1–F10, AP sin canal,
canales sin solapamiento, un solo AP y corridas sin contexto. El
modelo F11 puede haber corrido y dejar `interference_dbm = None`
(0 contribuidores): sigue cumpliéndose.

### Secuencia canónica por punto (decisión CF)

```
simular propagación → RSSI → SNR → (F11) interferencia → (F12) SINR
                     → combinar multi-AP (sigue MAX RSSI)
```

`evaluate_link` entrega ya `sinr_db`/`sinr_meets_target` (sin I
⇒ igual al SNR); la sesión llama a `annotate_sinr` **después** de
`annotate_interference` y **antes** de `combine_results`, de modo que
la evaluación ganadora transporta su propio SINR. Nada de F1–F11
cambia: `combine_results`/`_better` siguen decidiendo solo por
`rx_power_dbm` y empate ⇒ menor `access_point_id`.

### Umbral de SINR (decisión CH)

```
cumple = SINR ≥ sinr_target_db          (default 25 dB; rango [-20, 60])
```

- Comparación `>=` como el SNR (decisión AW); distinta de la
  comparación estricta del RSSI objetivo (decisión C).
- Default 25 dB = objetivo de SNR de F7: como **SINR ≤ SNR** siempre
  (el denominador añade I al ruido), cumplir SINR(25) ⇒ SNR(25); sin
  interferencia modelada ambos umbrales se cumplen juntos.
- Diagnóstico propio de dos estados (`sinr_diagnostic`):
  «SINR adecuado» / «SINR bajo». **No** toca `rf_diagnostic`
  (sus 4 salidas de F7 siguen congeladas).

### Estadísticas de SINR (Fase 12)

Único bloque `sinr_stats_block` (definido en `engine/sinr.py`,
consumido por simulador, combinador, panel y UI):

```
sinr_min_db, sinr_max_db, sinr_avg_db, sinr_target_db,
points_meeting_sinr_target, sinr_ratio = points / point_count
```

Denominador: **puntos totales del grid** (mismo criterio que
`snr_ratio`/`coverage_ratio`). En combinación multi-AP el SINR es el
del AP **ganador por RSSI** (decisión BB/CF): jamás se promedia entre
APs. `{}` si no hay evaluaciones ni SINR anotado ⇒ la UI distingue
«sin datos» de «0 %».

### Límites (honestidad del modelo)

- SINR aquí es **RSSI vs ruido+I**: no modela CCA/CSMA, captura,
  hidden node, temporización, MCS/throughput ni roaming (fuera de
  alcance en F12, verificado por `audit_f12.py`).
- Hereda todos los supuestos de F1–F11: FSPL, PSD plana, rectángulo
  ideal de ocupación, una sola banda por emisión.
- Es **información paralela**: no redefinirá RSSI/SOM/SNR/interferencia
  ni decide ganadores; el heatmap de SINR es presentación (escala
  0–45 dB con la misma dirección que SNR —mayor=mejor—, no la escala
  invertida de interferencia).
