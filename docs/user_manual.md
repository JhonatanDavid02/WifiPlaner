# Wi‑Fi Planner — Manual completo de uso y referencia

> Documento generado a partir del código fuente real del repositorio
> (`wifi_planner/`, rama `master`). Cada etiqueta de botón/campo aparece
> **tal cual la escribe la aplicación**. Las referencias `archivo:línea`
> apuntan al código para quien quiera mirar dentro.
>
> Contenido: instalación · ventana · **cada menú** · **cada botón** ·
> **cada herramienta** · **cada panel y campo** · diálogos · atajos ·
> capas · motor RF (heatmap, simulación, clientes) · persistencia ·
> recetas de uso · límites y errores · pruebas · mapa de archivos · glosario.

---

# 1. ¿Qué es Wi‑Fi Planner?

Wi‑Fi Planner es un **editor 2D de planos para dimensionar redes Wi‑Fi**.
Sobre un plano en metros dibuja paredes, puertas, ventanas, muebles, puntos
de acceso (AP) y clientes, y **calcula la cobertura RF real** con un motor de
simulación propio (FSPL + atenuación de materiales + presupuesto de enlace).

Lo que NO es: no hay modelo RF alternativo dentro de la interfaz, ni círculos
artificiales de cobertura. La UI **nunca calcula fórmulas**: solo modela,
invoca al motor (`engine/`) y pinta resultados (`ui/__init__.py:1-7`).

**Alcance funcional actual (Fases F1 → F15.2):**

| Fase | Qué aporta |
|---|---|
| F1–F3 | Puntos sueltos, materiales, editor 2D |
| F4–F5 | Heatmap espacial (`CoverageGrid`) y multi‑AP (mejor RSSI por punto) |
| F6 | Persistencia JSON versionada (`schema_version = 1`) |
| F7 | Piso de ruido, SNR, estándar Wi‑Fi, ancho de canal |
| F8 | Espacios (zonas) y aperturas (puertas/ventanas/pasos) |
| F9 | Obstáculos de mobiliario |
| F10 | Banda/canal/ancho **por AP** |
| F11 | Interferencia espectral (métrica «Interferencia») |
| F12 | SINR (métrica «SINR») |
| F13 | Optimización de canales (propuesta, no automática) |
| F14 | Plantas, dimensiones explícitas, deshacer/rehacer, gestos, rejilla, medir |
| F15 | Arrastre con ratón, **capa de cobertura del AP seleccionado**, **estado de señal de los clientes** |

**955 pruebas** automatizadas (`python -m pytest`) — todo el comportamiento
descrito aquí está cubierto por tests.

---

# 2. Instalación y arranque

## 2.1 Requisitos

- **Python 3.10 o superior** (desarrollado y probado con 3.14).
- **Tkinter**: viene con Python en Windows/macOS. En Debian/Ubuntu:
  `sudo apt install python3-tk`.
- Dependencias (`requirements.txt` en la raíz):

```
pytest>=8.0     # solo para ejecutar las pruebas
PyYAML>=6.0     # carga config/default_config.yaml
Pillow>=10.0    # imágenes del heatmap y del resaltado
```

Instalación:

```bash
pip install -r requirements.txt
```

## 2.2 Arrancar el programa

```bash
cd wifi_planner
python main.py
```

(`main.py:25-27` llama a `ui.run_app()`.) La ventana se abre con título
**Wi‑Fi Planner**, geometría `1180x760` y tamaño mínimo `960x640`.

## 2.3 Ejecutar las pruebas

```bash
cd wifi_planner
python -m pytest            # 955 pruebas, ~20 s
python -m pytest tests/test_heatmap.py -q     # un archivo concreto
```

(`pytest.ini`: `testpaths = tests`, `pythonpath = .`, `-q`.)

---

# 3. La primera pantalla

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Archivo  Editar  Ver                                                       │  ← menús
├────────────────────────────────────────────────────────────────────────────┤
│ Herramienta: (•Seleccionar)( Pared)( AP)( Cliente)( Zona)( Objeto)( Medir) │  ← fila 1
│ Banda: [2.4 GHz▾]  AP: [Todos los AP▾]  Res.: [0.50▾]                     │
│ [x] Heatmap  Métrica: [RSSI▾] │ [Eliminar][Dimensiones…][Config RF…]…      │  ← fila 2
├──────────────────────────────────┬─────────────────────────────────────────┤
│                                  │ Selección            (texto)            │
│        PLANO (lienzo 2D)         │ Configuración RF del AP                │
│   ┌ piso + rejilla + heatmap ┐   │ Pared / Espacio / Apertura / Objeto    │
│   │  APs · clientes · paredes│  │ Posición (m)  [X][Y] [Aplicar posición]│
│   └ leyenda arriba-izquierda ┘   │ Simulación / Heatmap                   │
│                                  │ [Ejecutar simulación]                  │
├──────────────────────────────────┴─────────────────────────────────────────┤
│ X: 3.20 m  Y: 5.10 m | Espacio: 12 × 8 m | Escala… Zoom… | Herramienta…  │  ← estado
└────────────────────────────────────────────────────────────────────────────┘
```

Al crear un proyecto nuevo el lienzo arranca **vacío** con un piso por
defecto de **12 × 8 m** (ajustables), rejilla visible cada **0.5 m**,
heatmap **activado** y resolución RF **0.50 m**.

---

# 4. Menús (barra de menús)

## 4.1 Menú **Archivo**

| Elemento | Atajo | Qué hace |
|---|---|---|
| **Nuevo** | `Ctrl+N` | Pide confirmación si hay cambios sin guardar y abre el diálogo *Dimensiones del espacio* (12 × 8 m por defecto). Al aplicar crea el proyecto, limpia la vista y recalcula el heatmap. |
| **Abrir…** | `Ctrl+O` | Diálogo *Abrir proyecto* con filtros `Proyecto Wi‑Fi Planner (*.json)` y `Todos los archivos (*.*)`. Carga atómica: si el archivo es inválido, no se toca el proyecto abierto. |
| *(separador)* | | |
| **Guardar** | `Ctrl+S` | Si el proyecto no tiene ruta, actúa como *Guardar como…*. Fuerza el sufijo `.json`. |
| **Guardar como…** | `Ctrl+Shift+S` | Diálogo *Guardar proyecto como*. Escritura **atómica** (`.tmp` → `fsync` → `rename`), así que un corte de luz no corrompe el archivo. |
| *(separador)* | | |
| **Salir** | — | Confirmación si hay cambios sin guardar, cancela el cálculo pendiente y cierra. También al cerrar la ventana (X). |

El título de la ventana pasa a `NombreProyecto *` cuando hay cambios sin guardar.

## 4.2 Menú **Editar**

| Elemento | Atajo | Qué hace |
|---|---|---|
| **Deshacer** | `Ctrl+Z` | Restaura el estado anterior (proyecto + selección). Si hay un arrastre a medias, lo cancela en lugar de deshacer. Máximo **50** pasos. |
| **Rehacer** | `Ctrl+Y` (o `Ctrl+Shift+Z`) | Reaplica el paso deshecho. |
| *(separador)* | | |
| **Eliminar** | también botón **Eliminar** y teclas `Supr`/`Retroceso` | Borra el elemento seleccionado. Al borrar una pared borra también sus aperturas; si el heatmap apuntaba a un AP borrado, vuelve a «Todos los AP». |

## 4.3 Menú **Ver**

| Elemento | Atajo | Qué hace |
|---|---|---|
| **Acercar** | `Ctrl++` | Zoom ×1.25 centrado en el lienzo (también rueda del ratón). |
| **Alejar** | `Ctrl+-` | Zoom ÷1.25 (también rueda del ratón). |
| **Vista normal** | `Ctrl+0` | Zoom 1× y desplazamiento a cero (el piso se ajusta al lienzo). |
| *(separador)* | | |
| **Ajustar a rejilla** (casilla) | — | Activa/desactiva el imán de rejilla al dibujar y arrastrar. Es preferencia de vista: **no** marca el proyecto como modificado. |
| **Paso de rejilla 0.1 m** (radio) | — | Paso visual de la rejilla dibujada. No afecta a la resolución RF. |
| **Paso de rejilla 0.25 m** | — | Ídem |
| **Paso de rejilla 0.5 m** | — | Ídem (por defecto) |
| **Paso de rejilla 1 m** | — | Ídem |

> ⚠️ **Rejilla visual ≠ resolución RF.** La rejilla (menú *Ver*) es solo una
> guía para dibujar. La **Res.:** de la barra superior es la resolución de la
> malla de simulación (`CoverageGrid`) y sí cambia los resultados.

---

# 5. Barra de herramientas (dos filas)

## 5.1 Fila 1

| Control | Etiqueta | Valores | Efecto |
|---|---|---|---|
| Etiqueta | `Herramienta:` | — | — |
| Radios | `Seleccionar` `Pared` `AP` `Cliente` `Zona` `Objeto` `Medir` | — | Cambian la herramienta activa (ver §7). Atajos: `s` `w` `a` `c` `e` `o` `m`. |
| Etiqueta | `Banda:` | — | — |
| Combobox | — | `2.4 GHz`, `5 GHz`, `6 GHz` | Banda **activa** del proyecto. Al cambiarla: se invalida el heatmap, se redibuja el plano y se refresca la simulación. |
| Etiqueta | `AP:` | — | — |
| Combobox | — | `Todos los AP` + ids (`AP-001`, …) | **Ámbito del heatmap**: combinado (todos los AP, gana el mejor RSSI por punto) o de un AP concreto. |
| Etiqueta | `Res.:` | — | — |
| Combobox | — | `1.00`, `0.50`, `0.25` | Resolución del `CoverageGrid` en metros. Menor = más puntos = más preciso y más lento. |

## 5.2 Fila 2

| Control | Etiqueta | Efecto |
|---|---|---|
| Casilla | **`Heatmap`** | Muestra/oculta la capa del heatmap. **Desactivarlo no recalcula RF** (solo oculta); al activarlo se (re)calcula. El resaltado del AP seleccionado se mantiene en cualquier caso. |
| Combobox | `Métrica:` → `RSSI`, `SNR`, `Interferencia`, `SINR` | Cambia **solo la visualización** (color/valor por punto). **No** vuelve a ejecutar la simulación: se repinta la imagen con los datos ya calculados. |
| Botón | **`Eliminar`** | Borra la selección (igual que *Editar → Eliminar*). |
| Botón | **`Dimensiones…`** | Diálogo *Dimensiones del espacio* con las medidas actuales. Cambiarlas recalcula todo. |
| Botón | **`Config RF…`** | Diálogo *Configuración RF* (piso de ruido, objetivos SNR/SINR/RSSI, estándar, ancho). Aplicar afecta a **todos** los APs. |
| Botón | **`Opt. canal…`** | Calcula una **propuesta** de canales (no modifica nada hasta que pulses *Aplicar propuesta*). |
| Botón | **`Simular`** | Ejecuta la simulación puntual y escribe el resumen en el panel derecho (ver §13). |

---

# 6. Lienzo: qué representa cada cosa

## 6.1 Capas (orden de dibujo, de abajo a arriba)

`ui/editor_canvas.py:192-279`

1. **Rectángulo del piso** con sus medidas (`12 m` arriba, `8 m` a la izquierda).
2. **Rejilla** visual (paso elegido en *Ver*). Se duplica el paso si habría más de 300 líneas por eje.
3. **Heatmap** (imagen del RSSI/SNR/interferencia/SINR).
4. **Cobertura del AP seleccionado** (capa de resaltado, encima del heatmap).
5. **Espacios** (zonas semitransparentes con su nombre).
6. **Obstáculos** (muebles/columnas, huellas semitransparentes con nombre).
7. **Paredes** (con huecos) y encima las **aperturas** (puerta/ventana/paso) + etiqueta de material.
8. **Previsualizaciones** en curso (pared, zona, objeto, medición).
9. **APs y clientes** con sus etiquetas.
10. **Leyenda** (arriba a la izquierda).

## 6.2 Símbolos

| Elemento | Cómo se ve | Selección |
|---|---|---|
| **AP** | Círculo color arena con marcas de antena, etiqueta `AP-001` y, si tiene canal, subtítulo `CH 6 · 20 MHz` | Anillo punteado azul alrededor + color más claro |
| **Cliente** | Punto verde con etiqueta `CLIENT-001` + **indicador de calidad de señal** (halo coloreado y punto macizo arriba a la derecha) | Punto más grande y color más claro |
| **Pared** | Línea clara con el id del material (`concrete`) encima | Línea azul más gruesa + **manijas** cuadradas en los extremos |
| **Apertura** | Segmento de color en la pared: puerta ámbar, ventana cian, paso morado | Más gruesa y azul |
| **Espacio** | Rectángulo azulado semitransparente con su nombre | Contorno azul más grueso |
| **Obstáculo** | Huella marrón semitransparente con su nombre | Contorno azul más grueso |
| **Medición** | Línea punteada ámbar con el texto `3.20 m` | — |

## 6.3 Orden de selección (al hacer clic, `editor_canvas.py:649-716`)

Si dos cosas se solapan, gana en este orden:
**AP → Cliente → Apertura → Objeto → Pared → Espacio**.
Para una pared seleccionada, arrastrar **cerca de un extremo** (10 px) mueve
solo ese extremo; si no, se mueve la pared entera.

---

# 7. Herramientas: qué pasa en cada caso

| Herramienta (tecla) | Clic | Arrastre | Soltar |
|---|---|---|---|
| **Seleccionar** (`s`) | Si tocas algo → lo selecciona y prepara su arrastre. Si tocas **hueco** → deselecciona y **empieza a desplazar el plano** (cursor de flechas). | Mueve el objeto (AP, cliente, pared, espacio u objeto) con imán de rejilla si está activo. | Cierra el movimiento como **una sola** entrada de deshacer. |
| **Pared** (`w`) | **2 clics**: primero marca el inicio, después traza la pared. Sigue activa para encadenar paredes. | Muestra una línea punteada de previsualización con el imán. | — (la pared se crea en el 2.º clic) |
| **AP** (`a`) | Crea el AP y **vuelve automáticamente a *Seleccionar*** (para que puedas moverlo enseguida). | — | — |
| **Cliente** (`c`) | Crea el cliente y **vuelve a *Seleccionar***. | — | — |
| **Zona** (`e`) | **2 clics** (esquina → esquina opuesta) y sigue activa. | Rectángulo punteado de previsualización. | — |
| **Objeto** (`o`) | **2 clics** (igual que Zona) y sigue activa. | Rectángulo punteado. | — |
| **Medir** (`m`) | Cada clic fija un nuevo punto de la medición. | La línea y la distancia siguen al cursor. | — |

**Imán de coordenadas** (al dibujar/arrastrar, por este orden):
1. extremos de otras paredes (10 px), 2. ejes horizontal/vertical respecto al
punto de inicio, 3. rejilla si *Ajustar a rejilla* está activo.

**Escape** cancela cualquier trazo/arrastre, deselecciona y vuelve a la
herramienta *Seleccionar*.

---

# 8. Panel derecho — cada bloque y cada campo

Panel fijo de 280 px. Siempre visibles: **Selección** y **Simulación /
Heatmap**. El resto aparece según lo que hayas seleccionado.

## 8.1 Bloque **Selección**

Área de texto de 10 líneas. Según lo seleccionado:

**Sin selección** — instrucciones y la configuración RF global:
```
Ningún elemento seleccionado.

1. Elige una herramienta y dibuja en el plano.
2. Pasa a «Seleccionar» y haz clic en un AP para
   configurar su banda/canal en «Configuración RF
   del AP», o en una pared para su material.
3. Pulsa «Ejecutar simulación» para ver la cobertura.

Configuración RF (Config RF…):
  Piso de ruido: -95 dBm
  Objetivo RSSI: > -67 dBm
  Objetivo SNR: ≥ 25 dB
  Objetivo SINR: ≥ 25 dB
  Estándar: 802.11ax
  Ancho de canal: 20 MHz
```

**Pared**
```
Pared
ID: WALL-001
Material: Concreto
Espesor: 0.15 m
Longitud: 8.00 m
Inicio: (4.00, 0.00) m
Fin: (4.00, 8.00) m
```

**Punto de acceso**
```
Punto de acceso
ID: AP-001
X: 2.00 m
Y: 3.00 m
Banda: 2.4 GHz (configurada)        ← o «— (activa: 2.4 GHz)» si no la tiene
Canal: 6 (2437 MHz) · Ancho: 20 MHz ← o «Canal: — (sin configurar)»
Estándar: 802.11ax (Wi-Fi 6)
Interferencia: …                    ← solo con canal configurado
SINR (dB):  mínimo / máximo / promedio / % ≥ objetivo
```

**Cliente**
```
Cliente
ID: CLIENT-001
X: 4.00 m
Y: 5.00 m
AP asociado: AP-001      ← o «Ninguno»
Banda: 2.4 GHz
RSSI: -62.8 dBm
SNR: 32.2 dB
Estado: SEÑAL FUERTE
```

**Espacio** · **Apertura** · **Objeto** (idem, con sus campos: nombre,
función, rectángulo, tipo, material, *overrides*).

## 8.2 Bloque **Configuración RF del AP** (solo con un AP seleccionado)

| Campo | Control | Notas |
|---|---|---|
| `Banda:` | Combobox | `2.4 GHz` / `5 GHz` / `6 GHz`. Al cambiarla se recargan canales y anchos válidos. |
| `Canal:` | Combobox | Canales de esa banda (2.4: 1‑13 · 5: 36‑165 · 6: 1‑233). El canal **no** cambia el RSSI: es coherencia de configuración. |
| `Ancho (MHz):` | Combobox | `20/40` en 2.4 GHz · `20/40/80/160` en 5/6 GHz. |
| `Frecuencia:` | Etiqueta | Se deriva del canal. |
| `Estándar:` | Combobox | `802.11n` (Wi‑Fi 4), `802.11ac` (5), `802.11ax` (6), `802.11be` (7). |
| `Potencia TX (dBm):` | Campo numérico | Por defecto `20`. |
| *(aviso)* | Etiqueta | Mensajes como `Aplicado: 2.4 GHz · canal 6 · 20 MHz · 20 dBm · 802.11ax`, `Sin cambios: el AP ya tiene esta configuración.` o avisos de canal propuesto. |
| Botones | **`Aplicar`** / **`Restablecer`** | *Aplicar* valida todo el bloque de una vez (si algo falla, no cambia nada) y es **una sola** entrada de deshacer. |

Errores posibles: `Selecciona una banda.`, `Canal o ancho inválido.`,
`Potencia TX inválida: … (usa un número en dBm).`, `Estándar no soportado: …`.

## 8.3 Bloque **Pared** (con una pared seleccionada)

| Campo | Qué hace |
|---|---|
| `Material:` | Cambia el material **al instante**. Catálogo: *Muro de yeso, Madera, Vidrio, Ladrillo, Concreto, Concreto reforzado, Metal*. |
| `Espesor (m):` + botón **`Aplicar espesor`** | Espesor real de la pared. Acepta coma o punto. Se aplica también con `Enter` o al salir del campo. |
| `Aperturas:` (contador) | Nº de huecos de esa pared. |
| Botones **`+ Puerta`** / **`+ Ventana`** | Añade una apertura al final de la pared (0.90 m la puerta, 1.20 m la ventana). |

## 8.4 Bloque **Espacio**

`Nombre:` · `Función:` · botón **`Aplicar espacio`**.
Los espacios **no afectan a la RF** (son organizativos). Errores:
`El nombre del espacio no puede estar vacío.`, `Nombre o función demasiado largo (máx. 200).`

## 8.5 Bloque **Apertura**

`Tipo:` (`Puerta`, `Ventana`, `Paso`) · `Inicio (m):` · `Fin (m):` (distancias
desde el inicio de la pared) · botón **`Aplicar apertura`**.
Un rayo que cruza por un hueco **sustituye** la atenuación de la pared por la
del hueco (por defecto 0 dB: se «abre» el paso).

## 8.6 Bloque **Objeto** (obstáculo de mobiliario)

`Nombre:` · `Tipo:` (`Mobiliario`, `Equipo`, `Columna`, `Otro`) · `Material:`
· `Override (band=dB):` (formato `band_5=6, band_2_4=4`) · botón
**`Aplicar objeto`**. Mínimo 0.1 m por lado.

## 8.7 Bloque **Posición (m)**

`X:` · `Y:` · botón **`Aplicar posición`** — mueve el AP o el cliente a
coordenadas exactas (metros). Para otros tipos no hace nada.

## 8.8 Bloque **Simulación / Heatmap** (siempre visible)

- Botón **`Ejecutar simulación`**: corre la simulación puntual y escribe:
  ```
  AP: AP-001
  Banda: 2.4 GHz
  Paredes: 4   Objetos: 2
  Puntos simulados: …
  RSSI mínimo: … / máximo: …
  SNR mínimo: … / máximo: …
  ```
- Etiqueta **`Heatmap (grid):`** con el texto del heatmap:
  ```
  AP: Todos los AP (2)
  Banda: 2.4 GHz
  Resolución: 0.5 m
  Estándar: 802.11ax (Wi-Fi 6)
  Puntos del grid: 40401
  RSSI mínimo / máximo / promedio
  % del total de puntos: Excelente … Buena … Regular … Debil … Sin cobertura util
  AP dominante (mejor RSSI por punto): AP-001 63%
  Clientes:
    CLIENT-001: AP AP-001 | 2.00 m | RSSI -35.2 dBm | SOM … | SNR … | Buena | …
  ```
  Estados posibles: `Calculando cobertura...`, `Heatmap desactivado.`,
  mensajes de error (ver §15).

---

# 9. Diálogos

## 9.1 **Dimensiones del espacio**

`Ancho (m):` · `Alto (m):` · nota `El espacio se guarda en metros (no en píxeles).`
· botones `Cancelar` / `Aplicar`.
Validaciones: números obligatorios, `> 0`, `Máximo 10000 m por lado.`, y
compatibilidad con la resolución RF (`Dimensiones incompatibles con la
resolución 0.5 m: Grid demasiado grande…`). Se usa en *Nuevo* y en `Dimensiones…`.

## 9.2 **Configuración RF** (`Config RF…`)

| Campo | Por defecto | Rango |
|---|---|---|
| `Piso de ruido (dBm):` | −95 | −200 … 0 |
| `Objetivo SNR (dB):` | 25 | −20 … 60 |
| `Objetivo SINR (dB):` | 25 | −20 … 60 |
| `Objetivo RSSI (dBm):` | −67 | numérico |
| `Estándar Wi-Fi:` | 802.11ax | n/ac/ax/be |
| `Ancho de canal (MHz):` | 20 | 20/40/80/160 |

Texto de ayuda incluido: *«Piso de ruido entre -200 y 0 dBm. El SNR es
P_rx − piso de ruido; el SINR añade la interferencia al denominador y
complementa al RSSI. El ancho de canal no modifica FSPL; 2.4 GHz admite
20/40 MHz.»* Botones `Cancelar` / `Aplicar`. Aplicar es atómico y
sincroniza la radio de **todos** los APs.

## 9.3 **Optimización de canales** (`Opt. canal…`)

- Cabecera: `Búsqueda: Exhaustiva · N evaluaciones` o `Búsqueda: Descenso coordinado · N evaluaciones`.
- Resumen: `SINR promedio: 18.4 dB → 24.1 dB (+5.7 dB)` o `Sin cambios: la asignación actual ya es la mejor propuesta por el modelo (óptimo local).`
- Tabla con columnas **`AP`** · **`Actual`** · **`Propuesto`**.
- Botones `Cerrar` y **`Aplicar propuesta`** (deshabilitado si no hay cambios).

**No modifica nada hasta que apliques.** El coste que optimiza es el SINR
promedio del heatmap combinado; usa búsqueda exhaustiva si hay ≤ 64
combinaciones, si no descenso coordenado (óptimo local).

---

# 10. Atajos de teclado

| Tecla | Acción |
|---|---|
| `Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` | Nuevo / Abrir / Guardar / Guardar como |
| `Ctrl+Z` / `Ctrl+Y` / `Ctrl+Shift+Z` | Deshacer / Rehacer |
| `Ctrl++` (o `Ctrl+=`) / `Ctrl+-` / `Ctrl+0` | Acercar / Alejar / Vista normal |
| **Rueda del ratón** | Zoom al punto del cursor (×1.25 / ÷1.25) |
| **Botón central + arrastre** | Desplazar el plano |
| **Botón izquierdo sobre hueco + arrastre** | Desplazar el plano (cursor de flechas) |
| `Supr` / `Retroceso` | Eliminar la selección |
| `Escape` | Cancelar trazo/arrastre, deseleccionar, volver a *Seleccionar* |
| `s` `w` `a` `c` `e` `o` `m` | Herramientas: **S**eleccionar, **W**all(pared), **A**P, **C**liente, Espac**e**(zona), **O**bjeto, **M**edir |

Las teclas de herramienta no actúan mientras escribes en un campo de texto
ni con `Ctrl` pulsado (para no robar los atajos de archivo).

---

# 11. Barra de estado y leyenda

## 11.1 Barra de estado (inferior)

```
X: 3.20 m    Y: 5.10 m    |    Espacio: 12 × 8 m    |    Escala: 57.4 px/m | Zoom: 100% | Res. grid: 0.5 m | Heatmap: actualizado | Herramienta: select
```

| Campo | Significado |
|---|---|
| `X: … Y: …` | Coordenadas del cursor en metros (`—` si no hay cursor). |
| `Espacio:` | Tamaño del piso activo. |
| `Escala:` | Píxeles por metro reales. |
| `Zoom:` | Porcentaje (100% = ajuste al lienzo). |
| `Res. grid:` | Resolución de la malla de simulación. |
| `Heatmap:` | `no` (apagado) · `sí` (activado) · **`recalculando…`** (documento modificado, pendiente) · **`actualizado`** (resultado vigente). |
| `Herramienta:` | Herramienta activa (`select`, `wall`, `ap`, `client`, `space`, `obstacle`, `measure`). |

## 11.2 Leyenda (caja superior izquierda)

Título según la métrica: **`Cobertura Wi‑Fi`** (RSSI) · **`SNR (dB)`** ·
**`Interferencia (dBm)`** · **`SINR (dB)`**.

| Métrica | Filas |
|---|---|
| **RSSI** | `Excelente ≥ -50 dBm` (verde) · `Buena ≥ -67 dBm` (verde clarito) · `Regular ≥ -75 dBm` (amarillo) · `Debil ≥ -85 dBm` (rojo) · `Sin cobertura util < -85 dBm` (gris) |
| **SNR** | `SNR objetivo ≥ 25 dB` · `Por debajo < 25 dB` |
| **SINR** | `SINR objetivo ≥ 25 dB` · `Por debajo < 25 dB` |
| **Interferencia** | `Interferencia extrema ≥ -30 dBm` · `muy alta ≥ -40` · `alta ≥ -55` · `baja ≥ -70` · `Sin interferencia < -85 dBm` |

Los umbrales salen de la configuración del proyecto (`Config RF…`), no están
fijados en el código. Los colores de la leyenda de RSSI coinciden con los de
la **capa del AP seleccionado**.

---

# 12. El heatmap (cobertura general)

**Qué es**: una imagen con un color por punto de la malla de simulación
(`CoverageGrid`), calculada con el motor real.

**Cómo se calcula**: para cada AP se evalúa el mismo grid con
`simulate_coverage` y los resultados se combinan conservando, **por punto**,
el AP de mayor RSSI (empate → menor id).

**Disparador**: se recalcula automáticamente ~**150 ms** después de la última
edición que afecte a la RF (debounce). Mientras tanto la barra de estado
muestra `recalculando…`.

**Invalida el heatmap (recalcula):** mover/crear/borrar paredes, aperturas u
obstáculos · mover/crear/borrar APs · cambiar banda · `Config RF…` ·
configuración del AP (banda/canal/ancho/potencia) · `Dimensiones…` ·
cambiar `Res.:` · desactivar→activar `Heatmap` · cambiar de ámbito `AP:` ·
deshacer/rehacer.

**NO invalida (no recalcula):** seleccionar un elemento · mover un cliente ·
cambiar la `Métrica:` (solo repinta) · desactivar `Heatmap` (solo oculta) ·
zoom/desplazar · rejilla visual · editar espacios (zonas).

**Limitaciones del heatmap:**
- **Bandas mixtas**: si tienes APs en 2.4 y 5 GHz a la vez, *Todos los AP* no
  puede combinarse; verás el mensaje con opciones (unificar bandas o elegir un
  AP concreto en el selector `AP:`).
- **6 GHz**: el catálogo de materiales por defecto no incluye `band_6`, así
  que aparecerá `No hay datos de atenuación de materiales para la banda
  seleccionada (p. ej. 6 GHz).` (no se inventan valores).
- Los porcentajes de la leyenda usan como denominador **todos** los puntos del
  grid (incluidos los que no tienen cobertura).

---

# 13. Cobertura del AP seleccionado (capa de resaltado)

Al seleccionar un AP con *Seleccionar* se pinta, **encima del heatmap**, su
cobertura individual con la paleta de la leyenda: zona verde/verde
clarito/amarillo/rojo, gris donde no hay señal, **borde blanco** donde se pasa
de señal a no señal y **bordes oscuros** entre zonas de calidad distintas.

- Es una **capa aparte**: no sustituye ni modifica el heatmap de fondo.
- **Selección instantánea**: los resultados por AP se cachean; seleccionar un
  AP, volver a él o apagar el heatmap **no** ejecutan la simulación otra vez.
  La primera vez que ves un AP sí se calcula (su pase completo).
- Se recalcula automáticamente cuando cambia la RF real (geometría, banda,
  configuración, resolución).

---

# 14. Simulación puntual (botón `Simular`)

Calcula la cobertura del **AP seleccionado** (o del primero si no hay
selección) sobre puntos de muestreo y muestra el resumen en el panel
*Simulación / Heatmap*: banda, nº de paredes/objetos, puntos, RSSI
mín/máx, SNR mín/máx y SINR si procede.

Errores posibles: `Coloca al menos un Access Point para simular.` y el de
banda sin datos de atenuación.

---

# 15. Clientes y su estado de señal

Cada cliente dibujado muestra un **indicador** (halo coloreado + punto macizo)
y, al seleccionarlo, el panel detalla:

```
AP asociado: AP-001      Banda: 2.4 GHz      RSSI: -79.9 dBm
SNR: 15.1 dB             Estado: SEÑAL INESTABLE
```

| Estado | Umbral (RSSI en la posición exacta del cliente) | Color del indicador |
|---|---|---|
| `SEÑAL BUENA` | ≥ −55 dBm | verde claro |
| `SEÑAL FUERTE` | −56 … −67 dBm | verde |
| `SEÑAL DÉBIL` | −68 … −75 dBm | amarillo |
| `SEÑAL INESTABLE` | −76 … −85 dBm | rojo |
| `SIN SEÑAL` | < −85 dBm, sin evaluación o fuera de cobertura | gris |

- Los límites están centralizados en `ui/client_signal.py` (constantes
  `*_MIN_DBM`): es el único sitio a tocar para ajustarlos.
- El **AP asociado** es el de mejor RSSI en esa posición (no hay roaming
  guardado). Si no hay señal utilizable: `AP asociado: Ninguno`.
- El valor sale del **motor real** en la posición exacta del cliente (misma
  ruta que el heatmap), **nunca** de los píxeles del heatmap.
- Se actualiza al mover el cliente, mover un AP, cambiar la banda, añadir o
  mover paredes, cambiar materiales o recalcular la cobertura.

---

# 16. Qué afecta a la RF (y qué no)

**Afecta (cambia los resultados):**
- Paredes: material y espesor (`pérdida = atenuación de referencia × espesor/espesor de referencia`).
- Aperturas dentro de una pared: abren el paso (por defecto 0 dB).
- Obstáculos (muebles/columnas): pérdida propia por material (+ *override*).
- Posición de APs y clientes, potencia TX, banda/frecuencia, piso de ruido.
- Ancho de canal y canales → **solo** para interferencia/SINR (no cambian FSPL/RSSI).
- Resolución del grid (cambia la muestrea, no la fórmula).

**No afecta:**
- Espacios/zonas, nombres, colores, rejilla visual, zoom, métrica del heatmap,
  apagar el heatmap, selección.

**Materiales por defecto** (`config/default_config.yaml`):

| Material | Espesor ref. | 2.4 GHz | 5 GHz |
|---|---|---|---|
| Muro de yeso | 0.012 m | 3 dB | 4 dB |
| Madera | 0.04 m | 3 dB | 4 dB |
| Vidrio | 0.008 m | 3 dB | 4 dB |
| Ladrillo | 0.12 m | 6 dB | 8 dB |
| Concreto | 0.15 m | 12 dB | 15 dB |
| Concreto reforzado | 0.20 m | 15 dB | 20 dB |
| Metal | 0.005 m | 25 dB | 30 dB |

(No hay atenuación para 6 GHz → esa banda falla con mensaje visible.)

---

# 17. Recetas paso a paso

## A) Planear una oficina y ver la cobertura
1. `Archivo → Nuevo` → pon las dimensiones (p. ej. 30 × 15 m) → `Aplicar`.
2. Herramienta **Pared** (`w`): clic en el inicio y clic en el final. Repite.
   Selecciona cada pared y en *Pared* elige **Material** y **Espesor**.
3. Selecciona una pared → **`+ Puerta`** / **`+ Ventana`** donde quieras huecos.
4. Herramienta **AP** (`a`): clic donde vaya el punto de acceso.
5. Selecciona el AP → *Configuración RF del AP* → banda/canal/ancho/potencia → **`Aplicar`**.
6. Espera a que la barra de estado diga `Heatmap: actualizado` (o pulsa
   `Ejecutar simulación` para ver los números).
7. Cambia `Métrica:` a `SNR` / `Interferencia` / `SINR` para otras vistas (sin recalcular).

## B) Colocar clientes y comprobar su calidad
1. Herramienta **Cliente** (`c`): clic en cada posición.
2. Arrastra los clientes donde quieras: el indicador de color cambia en caliente.
3. Selecciona un cliente → verás `AP asociado`, `Banda`, `RSSI`, `SNR` y `Estado`.

## C) Comparar bandas
1. `Banda: 2.4 GHz` → anota los RSSI de los clientes.
2. `Banda: 5 GHz` → el heatmap se recalcula y los clientes bajan de nivel
   (5 GHz se atenúa más).
3. Cada AP puede tener **su propia banda** en *Configuración RF del AP*.

## D) Quitar puntos ciegos
1. Mira el gris `Sin cobertura util` del heatmap y la capa del AP.
2. Mueve/Añade un AP, o cambia un material (p. ej. `Concreto` → `Ladrillo`).
3. Observa: mover el AP recalcula; mover un cliente **no**.

## E) Optimizar canales
1. Configura **canal** a todos los APs (sin canal no hay interferencia modelada).
2. `Opt. canal…` → revisa la tabla `AP / Actual / Propuesto`.
3. `Aplicar propuesta` solo si te convence (o `Cerrar` para descartar).

## F) Guardar y reabrir
`Ctrl+S` (o *Guardar como…*) → archivo `.json` autocontenido. Al reabrir se
conservan geometría, materiales, bandas, umbrales, APs y clientes; **no** se
conservan heatmaps, simulaciones, selección ni deshacer.

---

# 18. Deshacer, gestos y guardado

- **25 operaciones** son desechables (crear/editar/borrar paredes, APs,
  clientes, zonas, objetos, aperturas, dimensiones, RF, canales…).
- **Un arrastre continuo = un solo paso**: al empezar a arrastrar se congela
  una foto y al soltar se apila una única entrada. Si no cambió nada, no se
  apila nada. `Escape` cancela el arrastre sin dejar rastro.
- Tope: **50 pasos** (los más antiguos se descartan).
- No desechables (aunque marquen el proyecto como modificado): cambiar
  resolución, banda activa, métrica, rejilla, snap, ámbito del heatmap.
- El botón de cerrar pide confirmación si `dirty` está activo.

---

# 19. Archivos y formato

- Extensión **`.json`** (si no la traes, se añade).
- Estructura: `{ "schema_version": 1, "project": {...}, "editor": {...} }`
  con `project` (nombre, unidades `m`, bandas, materiales, radio, umbrales,
  `floors[]` con paredes/espacios/aperturas/obstáculos, `access_points[]`,
  `clients[]`) y `editor` (`band_id`, `grid_resolution_m`).
- **No se guarda**: heatmaps, simulaciones, imágenes, selección, herramienta,
  métrica, rejilla/snap, deshacer, interferencia/SINR calculados, piso activo.
- Protecciones: archivo ≤ 20 MiB, JSON UTF‑8, escritura atómica, validación
  completa antes de escribir y al cargar (versión de esquema, ids únicos,
  materiales referenciados, límites de 10 000 m, etc.).

---

# 20. Límites, errores frecuentes y rendimiento

## 20.1 Límites duros

| Límite | Valor | Mensaje |
|---|---|---|
| Puntos del grid | **100 000** | `Grid demasiado grande: N puntos (máximo 100000). Aumenta la resolución.` |
| Resolución mínima | 0.05 m | `Resolución mínima 0.05 m` |
| Lado del piso | 10 000 m | `Máximo 10000 m por lado.` |
| Zoom | 0.1× – 20× | — |
| Deshacer | 50 pasos | — |
| Aperturas por pared | 32 | validación al cargar/guardar |
| Tamaño de archivo | 20 MiB | error al abrir |
| Zona/objeto mínimo | 0.1 m por lado | recorte/aviso |

> ⚠️ **Planos muy grandes**: con la resolución por defecto (0.50 m) un piso
> de **200 × 200 m** genera 160 801 puntos y **no se puede ni crear** (guard de
> 100 000). Sube la resolución a `1.00` (40 401 puntos) o agranda el piso por
> pasos. Como referencia de coste: 100 × 100 m @0.5 con 2 APs ≈ **9 s** de
> heatmap; 200 × 200 m @1.0 con 4 APs ≈ **30 s**.

## 20.2 Errores que puedes ver

| Mensaje | Causa / solución |
|---|---|
| `Coloca al menos un Access Point para el heatmap.` | No hay APs: dibuja uno con la herramienta `AP`. |
| `No hay datos de atenuación de materiales para la banda seleccionada (p. ej. 6 GHz).` | La banda activa no está en el catálogo de materiales. |
| `No se puede combinar el heatmap: hay APs configurados en bandas distintas…` | Unifica bandas o elige un AP en el selector `AP:`. |
| `Grid demasiado grande…` | Sube `Res.:` o reduce dimensiones. |
| `Dimensiones incompatibles con la resolución…` | Igual que arriba (pasa al redimensionar). |
| `Canal N no pertenece a la banda …` / `Ancho de canal X MHz no permitido…` | Combinación inválida en *Configuración RF del AP*. |
| `Potencia TX inválida…` | Escribe un número (acepta coma o punto). |
| `La pared necesita dos puntos distintos.` | Clics muy juntos o imán. |
| `Este archivo no es un proyecto Wi‑Fi Planner válido` | JSON dañado o de otra app. |
| `Versión de esquema incompatible: N` | Archivo de otra versión (solo se soporta `schema_version=1`). |

## 20.3 Rendimiento (medido)

- **Selección de AP, mover cliente, apagar heatmap, cambiar métrica**: son
  cambios de interfaz → **~0‑300 ms** (no ejecutan la simulación).
- **Mover AP / pared / banda / resolución**: son cambios reales → ejecutan el
  heatmap completo (según tamaño: 1,3 s en 50×50 @0.5; 13 s en 100×100 @0.5;
  30‑37 s en 200×200 @1.0 con 4 APs y 48 paredes).
- La **primera** selección de un AP aún calcula su capa una vez (≈4 s en
  100×100 @0.5); a partir de ahí es instantánea.
- **Activar** `Heatmap` vuelve a calcular el fondo (es deliberado).
- Durante un arrastre la interfaz responde a ~30‑50 fps; el cálculo pesado
  sale después del retardo de 150 ms, en el hilo principal (verás un bloqueo
  corto en planos grandes).

---

# 21. Estructura del proyecto y mapa de archivos

```
WifiPlaner/
├── .gitignore               reglas de exclusión e higiene
├── requirements.txt         pytest, PyYAML, Pillow
├── assets/
│   ├── Diagrama_Estructura_WiFi_Planner.png  diagrama arquitectónico
│   ├── PlanoRedes.png                        plano base de la biblioteca
│   └── reference/
│       └── Figura3_Arquitectura_AAA.png      arquitectura de seguridad RADIUS/AAA
├── docs/
│   ├── user_manual.md       ← ESTE DOCUMENTO (manual de uso y referencia)
│   ├── architecture.md      capas, flujo de datos, contratos
│   ├── decisions.md         99 decisiones de diseño (A…CU)
│   ├── formulas.md          15 bloques de fórmulas RF
│   ├── technical_context.md contexto técnico completo y trazabilidad
│   └── reference/
│       └── Proyecto_WiFi_Biblioteca.xlsx     tablas de validación teórica
├── legacy/                  prototipos históricos v1–v4 desacoplados
│   ├── README.md            guía y trazabilidad histórica
│   ├── CalculadoraWLAN_Visual.py  (v4)
│   ├── CalculoWifi2.py            (v2)
│   ├── calculo_wifi_biblioteca.py (v1)
│   └── CODIGO(Interactivo).py     (v3)
└── wifi_planner/            código fuente modular del simulador
    ├── main.py              punto de entrada (python main.py)
    ├── pytest.ini           configuración de pruebas
    ├── config/
    │   ├── __init__.py      load_config() → defaults del YAML
    │   └── default_config.yaml  TODOS los valores mágicos (radio, umbrales, bandas, materiales)
    ├── core/                modelo puro (sin Tk, sin fórmulas RF)
    │   ├── project.py       Project, CoverageThresholds
    │   ├── space.py         Floor, Space
    │   ├── wall.py          Wall, Opening
    │   ├── obstacle.py      Obstacle (mobiliario)
    │   ├── access_point.py  AccessPoint
    │   ├── client.py        ClientDevice
    │   ├── material.py      Material + MaterialAttenuationError
    │   ├── band.py, channel.py  FrequencyBand, catálogo de canales
    │   ├── radio.py         RadioConfiguration
    │   ├── result.py        LinkEvaluation, SimulationResult, QualityClass
    │   └── geometry.py      Point2D, Segment2D, Rect
    ├── engine/              simulación (sin Tk, funciones puras)
    │   ├── propagation.py   FSPL
    │   ├── link_budget.py   P_rx, SOM, SNR, evaluate_link
    │   ├── obstacles.py     trace_walls, atenuaciones
    │   ├── intersection.py  cruces de segmentos
    │   ├── classifier.py    calidad, SOM, diagnósticos
    │   ├── simulator.py     simulate_coverage (el pipeline)
    │   ├── combine.py       combinación multi‑AP
    │   ├── interference.py  modelo espectral (F11)
    │   ├── sinr.py          SINR (F12)
    │   ├── channel_optimization.py  propuesta de canales (F13)
    │   └── coverage_grid.py CoverageGrid (malla)
    ├── persistence/
    │   └── json_project_repository.py  guardar/cargar JSON (schema v1)
    ├── ui/
    │   ├── app.py           ventana, menús, callbacks, heatmap, overlays
    │   ├── session.py       EditorSession: CRUD, undo, heatmap, simulaciones
    │   ├── editor_canvas.py lienzo, herramientas, capas, hit-testing
    │   ├── viewport.py      metros ⇄ píxeles, zoom, pan
    │   ├── coverage_renderer.py imágenes del heatmap + leyenda
    │   ├── client_signal.py estados de señal de los clientes
    │   ├── geometry_view.py vista congelada del piso activo
    │   ├── theme.py         paleta de colores
    │   ├── dialogs/
    │   │   ├── rf_dialog.py                  Configuración RF
    │   │   ├── project_dialog.py             Dimensiones del espacio
    │   │   ├── channel_optimization_dialog.py Optimización de canales
    │   │   └── material_dialog.py, wall_dialog.py   (reservados, vacíos)
    │   └── panels/
    │       ├── toolbar.py   barra de herramientas
    │       └── properties.py panel derecho
    └── tests/               955 pruebas (37 archivos)
        ├── factories.py     make_session() y demás fábricas
        └── fixtures/        golden_data.py (datos de referencia)
```

**Reglas de arquitectura** (no se rompen):

1. `core/` y `engine/` **nunca** importan `ui/`, `persistence/` ni Tkinter/PIL.
2. `ui/` puede importar `core/`, `engine/`, `persistence/` y `config/`.
3. **La UI no contiene fórmulas RF**: solo invoca al motor y pinta.
4. Sin valores mágicos: umbrales, potencias y atenuaciones salen de
   `config/default_config.yaml` o de parámetros.

---

# 22. Glosario

| Término | Significado |
|---|---|
| **RSSI / P_rx** | Potencia recibida en dBm (lo que mide el heatmap). |
| **FSPL** | Pérdida en espacio libre: `20·log10(d[m]) + 20·log10(f[MHz]) − 27.55`. |
| **SOM** | `P_rx − sensibilidad`; ≥20 APROBADO, ≥10 RIESGO, si no FALLIDO. |
| **SNR** | `P_rx − piso de ruido`; objetivo ≥ 25 dB por defecto. |
| **SINR** | `P_rx − 10·log10(10^(N/10) + 10^(I/10))`; sin interferencia es igual al SNR. |
| **Interferencia** | Potencia agregada de APs cuyos canales se solapan (solo con canal configurado). |
| **Calidad** | Excelente ≥ −50 · Buena ≥ −67 · Regular ≥ −75 · Débil ≥ −85 · Sin cobertura util. |
| **RSSI objetivo** | Umbral de cobertura útil (comparación **estricta** `>`), −67 dBm por defecto. |
| **Heatmap** | Imagen con un color por punto del grid. |
| **CoverageGrid** | Malla regular de puntos de simulación (resolución `Res.:`). |
| **Capa del AP** | Resaltado de la cobertura del AP seleccionado. |
| **Debounce** | Retardo de 150 ms antes de recalcular, para no recalcular en cada píxel de un arrastre. |
| **Gesto** | Un arrastre continuo = una entrada de deshacer. |
| **dirty** | Proyecto modificado desde la última guardada (asterisco en el título). |

---

*Documento generado el 26/09/2026 a partir del estado actual del código.
Si el programa cambia, vuelve a generarlo: las etiquetas citadas salen
literalmente de `ui/app.py`, `ui/panels/toolbar.py`,
`ui/panels/properties.py` y `ui/dialogs/`.*
