"""
=============================================================================
CALCULADORA WLAN VISUAL - BIBLIOTECA UNIVERSITARIA
Interfaz Grafica para Auditoria y Rediseno de Red Wi-Fi
Corporacion Unificada Nacional de Educacion Superior (CUN)
Asignatura: Redes Inalambricas

 VERSION 4 - INTERFAZ GRAFICA

Basada en CODIGO(Interactivo).py - VERSION 3

La finalidad de esta version es presentar la calculadora WLAN
con una interfaz visual profesional para la presentacion academica.
=============================================================================
"""

import math
import tkinter as tk
from tkinter import ttk, messagebox
import os


# ============================================================================
# 1. FUNCIONES DE FISICA DE RF - G1
# ============================================================================

def calcular_longitud_onda(frecuencia_hz):
    c = 300_000_000
    return c / frecuencia_hz


def calcular_fspl(distancia_m, frecuencia_mhz):
    if distancia_m <= 0:
        raise ValueError("La distancia debe ser mayor que 0.")
    if frecuencia_mhz <= 0:
        raise ValueError("La frecuencia debe ser mayor que 0.")
    return round(
        (20 * math.log10(distancia_m))
        + (20 * math.log10(frecuencia_mhz))
        - 27.55,
        2
    )


def calcular_prx(p_tx, g_tx, l_tx, fspl, g_rx, l_rx):
    p_rx = p_tx + g_tx - l_tx - fspl + g_rx - l_rx
    return round(p_rx, 2)


def calcular_som(p_rx, sensibilidad_rx):
    return round(p_rx - sensibilidad_rx, 2)


def evaluar_veredicto(som):
    if som < 10:
        return "FALLIDO"
    elif som < 20:
        return "RIESGO"
    else:
        return "APROBADO"


def cumple_rssi_objetivo(p_rx, umbral=-67.0):
    return p_rx > umbral


# ============================================================================
# 2. PARAMETROS DEL PROYECTO
# ============================================================================

P_TX = 20.0
G_TX = 3.0
G_RX = 0.0
L_TX = 1.0
L_RX = 1.0
SENSIBILIDAD_RX = -75.0
RSSI_OBJETIVO_MIN = -67.0

FRECUENCIAS = {
    "2.4 GHz": 2437,
    "5 GHz": 5180
}

ZONAS = [
    {
        "ap": "AP1",
        "zona": "Entrada Principal + Sala Audiovisual",
        "sala_critica": "Entrada Principal (15,48 m2)",
        "distancia_max_m": 5.72,
        "color": "#2196F3"
    },
    {
        "ap": "AP2",
        "zona": "Sala de Estudio Colaborativo + Zaguan",
        "sala_critica": "Sala de Estudio Colaborativo (37,62 m2)",
        "distancia_max_m": 8.92,
        "color": "#F44336"
    },
    {
        "ap": "AP3",
        "zona": "Atencion/Circulacion + Deposito + Informatica + Sanitarios",
        "sala_critica": "Atencion y Circulacion Bibliotecaria (22,33 m2)",
        "distancia_max_m": 6.87,
        "color": "#4CAF50"
    },
    {
        "ap": "AP4",
        "zona": "Hemeroteca + Sala de Lectura",
        "sala_critica": "Sala de Lectura (44,02 m2)",
        "distancia_max_m": 9.65,
        "color": "#9C27B0"
    }
]

# Posiciones de los APs en el canvas (ajustadas al plano)
AP_POSITIONS = {
    "AP1": (685, 195),
    "AP2": (1050, 175),
    "AP3": (200, 510),
    "AP4": (730, 475)
}

COLOR_VERDE = "#4CAF50"
COLOR_AMARILLO = "#FF9800"
COLOR_ROJO = "#F44336"
COLOR_FONDO = "#1a1a2e"
COLOR_PANEL = "#16213e"
COLOR_TEXTO = "#e0e0e0"
COLOR_TITULO = "#00d4ff"
COLOR_BOTON = "#0f3460"
COLOR_BOTON_HOVER = "#1a508b"


# ============================================================================
# 3. CLASE PRINCIPAL DE LA APLICACION
# ============================================================================

class CalculadoraWLAN:
    def __init__(self, root):
        self.root = root
        self.root.title("Calculadora WLAN - Biblioteca Universitaria - CUN")
        self.root.geometry("1280x800")
        self.root.minsize(1100, 700)
        self.root.configure(bg=COLOR_FONDO)

        self.ap_seleccionado = tk.StringVar(value="")

        self._configurar_estilos()
        self._construir_layout()
        self._cargar_plano()
        self._mostrar_bienvenida()

    def _configurar_estilos(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure("TFrame", background=COLOR_FONDO)
        self.style.configure("Panel.TFrame", background=COLOR_PANEL)
        self.style.configure("TLabel",
                             background=COLOR_PANEL,
                             foreground=COLOR_TEXTO,
                             font=("Segoe UI", 10))
        self.style.configure("Titulo.TLabel",
                             background=COLOR_FONDO,
                             foreground=COLOR_TITULO,
                             font=("Segoe UI", 16, "bold"))
        self.style.configure("Sub.TLabel",
                             background=COLOR_PANEL,
                             foreground=COLOR_TITULO,
                             font=("Segoe UI", 12, "bold"))
        self.style.configure("Resultado.TLabel",
                             background=COLOR_PANEL,
                             foreground="#ffffff",
                             font=("Consolas", 11))
        self.style.configure("Verde.TLabel",
                             background=COLOR_PANEL,
                             foreground=COLOR_VERDE,
                             font=("Segoe UI", 11, "bold"))
        self.style.configure("Amarillo.TLabel",
                             background=COLOR_PANEL,
                             foreground=COLOR_AMARILLO,
                             font=("Segoe UI", 11, "bold"))
        self.style.configure("Rojo.TLabel",
                             background=COLOR_PANEL,
                             foreground=COLOR_ROJO,
                             font=("Segoe UI", 11, "bold"))
        self.style.configure("Accion.TButton",
                             background=COLOR_BOTON,
                             foreground="#ffffff",
                             font=("Segoe UI", 10, "bold"),
                             padding=(12, 8))
        self.style.map("Accion.TButton",
                       background=[("active", COLOR_BOTON_HOVER)])

        self.style.configure("AP.TButton",
                             background=COLOR_BOTON,
                             foreground="#ffffff",
                             font=("Segoe UI", 10, "bold"),
                             padding=(15, 10))
        self.style.map("AP.TButton",
                       background=[("active", COLOR_BOTON_HOVER)])

    def _construir_layout(self):
        barra_superior = tk.Frame(self.root, bg=COLOR_FONDO, height=50)
        barra_superior.pack(fill=tk.X, padx=10, pady=(10, 5))

        ttk.Label(barra_superior,
                  text="CALCULADORA WLAN - BIBLIOTECA UNIVERSITARIA",
                  style="Titulo.TLabel").pack(side=tk.LEFT, padx=10)

        ttk.Label(barra_superior,
                  text="CUN | Redes Inalambricas",
                  style="TLabel").pack(side=tk.RIGHT, padx=10)

        contenido = tk.Frame(self.root, bg=COLOR_FONDO)
        contenido.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.panel_izquierdo = tk.Frame(contenido, bg=COLOR_FONDO, width=750)
        self.panel_izquierdo.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.panel_izquierdo.pack_propagate(False)

        self.panel_derecho = tk.Frame(contenido, bg=COLOR_PANEL,
                                       width=480, bd=1, relief=tk.RIDGE)
        self.panel_derecho.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.panel_derecho.pack_propagate(False)

        barra_inferior = tk.Frame(self.root, bg=COLOR_PANEL, height=70, bd=1,
                                   relief=tk.RIDGE)
        barra_inferior.pack(fill=tk.X, padx=10, pady=(5, 10))

        self._construir_panel_derecho()
        self._construir_barra_inferior(barra_inferior)

    def _construir_panel_derecho(self):
        ttk.Label(self.panel_derecho, text="PARAMETROS DEL PROYECTO",
                  style="Sub.TLabel").pack(pady=(15, 10), padx=15, anchor="w")

        params_frame = tk.Frame(self.panel_derecho, bg="#0d1b2a",
                                 bd=1, relief=tk.GROOVE)
        params_frame.pack(fill=tk.X, padx=15, pady=(0, 10))

        parametros = [
            ("Potencia TX:", f"{P_TX} dBm"),
            ("Ganancia antena TX:", f"{G_TX} dBi"),
            ("Ganancia antena RX:", f"{G_RX} dBi"),
            ("Perdidas TX:", f"{L_TX} dB"),
            ("Perdidas RX:", f"{L_RX} dB"),
            ("Sensibilidad receptor:", f"{SENSIBILIDAD_RX} dBm"),
            ("Umbral RSSI objetivo:", f"{RSSI_OBJETIVO_MIN} dBm"),
        ]

        for i, (etiqueta, valor) in enumerate(parametros):
            row_bg = "#0d1b2a" if i % 2 == 0 else "#112240"
            row = tk.Frame(params_frame, bg=row_bg)
            row.pack(fill=tk.X, padx=5, pady=1)
            ttk.Label(row, text=etiqueta, style="TLabel",
                      font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=8, pady=3)
            ttk.Label(row, text=valor, style="Resultado.TLabel",
                      font=("Consolas", 9)).pack(side=tk.RIGHT, padx=8, pady=3)

        ttk.Label(self.panel_derecho, text="RESULTADOS",
                  style="Sub.TLabel").pack(pady=(15, 10), padx=15, anchor="w")

        self.frame_resultados = tk.Frame(self.panel_derecho, bg="#0d1b2a",
                                          bd=1, relief=tk.GROOVE)
        self.frame_resultados.pack(fill=tk.BOTH, expand=True, padx=15,
                                    pady=(0, 15))

    def _construir_barra_inferior(self, barra):
        frame_botones = tk.Frame(barra, bg=COLOR_PANEL)
        frame_botones.pack(expand=True)

        ttk.Label(frame_botones, text="Seleccionar AP:",
                  style="TLabel",
                  font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 10))

        for zona in ZONAS:
            btn = tk.Button(
                frame_botones,
                text=zona["ap"],
                bg=zona["color"],
                fg="#ffffff",
                font=("Segoe UI", 10, "bold"),
                width=6,
                relief=tk.RAISED,
                bd=2,
                activebackground=zona["color"],
                activeforeground="#ffffff",
                cursor="hand2",
                command=lambda ap=zona["ap"]: self._evaluar_ap(ap)
            )
            btn.pack(side=tk.LEFT, padx=5, pady=8)

        separador = ttk.Separator(frame_botones, orient=tk.VERTICAL)
        separador.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=8)

        ttk.Button(frame_botones, text="Enlace Personalizado",
                   style="Accion.TButton",
                   command=self._dialogo_enlace_personalizado).pack(
            side=tk.LEFT, padx=5, pady=8)

        ttk.Button(frame_botones, text="Tabla Referencia",
                   style="Accion.TButton",
                   command=self._ventana_tabla_referencia).pack(
            side=tk.LEFT, padx=5, pady=8)

        ttk.Button(frame_botones, text="Resumen",
                   style="Accion.TButton",
                   command=self._ventana_resumen).pack(
            side=tk.LEFT, padx=5, pady=8)

        ttk.Button(frame_botones, text="Parametros",
                   style="Accion.TButton",
                   command=self._ventana_parametros).pack(
            side=tk.LEFT, padx=5, pady=8)

    def _cargar_plano(self):
        self.canvas_frame = tk.Frame(self.panel_izquierdo, bg="#000000",
                                      bd=1, relief=tk.SUNKEN)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#1a1a2e",
                                 highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        ruta_plano = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "PlanoRedes.png")

        self.plano_img = None
        if os.path.exists(ruta_plano):
            try:
                from PIL import Image, ImageTk
                img = Image.open(ruta_plano)
                self._pil_img = img.copy()
                self.plano_img = ImageTk.PhotoImage(img)
                self.canvas.bind("<Configure>", self._redimensionar_plano)
            except ImportError:
                try:
                    self.plano_img = tk.PhotoImage(file=ruta_plano)
                    self.canvas.bind("<Configure>", self._redimensionar_plano)
                except tk.TclError:
                    self._dibujar_plano_sintetico()
        else:
            self._dibujar_plano_sintetico()

    def _redimensionar_plano(self, event=None):
        self.canvas.delete("plano")
        if self.plano_img is None:
            return

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        try:
            from PIL import Image, ImageTk
            img = self._pil_img
            ratio = min(canvas_w / img.width, canvas_h / img.height)
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            self._plano_tk = ImageTk.PhotoImage(resized)
            self.canvas.create_image(
                canvas_w // 2, canvas_h // 2,
                image=self._plano_tk, anchor="center", tags="plano"
            )
        except (ImportError, AttributeError):
            pass

        self.canvas.tag_lower("plano")

    def _dibujar_plano_sintetico(self):
        self.canvas.delete("plano")
        canvas_w = self.canvas.winfo_width() or 700
        canvas_h = self.canvas.winfo_height() or 500

        self.canvas.create_rectangle(
            20, 20, canvas_w - 20, canvas_h - 20,
            outline="#334155", width=2, fill="#0f172a", tags="plano"
        )

        habitaciones = [
            (40, 40, 180, 160, "Deposito\nBibliografico\n9,93 m2", "#1e3a5f"),
            (200, 40, 380, 160, "Atencion y\nCirculacion\n22,33 m2", "#1e3a5f"),
            (40, 180, 180, 300, "Servicios\nSanitarios\n14,07 m2", "#1e3a5f"),
            (200, 180, 380, 300, "Sala de\nInformatica\n9,32 m2", "#1e3a5f"),
            (400, 40, 560, 160, "Sala\nAudiovisual\n11,80 m2", "#2d1b69"),
            (580, 40, 700, 160, "Entrada\nPrincipal\n15,48 m2", "#1b4332"),
            (400, 180, 560, 300, "Hemeroteca\n14,83 m2", "#5c4033"),
            (580, 180, 700, 300, "Zaguan\n7,47 m2", "#5c4033"),
            (40, 320, 380, 480, "Sala Estudio\nColaborativo\n37,62 m2", "#4a1942"),
            (400, 320, 700, 480, "Sala de\nLectura\n44,02 m2", "#4a1942"),
        ]

        for x1, y1, x2, y2, texto, color in habitaciones:
            self.canvas.create_rectangle(x1, y1, x2, y2,
                                          outline="#475569", fill=color,
                                          width=1, tags="plano")
            self.canvas.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=texto, fill="#94a3b8",
                font=("Segoe UI", 8), justify="center", tags="plano"
            )

        self.canvas.create_text(
            canvas_w / 2, canvas_h - 15,
            text="AREA TOTAL DE REFERENCIA: 186,87 m2",
            fill="#64748b", font=("Segoe UI", 9, "bold"), tags="plano"
        )

    def _dibujar_aps(self):
        self.canvas.delete("ap_selection")

        ap_id = self.ap_seleccionado.get()
        if not ap_id:
            return

        x, y = AP_POSITIONS[ap_id]
        color = "#ffffff"

        canvas_w = self.canvas.winfo_width() or 700
        canvas_h = self.canvas.winfo_height() or 500

        scale_x = canvas_w / 1200
        scale_y = canvas_h / 600
        sx = int(x * scale_x)
        sy = int(y * scale_y)

        glow_size = int(22 * min(scale_x, scale_y))

        self.canvas.create_oval(
            sx - glow_size - 4, sy - glow_size - 4,
            sx + glow_size + 4, sy + glow_size + 4,
            outline="#ffffff", width=3,
            fill="", tags="ap_selection"
        )

        self.canvas.create_oval(
            sx - glow_size, sy - glow_size,
            sx + glow_size, sy + glow_size,
            outline="#00d4ff", width=2,
            fill="", tags="ap_selection"
        )

        self.canvas.create_text(
            sx, sy - glow_size - 15,
            text=ap_id, fill="#00d4ff",
            font=("Segoe UI", 12, "bold"),
            tags="ap_selection"
        )

    def _mostrar_bienvenida(self):
        for widget in self.frame_resultados.winfo_children():
            widget.destroy()

        ttk.Label(self.frame_resultados,
                  text="Calculadora WLAN Interactiva",
                  style="Sub.TLabel",
                  font=("Segoe UI", 13, "bold")).pack(
            pady=(25, 15), padx=15, anchor="center")

        ttk.Label(self.frame_resultados,
                  text="Seleccione un AP en el mapa o use\nlos botones de abajo para evaluar.",
                  style="TLabel",
                  font=("Segoe UI", 10),
                  justify="center").pack(pady=5, padx=15)

        info_frame = tk.Frame(self.frame_resultados, bg="#0d1b2a",
                               bd=1, relief=tk.GROOVE)
        info_frame.pack(fill=tk.X, padx=15, pady=20)

        ttk.Label(info_frame, text="Zonas del Rediseno:",
                  style="Sub.TLabel",
                  font=("Segoe UI", 10, "bold")).pack(
            pady=(10, 5), padx=10, anchor="w")

        for zona in ZONAS:
            row = tk.Frame(info_frame, bg="#0d1b2a")
            row.pack(fill=tk.X, padx=10, pady=2)

            tk.Label(row, text="  ", bg=zona["color"],
                     width=3).pack(side=tk.LEFT, padx=(0, 8))

            ttk.Label(row,
                      text=f"{zona['ap']}: {zona['zona']}",
                      style="TLabel",
                      font=("Segoe UI", 9)).pack(side=tk.LEFT)

            ttk.Label(row,
                      text=f"{zona['distancia_max_m']} m",
                      style="Resultado.TLabel",
                      font=("Consolas", 9)).pack(side=tk.RIGHT)

        tk.Frame(info_frame, bg="#0d1b2a", height=10).pack()

        ttk.Label(self.frame_resultados,
                  text="Formula: P_rx = P_tx + G_tx - L_tx - FSPL + G_rx - L_rx",
                  style="TLabel",
                  font=("Consolas", 9)).pack(pady=(15, 5), padx=15)

        ttk.Label(self.frame_resultados,
                  text="FSPL = 20*log10(d) + 20*log10(f) - 27.55",
                  style="TLabel",
                  font=("Consolas", 9)).pack(pady=2, padx=15)

    def _evaluar_ap(self, ap_id):
        self.ap_seleccionado.set(ap_id)
        self._dibujar_aps()

        zona = None
        for z in ZONAS:
            if z["ap"] == ap_id:
                zona = z
                break

        if zona is None:
            return

        for widget in self.frame_resultados.winfo_children():
            widget.destroy()

        header = tk.Frame(self.frame_resultados, bg=zona["color"], height=45)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(header, text=f"  EVALUACION {zona['ap']}",
                 bg=zona["color"], fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT, padx=10)

        info_frame = tk.Frame(self.frame_resultados, bg="#0d1b2a")
        info_frame.pack(fill=tk.X, padx=15, pady=(15, 10))

        datos = [
            ("Zona:", zona["zona"]),
            ("Sala critica:", zona["sala_critica"]),
            ("Distancia max:", f"{zona['distancia_max_m']} m"),
        ]

        for etiqueta, valor in datos:
            row = tk.Frame(info_frame, bg="#0d1b2a")
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=etiqueta, style="TLabel",
                      font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=8)
            ttk.Label(row, text=valor, style="Resultado.TLabel",
                      font=("Consolas", 9)).pack(side=tk.RIGHT, padx=8)

        ttk.Separator(self.frame_resultados,
                      orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15, pady=5)

        for banda, frecuencia in FRECUENCIAS.items():
            self._evaluar_banda(zona, banda, frecuencia)

    def _evaluar_banda(self, zona, banda, frecuencia):
        fspl = calcular_fspl(zona["distancia_max_m"], frecuencia)
        p_rx = calcular_prx(P_TX, G_TX, L_TX, fspl, G_RX, L_RX)
        som = calcular_som(p_rx, SENSIBILIDAD_RX)
        veredicto = evaluar_veredicto(som)
        cumple = cumple_rssi_objetivo(p_rx, RSSI_OBJETIVO_MIN)

        banda_frame = tk.Frame(self.frame_resultados, bg="#0d1b2a",
                                bd=1, relief=tk.GROOVE)
        banda_frame.pack(fill=tk.X, padx=15, pady=5)

        titulo_banda = tk.Frame(banda_frame, bg="#112240")
        titulo_banda.pack(fill=tk.X)
        tk.Label(titulo_banda, text=f"  BANDA: {banda}",
                 bg="#112240", fg=COLOR_TITULO,
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=5, pady=5)

        resultados_data = [
            ("FSPL:", f"{fspl:.2f} dB"),
            ("P_rx:", f"{p_rx:.2f} dBm"),
            ("SOM:", f"{som:.2f} dB"),
            ("RSSI > -67 dBm:", "SI" if cumple else "NO"),
        ]

        for etiqueta, valor in resultados_data:
            row = tk.Frame(banda_frame, bg="#0d1b2a")
            row.pack(fill=tk.X, padx=10, pady=1)
            ttk.Label(row, text=etiqueta, style="TLabel",
                      font=("Segoe UI", 9)).pack(side=tk.LEFT)
            ttk.Label(row, text=valor, style="Resultado.TLabel",
                      font=("Consolas", 9)).pack(side=tk.RIGHT)

        veredicto_frame = tk.Frame(banda_frame, bg="#0d1b2a")
        veredicto_frame.pack(fill=tk.X, padx=10, pady=(5, 10))

        if veredicto == "APROBADO":
            bg_color = COLOR_VERDE
            estilo = "Verde.TLabel"
        elif veredicto == "RIESGO":
            bg_color = COLOR_AMARILLO
            estilo = "Amarillo.TLabel"
        else:
            bg_color = COLOR_ROJO
            estilo = "Rojo.TLabel"

        tk.Label(veredicto_frame, text="RESULTADO:", bg="#0d1b2a",
                 fg="#94a3b8",
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=8)

        tk.Label(veredicto_frame, text=f"  {veredicto}  ",
                 bg=bg_color, fg="#ffffff",
                 font=("Segoe UI", 11, "bold"),
                 padx=15, pady=3).pack(side=tk.RIGHT, padx=8)

    def _dialogo_enlace_personalizado(self):
        dialogo = tk.Toplevel(self.root)
        dialogo.title("Enlace Personalizado")
        dialogo.geometry("480x550")
        dialogo.configure(bg=COLOR_PANEL)
        dialogo.resizable(False, False)
        dialogo.transient(self.root)
        dialogo.grab_set()

        tk.Label(dialogo, text="EVALUACION DE ENLACE PERSONALIZADO",
                 bg=COLOR_PANEL, fg=COLOR_TITULO,
                 font=("Segoe UI", 14, "bold")).pack(pady=(15, 10))

        tk.Label(dialogo, text="Ingrese la distancia y seleccione la banda",
                 bg=COLOR_PANEL, fg="#94a3b8",
                 font=("Segoe UI", 9)).pack(pady=(0, 10))

        form_frame = tk.Frame(dialogo, bg=COLOR_PANEL)
        form_frame.pack(fill=tk.X, padx=30)

        tk.Label(form_frame, text="Distancia (metros):",
                 bg=COLOR_PANEL, fg=COLOR_TEXTO,
                 font=("Segoe UI", 10)).pack(anchor="w")

        entry_distancia = tk.Entry(form_frame, font=("Consolas", 12),
                                    bg="#0d1b2a", fg="#ffffff",
                                    insertbackground="#ffffff",
                                    relief=tk.SUNKEN, bd=2)
        entry_distancia.pack(fill=tk.X, pady=(2, 12), ipady=5)

        tk.Label(form_frame, text="Banda de frecuencia:",
                 bg=COLOR_PANEL, fg=COLOR_TEXTO,
                 font=("Segoe UI", 10)).pack(anchor="w")

        banda_var = tk.StringVar(value="5 GHz")
        banda_frame = tk.Frame(form_frame, bg=COLOR_PANEL)
        banda_frame.pack(fill=tk.X, pady=(2, 12))

        tk.Radiobutton(banda_frame, text="2.4 GHz (2437 MHz)",
                       variable=banda_var, value="2.4 GHz",
                       bg=COLOR_PANEL, fg=COLOR_TEXTO,
                       selectcolor="#0d1b2a",
                       font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(banda_frame, text="5 GHz (5180 MHz)",
                       variable=banda_var, value="5 GHz",
                       bg=COLOR_PANEL, fg=COLOR_TEXTO,
                       selectcolor="#0d1b2a",
                       font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=5)

        separador = tk.Frame(dialogo, bg="#334155", height=1)
        separador.pack(fill=tk.X, padx=30, pady=(5, 5))

        resultado_frame = tk.Frame(dialogo, bg="#0d1b2a", bd=1,
                                    relief=tk.GROOVE)
        resultado_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=(5, 15))

        def calcular():
            try:
                distancia = float(entry_distancia.get())
                if distancia <= 0:
                    messagebox.showerror("Error",
                                         "La distancia debe ser mayor que 0.",
                                         parent=dialogo)
                    return
            except ValueError:
                messagebox.showerror("Error",
                                     "Ingrese un numero valido.",
                                     parent=dialogo)
                return

            banda = banda_var.get()
            frecuencia = FRECUENCIAS[banda]

            fspl = calcular_fspl(distancia, frecuencia)
            p_rx = calcular_prx(P_TX, G_TX, L_TX, fspl, G_RX, L_RX)
            som = calcular_som(p_rx, SENSIBILIDAD_RX)
            veredicto = evaluar_veredicto(som)
            cumple = cumple_rssi_objetivo(p_rx, RSSI_OBJETIVO_MIN)

            for widget in resultado_frame.winfo_children():
                widget.destroy()

            color_veredicto = {
                "APROBADO": COLOR_VERDE,
                "RIESGO": COLOR_AMARILLO,
                "FALLIDO": COLOR_ROJO
            }

            bg_veredicto = color_veredicto.get(veredicto, COLOR_ROJO)

            header_resultado = tk.Frame(resultado_frame, bg=bg_veredicto,
                                         height=45)
            header_resultado.pack(fill=tk.X)
            header_resultado.pack_propagate(False)
            tk.Label(header_resultado,
                     text=f"  RESULTADO: {veredicto}",
                     bg=bg_veredicto, fg="#ffffff",
                     font=("Segoe UI", 14, "bold")).pack(
                side=tk.LEFT, padx=10, pady=5)

            datos_frame = tk.Frame(resultado_frame, bg="#0d1b2a")
            datos_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

            datos = [
                ("Distancia:", f"{distancia:.2f} m"),
                ("Banda:", f"{banda} ({frecuencia} MHz)"),
                ("FSPL:", f"{fspl:.2f} dB"),
                ("P_rx:", f"{p_rx:.2f} dBm"),
                ("SOM:", f"{som:.2f} dB"),
                ("RSSI > -67 dBm:", "SI" if cumple else "NO"),
            ]

            for etiqueta, valor in datos:
                row = tk.Frame(datos_frame, bg="#0d1b2a")
                row.pack(fill=tk.X, pady=2)
                tk.Label(row, text=etiqueta, bg="#0d1b2a", fg="#94a3b8",
                         font=("Segoe UI", 10)).pack(side=tk.LEFT)
                tk.Label(row, text=valor, bg="#0d1b2a", fg="#ffffff",
                         font=("Consolas", 10, "bold")).pack(side=tk.RIGHT)

            criterio_frame = tk.Frame(resultado_frame, bg="#112240",
                                       bd=1, relief=tk.GROOVE)
            criterio_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

            tk.Label(criterio_frame, text="CRITERIOS DE EVALUACION:",
                     bg="#112240", fg=COLOR_TITULO,
                     font=("Segoe UI", 9, "bold")).pack(
                anchor="w", padx=10, pady=(8, 3))

            criterios = [
                ("APROBADO:", "SOM >= 20 dB", COLOR_VERDE),
                ("RIESGO:", "10 <= SOM < 20 dB", COLOR_AMARILLO),
                ("FALLIDO:", "SOM < 10 dB", COLOR_ROJO),
            ]

            for texto, rango, color in criterios:
                row = tk.Frame(criterio_frame, bg="#112240")
                row.pack(fill=tk.X, padx=10, pady=1)
                tk.Label(row, text="  ", bg=color, width=3).pack(
                    side=tk.LEFT, padx=(0, 8))
                tk.Label(row, text=texto, bg="#112240", fg="#ffffff",
                         font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
                tk.Label(row, text=rango, bg="#112240", fg="#94a3b8",
                         font=("Consolas", 9)).pack(side=tk.LEFT, padx=5)

            tk.Frame(criterio_frame, bg="#112240", height=5).pack()

            explicacion = {
                "APROBADO": "La cobertura es adecuada para aplicaciones de tiempo real (voz/video).",
                "RIESGO": "La cobertura puede ser insuficiente en condiciones adversas.",
                "FALLIDO": "La cobertura NO es suficiente. Se requiere reubicar o agregar AP."
            }

            tk.Label(resultado_frame,
                     text=explicacion.get(veredicto, ""),
                     bg="#0d1b2a", fg="#94a3b8",
                     font=("Segoe UI", 9),
                     wraplength=400, justify="left").pack(
                padx=10, pady=(5, 10), anchor="w")

            self._actualizar_panel_principal(distancia, banda, frecuencia,
                                             fspl, p_rx, som, veredicto, cumple)

        ttk.Button(form_frame, text="Calcular",
                   style="Accion.TButton",
                   command=calcular).pack(pady=(5, 0))

        entry_distancia.focus_set()
        entry_distancia.bind("<Return>", lambda e: calcular())

    def _actualizar_panel_principal(self, distancia, banda, frecuencia,
                                    fspl, p_rx, som, veredicto, cumple):
        for widget in self.frame_resultados.winfo_children():
            widget.destroy()

        color_veredicto = {
            "APROBADO": COLOR_VERDE,
            "RIESGO": COLOR_AMARILLO,
            "FALLIDO": COLOR_ROJO
        }

        bg_veredicto = color_veredicto.get(veredicto, COLOR_ROJO)

        header = tk.Frame(self.frame_resultados, bg=bg_veredicto, height=45)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="  ENLACE PERSONALIZADO",
                 bg=bg_veredicto, fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT, padx=10)

        info_frame = tk.Frame(self.frame_resultados, bg="#0d1b2a")
        info_frame.pack(fill=tk.X, padx=15, pady=(15, 10))

        datos_izquierda = [
            ("Distancia:", f"{distancia:.2f} m"),
            ("Banda:", f"{banda} ({frecuencia} MHz)"),
        ]

        for etiqueta, valor in datos_izquierda:
            row = tk.Frame(info_frame, bg="#0d1b2a")
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=etiqueta, style="TLabel",
                      font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=8)
            ttk.Label(row, text=valor, style="Resultado.TLabel",
                      font=("Consolas", 9)).pack(side=tk.RIGHT, padx=8)

        ttk.Separator(self.frame_resultados,
                      orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15, pady=5)

        banda_frame = tk.Frame(self.frame_resultados, bg="#0d1b2a",
                                bd=1, relief=tk.GROOVE)
        banda_frame.pack(fill=tk.X, padx=15, pady=5)

        titulo_banda = tk.Frame(banda_frame, bg="#112240")
        titulo_banda.pack(fill=tk.X)
        tk.Label(titulo_banda, text=f"  BANDA: {banda}",
                 bg="#112240", fg=COLOR_TITULO,
                 font=("Segoe UI", 10, "bold")).pack(
            side=tk.LEFT, padx=5, pady=5)

        resultados_data = [
            ("FSPL:", f"{fspl:.2f} dB"),
            ("P_rx:", f"{p_rx:.2f} dBm"),
            ("SOM:", f"{som:.2f} dB"),
            ("RSSI > -67 dBm:", "SI" if cumple else "NO"),
        ]

        for etiqueta, valor in resultados_data:
            row = tk.Frame(banda_frame, bg="#0d1b2a")
            row.pack(fill=tk.X, padx=10, pady=1)
            ttk.Label(row, text=etiqueta, style="TLabel",
                      font=("Segoe UI", 9)).pack(side=tk.LEFT)
            ttk.Label(row, text=valor, style="Resultado.TLabel",
                      font=("Consolas", 9)).pack(side=tk.RIGHT)

        veredicto_frame = tk.Frame(banda_frame, bg="#0d1b2a")
        veredicto_frame.pack(fill=tk.X, padx=10, pady=(5, 10))

        tk.Label(veredicto_frame, text="RESULTADO:", bg="#0d1b2a",
                 fg="#94a3b8",
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=8)

        tk.Label(veredicto_frame, text=f"  {veredicto}  ",
                 bg=bg_veredicto, fg="#ffffff",
                 font=("Segoe UI", 11, "bold"),
                 padx=15, pady=3).pack(side=tk.RIGHT, padx=8)

    def _ventana_tabla_referencia(self):
        ventana = tk.Toplevel(self.root)
        ventana.title("Tabla de Referencia - Comparacion entre Bandas")
        ventana.geometry("950x480")
        ventana.configure(bg=COLOR_PANEL)
        ventana.transient(self.root)

        tk.Label(ventana, text="TABLA DE REFERENCIA - COMPARACION ENTRE BANDAS",
                 bg=COLOR_PANEL, fg=COLOR_TITULO,
                 font=("Segoe UI", 14, "bold")).pack(pady=(15, 10))

        columnas = ("distancia", "banda", "fspl", "prx", "som", "rssi", "resultado")
        tree = ttk.Treeview(ventana, columns=columnas, show="headings",
                            height=12)

        tree.heading("distancia", text="Dist. (m)")
        tree.heading("banda", text="Banda")
        tree.heading("fspl", text="FSPL (dB)")
        tree.heading("prx", text="P_rx (dBm)")
        tree.heading("som", text="SOM (dB)")
        tree.heading("rssi", text="> -67 dBm")
        tree.heading("resultado", text="Resultado")

        tree.column("distancia", width=80, anchor="center")
        tree.column("banda", width=100, anchor="center")
        tree.column("fspl", width=100, anchor="center")
        tree.column("prx", width=110, anchor="center")
        tree.column("som", width=100, anchor="center")
        tree.column("rssi", width=90, anchor="center")
        tree.column("resultado", width=120, anchor="center")

        style_tree = ttk.Style()
        style_tree.configure("Treeview",
                             background="#0d1b2a",
                             foreground="#e0e0e0",
                             fieldbackground="#0d1b2a",
                             font=("Consolas", 10),
                             rowheight=30)
        style_tree.configure("Treeview.Heading",
                             background=COLOR_BOTON,
                             foreground="#ffffff",
                             font=("Segoe UI", 10, "bold"))
        style_tree.map("Treeview",
                       background=[("selected", "#1a508b")])

        scrollbar = ttk.Scrollbar(ventana, orient=tk.VERTICAL,
                                   command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(15, 0),
                  pady=(0, 15))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 15), pady=(0, 15))

        for distancia in [5, 10, 15, 20]:
            for banda, frecuencia in FRECUENCIAS.items():
                fspl = calcular_fspl(distancia, frecuencia)
                p_rx = calcular_prx(P_TX, G_TX, L_TX, fspl, G_RX, L_RX)
                som = calcular_som(p_rx, SENSIBILIDAD_RX)
                veredicto = evaluar_veredicto(som)
                cumple = "SI" if cumple_rssi_objetivo(p_rx, RSSI_OBJETIVO_MIN) else "NO"

                tag = "aprobado" if veredicto == "APROBADO" else (
                    "riesgo" if veredicto == "RIESGO" else "fallido")

                tree.insert("", "end", values=(
                    f"{distancia}", banda, f"{fspl:.2f}",
                    f"{p_rx:.2f}", f"{som:.2f}", cumple, veredicto
                ), tags=(tag,))

        tree.tag_configure("aprobado", foreground=COLOR_VERDE)
        tree.tag_configure("riesgo", foreground=COLOR_AMARILLO)
        tree.tag_configure("fallido", foreground=COLOR_ROJO)

    def _ventana_resumen(self):
        ventana = tk.Toplevel(self.root)
        ventana.title("Resumen del Rediseno - 5 GHz")
        ventana.geometry("700x520")
        ventana.configure(bg=COLOR_PANEL)
        ventana.transient(self.root)

        tk.Label(ventana, text="RESUMEN DEL REDISENO - 5 GHz",
                 bg=COLOR_PANEL, fg=COLOR_TITULO,
                 font=("Segoe UI", 14, "bold")).pack(pady=(15, 15))

        aprobados = 0
        cumplen = 0
        frecuencia = FRECUENCIAS["5 GHz"]

        for zona in ZONAS:
            fspl = calcular_fspl(zona["distancia_max_m"], frecuencia)
            p_rx = calcular_prx(P_TX, G_TX, L_TX, fspl, G_RX, L_RX)
            som = calcular_som(p_rx, SENSIBILIDAD_RX)
            veredicto = evaluar_veredicto(som)
            cumple = cumple_rssi_objetivo(p_rx, RSSI_OBJETIVO_MIN)

            if veredicto == "APROBADO":
                aprobados += 1
            if cumple:
                cumplen += 1

            ap_frame = tk.Frame(ventana, bg="#0d1b2a", bd=1, relief=tk.GROOVE)
            ap_frame.pack(fill=tk.X, padx=20, pady=5)

            header = tk.Frame(ap_frame, bg=zona["color"], height=35)
            header.pack(fill=tk.X)
            header.pack_propagate(False)
            tk.Label(header, text=f"  {zona['ap']}",
                     bg=zona["color"], fg="#ffffff",
                     font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT, padx=10)

            data_frame = tk.Frame(ap_frame, bg="#0d1b2a")
            data_frame.pack(fill=tk.X, padx=10, pady=8)

            datos_izq = [
                f"Zona: {zona['zona']}",
                f"Distancia: {zona['distancia_max_m']} m",
            ]
            datos_der = [
                f"P_rx: {p_rx:.2f} dBm",
                f"SOM: {som:.2f} dB",
            ]

            col_izq = tk.Frame(data_frame, bg="#0d1b2a")
            col_izq.pack(side=tk.LEFT, fill=tk.X, expand=True)
            col_der = tk.Frame(data_frame, bg="#0d1b2a")
            col_der.pack(side=tk.RIGHT, fill=tk.X, expand=True)

            for texto in datos_izq:
                tk.Label(col_izq, text=texto, bg="#0d1b2a", fg="#94a3b8",
                         font=("Segoe UI", 9), anchor="w").pack(anchor="w")

            for texto in datos_der:
                tk.Label(col_der, text=texto, bg="#0d1b2a", fg="#94a3b8",
                         font=("Consolas", 9), anchor="e").pack(anchor="e")

            color_v = {"APROBADO": COLOR_VERDE, "RIESGO": COLOR_AMARILLO,
                       "FALLIDO": COLOR_ROJO}

            tk.Label(data_frame, text=f"  {veredicto}  ",
                     bg=color_v.get(veredicto, COLOR_ROJO), fg="#ffffff",
                     font=("Segoe UI", 9, "bold"),
                     padx=8).pack(side=tk.RIGHT, padx=(10, 0))

        resumen_frame = tk.Frame(ventana, bg="#112240", bd=1, relief=tk.GROOVE)
        resumen_frame.pack(fill=tk.X, padx=20, pady=15)

        tk.Label(resumen_frame, text="ESTADISTICAS FINALES",
                 bg="#112240", fg=COLOR_TITULO,
                 font=("Segoe UI", 11, "bold")).pack(pady=(10, 5))

        stats = [
            (f"AP con resultado APROBADO en 5 GHz:",
             f"{aprobados}/{len(ZONAS)}"),
            (f"AP que superan -67 dBm en 5 GHz:",
             f"{cumplen}/{len(ZONAS)}"),
        ]

        for etiqueta, valor in stats:
            row = tk.Frame(resumen_frame, bg="#112240")
            row.pack(fill=tk.X, padx=20, pady=3)
            tk.Label(row, text=etiqueta, bg="#112240", fg="#94a3b8",
                     font=("Segoe UI", 10)).pack(side=tk.LEFT)
            tk.Label(row, text=valor, bg="#112240", fg="#ffffff",
                     font=("Consolas", 11, "bold")).pack(side=tk.RIGHT)

        tk.Label(resumen_frame,
                 text="Este resultado representa cobertura teorica.",
                 bg="#112240", fg="#64748b",
                 font=("Segoe UI", 8)).pack(pady=(10, 5))

        tk.Label(resumen_frame,
                 text="La capacidad de usuarios simultaneos NO es calculada.",
                 bg="#112240", fg="#64748b",
                 font=("Segoe UI", 8)).pack(pady=(0, 10))

    def _ventana_parametros(self):
        ventana = tk.Toplevel(self.root)
        ventana.title("Parametros del Proyecto")
        ventana.geometry("450x450")
        ventana.configure(bg=COLOR_PANEL)
        ventana.transient(self.root)

        tk.Label(ventana, text="PARAMETROS UTILIZADOS",
                 bg=COLOR_PANEL, fg=COLOR_TITULO,
                 font=("Segoe UI", 14, "bold")).pack(pady=(15, 20))

        parametros = [
            ("Potencia TX (P_TX):", f"{P_TX} dBm"),
            ("Ganancia antena TX (G_TX):", f"{G_TX} dBi"),
            ("Ganancia antena RX (G_RX):", f"{G_RX} dBi"),
            ("Perdidas TX (L_TX):", f"{L_TX} dB"),
            ("Perdidas RX (L_RX):", f"{L_RX} dB"),
            ("Sensibilidad receptor:", f"{SENSIBILIDAD_RX} dBm"),
            ("Umbral RSSI objetivo:", f"{RSSI_OBJETIVO_MIN} dBm"),
            ("", ""),
            ("Frecuencias evaluadas:", ""),
            ("  Banda 2.4 GHz:", "2437 MHz (Canal 6)"),
            ("  Banda 5 GHz:", "5180 MHz (Canal 36)"),
            ("", ""),
            ("Criterios SOM:", ""),
            ("  FALLIDO:", "SOM < 10 dB"),
            ("  RIESGO:", "10 <= SOM < 20 dB"),
            ("  APROBADO:", "SOM >= 20 dB"),
        ]

        params_frame = tk.Frame(ventana, bg="#0d1b2a", bd=1, relief=tk.GROOVE)
        params_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        for i, (etiqueta, valor) in enumerate(parametros):
            if not etiqueta and not valor:
                tk.Frame(params_frame, bg="#0d1b2a", height=8).pack()
                continue

            row_bg = "#0d1b2a" if i % 2 == 0 else "#112240"
            row = tk.Frame(params_frame, bg=row_bg)
            row.pack(fill=tk.X, padx=10, pady=1)

            tk.Label(row, text=etiqueta, bg=row_bg, fg="#94a3b8",
                     font=("Segoe UI", 10),
                     anchor="w").pack(side=tk.LEFT, padx=10, pady=4)

            tk.Label(row, text=valor, bg=row_bg, fg="#ffffff",
                     font=("Consolas", 10, "bold"),
                     anchor="e").pack(side=tk.RIGHT, padx=10, pady=4)


# ============================================================================
# 4. PROGRAMA PRINCIPAL
# ============================================================================

def main():
    root = tk.Tk()
    app = CalculadoraWLAN(root)
    root.mainloop()


if __name__ == "__main__":
    main()
