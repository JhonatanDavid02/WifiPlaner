"""
=============================================================================
CALCULADORA DE INGENIERIA WLAN - BIBLIOTECA UNIVERSITARIA
Auditoria y Rediseno de Red Wi-Fi
Corporacion Unificada Nacional de Educacion Superior (CUN)
Asignatura: Redes Inalambricas

VERSION 3 - DEMO INTERACTIVA

Basada en:
- Granulo 1: Fundamentos de Redes Inalambricas
- Granulo 2: Diseno y Configuracion de WLAN
- Granulo 3: Seguridad en Redes Inalambricas

IMPORTANTE:
Este programa realiza un analisis teorico de COBERTURA mediante
presupuesto de enlace.

NO calcula capacidad de usuarios simultaneos.
NO sustituye un Site Survey fisico.
NO representa una medicion real de RSSI.

La finalidad de esta version es permitir una demostracion interactiva
del funcionamiento del calculo WLAN durante la presentacion.
=============================================================================
"""

import math


# ============================================================================
# 1. FUNCIONES DE FISICA DE RF - G1
# ============================================================================

def calcular_longitud_onda(frecuencia_hz):
    """
    G1:
        lambda = c / f

    Devuelve la longitud de onda en metros.
    """
    c = 300_000_000  # m/s
    return c / frecuencia_hz


def calcular_fspl(distancia_m, frecuencia_mhz):
    """
    G1 / G2:

        FSPL(dB) = 20*log10(d) + 20*log10(f) - 27.55

    d = distancia en metros
    f = frecuencia en MHz
    """

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


# ============================================================================
# 2. FUNCIONES DE PRESUPUESTO DE ENLACE - G2
# ============================================================================

def calcular_prx(p_tx, g_tx, l_tx, fspl, g_rx, l_rx):
    """
    G2 - Formulacion utilizada en el script de enlaces PtP:

        P_rx = P_tx + G_tx - L_tx - FSPL + G_rx - L_rx

    El resultado representa potencia recibida teorica calculada.
    """

    p_rx = (
        p_tx
        + g_tx
        - l_tx
        - fspl
        + g_rx
        - l_rx
    )

    return round(p_rx, 2)


def calcular_som(p_rx, sensibilidad_rx):
    """
    G2:

        SOM = P_rx - Sensibilidad del receptor
    """

    return round(p_rx - sensibilidad_rx, 2)


def evaluar_veredicto(som):
    """
    G2:

        SOM < 10 dB       -> FALLIDO
        10 <= SOM < 20 dB -> RIESGO
        SOM >= 20 dB      -> APROBADO
    """

    if som < 10:
        return "FALLIDO"

    elif som < 20:
        return "RIESGO"

    else:
        return "APROBADO"


def cumple_rssi_objetivo(p_rx, umbral=-67.0):
    """
    Umbral utilizado para evaluar si la potencia recibida supera
    el objetivo de -67 dBm.

    Se utiliza > -67 dBm.
    """

    return p_rx > umbral


# ============================================================================
# 3. PARAMETROS DEL PROYECTO
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


# ============================================================================
# 4. ZONAS DEL REDISENO
# ============================================================================

ZONAS = [
    {
        "ap": "AP1",
        "zona": "Entrada Principal + Sala Audiovisual",
        "sala_critica": "Entrada Principal (15,48 m2)",
        "distancia_max_m": 5.72
    },

    {
        "ap": "AP2",
        "zona": "Sala de Estudio Colaborativo + Zaguan",
        "sala_critica": "Sala de Estudio Colaborativo (37,62 m2)",
        "distancia_max_m": 8.92
    },

    {
        "ap": "AP3",
        "zona": "Atencion/Circulacion + Deposito + Informatica + Sanitarios",
        "sala_critica": "Atencion y Circulacion Bibliotecaria (22,33 m2)",
        "distancia_max_m": 6.87
    },

    {
        "ap": "AP4",
        "zona": "Hemeroteca + Sala de Lectura",
        "sala_critica": "Sala de Lectura (44,02 m2)",
        "distancia_max_m": 9.65
    }
]


# ============================================================================
# 5. FUNCIONES DE PRESENTACION
# ============================================================================

def mostrar_encabezado():
    print("\n" + "=" * 80)
    print("     CALCULADORA WLAN - BIBLIOTECA UNIVERSITARIA")
    print("     AUDITORIA Y REDISENO DE RED WI-FI")
    print("=" * 80)


def mostrar_parametros():
    print("\n" + "=" * 80)
    print("PARAMETROS UTILIZADOS")
    print("=" * 80)

    print(f"Potencia TX:              {P_TX} dBm")
    print(f"Ganancia antena TX:       {G_TX} dBi")
    print(f"Ganancia antena RX:       {G_RX} dBi")
    print(f"Perdidas TX:              {L_TX} dB")
    print(f"Perdidas RX:              {L_RX} dB")
    print(f"Sensibilidad receptor:    {SENSIBILIDAD_RX} dBm")
    print(f"Umbral objetivo:           {RSSI_OBJETIVO_MIN} dBm")


def mostrar_longitudes_onda():
    print("\n" + "=" * 80)
    print("LONGITUD DE ONDA - G1")
    print("=" * 80)

    lambda_24 = calcular_longitud_onda(2_400_000_000)
    lambda_5 = calcular_longitud_onda(5_000_000_000)

    print(f"2.4 GHz: {round(lambda_24 * 100, 2)} cm")
    print(f"5 GHz:   {round(lambda_5 * 100, 2)} cm")


# ============================================================================
# 6. OPCION 1 - TABLA DE REFERENCIA
# ============================================================================

def mostrar_tabla_referencia():

    print("\n" + "=" * 100)
    print("TABLA DE REFERENCIA - COMPARACION ENTRE BANDAS")
    print("=" * 100)

    print(
        f"{'Dist.':<8}"
        f"{'Banda':<12}"
        f"{'FSPL':<10}"
        f"{'P_rx':<12}"
        f"{'SOM':<10}"
        f"{'> -67':<10}"
        f"{'Resultado'}"
    )

    print("-" * 100)

    for distancia in [5, 10, 15, 20]:

        for banda, frecuencia in FRECUENCIAS.items():

            fspl = calcular_fspl(distancia, frecuencia)

            p_rx = calcular_prx(
                P_TX,
                G_TX,
                L_TX,
                fspl,
                G_RX,
                L_RX
            )

            som = calcular_som(
                p_rx,
                SENSIBILIDAD_RX
            )

            veredicto = evaluar_veredicto(som)

            cumple = (
                "SI"
                if cumple_rssi_objetivo(
                    p_rx,
                    RSSI_OBJETIVO_MIN
                )
                else "NO"
            )

            print(
                f"{distancia:<8}"
                f"{banda:<12}"
                f"{fspl:<10}"
                f"{p_rx:<12}"
                f"{som:<10}"
                f"{cumple:<10}"
                f"{veredicto}"
            )

    print("-" * 100)


# ============================================================================
# 7. OPCION 2 - ENLACE PERSONALIZADO
# ============================================================================

def seleccionar_banda():

    print("\nSeleccione la banda:")

    print("1. 2.4 GHz")
    print("2. 5 GHz")

    while True:

        opcion = input("\nOpcion: ").strip()

        if opcion == "1":
            return "2.4 GHz", 2437

        elif opcion == "2":
            return "5 GHz", 5180

        else:
            print("Opcion invalida. Seleccione 1 o 2.")


def evaluar_enlace_personalizado():

    print("\n" + "=" * 80)
    print("EVALUACION DE ENLACE PERSONALIZADO")
    print("=" * 80)

    while True:

        try:

            distancia = float(
                input("Ingrese la distancia en metros: ")
            )

            if distancia <= 0:
                print("La distancia debe ser mayor que 0.")
                continue

            break

        except ValueError:
            print("Ingrese un numero valido.")

    banda, frecuencia = seleccionar_banda()

    fspl = calcular_fspl(
        distancia,
        frecuencia
    )

    p_rx = calcular_prx(
        P_TX,
        G_TX,
        L_TX,
        fspl,
        G_RX,
        L_RX
    )

    som = calcular_som(
        p_rx,
        SENSIBILIDAD_RX
    )

    veredicto = evaluar_veredicto(som)

    cumple = cumple_rssi_objetivo(
        p_rx,
        RSSI_OBJETIVO_MIN
    )

    print("\n" + "-" * 80)
    print("RESULTADO DEL ENLACE")
    print("-" * 80)

    print(f"Distancia:              {distancia:.2f} m")
    print(f"Banda:                  {banda}")
    print(f"Frecuencia:             {frecuencia} MHz")
    print(f"FSPL:                   {fspl:.2f} dB")
    print(f"P_rx:                   {p_rx:.2f} dBm")
    print(f"SOM:                    {som:.2f} dB")
    print(f"Supera -67 dBm:         {'SI' if cumple else 'NO'}")
    print(f"Veredicto SOM:          {veredicto}")

    print("-" * 80)


# ============================================================================
# 8. OPCION 3 - EVALUAR AP
# ============================================================================

def mostrar_ap(ap):

    zona = None

    for z in ZONAS:

        if z["ap"] == ap:
            zona = z
            break

    if zona is None:
        print("AP no encontrado.")
        return

    print("\n" + "=" * 80)
    print(f"EVALUACION DE {zona['ap']}")
    print("=" * 80)

    print(f"Zona:          {zona['zona']}")
    print(f"Sala critica:  {zona['sala_critica']}")
    print(f"Distancia:     {zona['distancia_max_m']} m")

    print("\n" + "-" * 80)

    for banda, frecuencia in FRECUENCIAS.items():

        fspl = calcular_fspl(
            zona["distancia_max_m"],
            frecuencia
        )

        p_rx = calcular_prx(
            P_TX,
            G_TX,
            L_TX,
            fspl,
            G_RX,
            L_RX
        )

        som = calcular_som(
            p_rx,
            SENSIBILIDAD_RX
        )

        veredicto = evaluar_veredicto(som)

        cumple = cumple_rssi_objetivo(
            p_rx,
            RSSI_OBJETIVO_MIN
        )

        print(f"\nBANDA: {banda}")
        print(f"FSPL:                  {fspl:.2f} dB")
        print(f"P_rx:                  {p_rx:.2f} dBm")
        print(f"SOM:                   {som:.2f} dB")
        print(f"Supera -67 dBm:        {'SI' if cumple else 'NO'}")
        print(f"Resultado:             {veredicto}")

    print("\n" + "-" * 80)


def seleccionar_ap():

    print("\nSeleccione el AP que desea evaluar:")

    for i, zona in enumerate(ZONAS, start=1):

        print(
            f"{i}. {zona['ap']} - {zona['zona']}"
        )

    while True:

        opcion = input("\nOpcion: ").strip()

        if opcion in ["1", "2", "3", "4"]:

            return ZONAS[int(opcion) - 1]["ap"]

        print("Seleccione un AP entre 1 y 4.")


# ============================================================================
# 9. OPCION 4 - RESUMEN DEL REDISENO
# ============================================================================

def resumen_rediseno():

    print("\n" + "=" * 100)
    print("RESUMEN DEL REDISENO")
    print("=" * 100)

    aprobados = 0
    cumplen = 0

    for zona in ZONAS:

        frecuencia = FRECUENCIAS["5 GHz"]

        fspl = calcular_fspl(
            zona["distancia_max_m"],
            frecuencia
        )

        p_rx = calcular_prx(
            P_TX,
            G_TX,
            L_TX,
            fspl,
            G_RX,
            L_RX
        )

        som = calcular_som(
            p_rx,
            SENSIBILIDAD_RX
        )

        veredicto = evaluar_veredicto(som)

        cumple = cumple_rssi_objetivo(
            p_rx,
            RSSI_OBJETIVO_MIN
        )

        if veredicto == "APROBADO":
            aprobados += 1

        if cumple:
            cumplen += 1

        print(
            f"{zona['ap']}: "
            f"{zona['distancia_max_m']} m | "
            f"P_rx = {p_rx:.2f} dBm | "
            f"SOM = {som:.2f} dB | "
            f"{veredicto}"
        )

    print("-" * 100)

    print(
        f"AP con resultado APROBADO en 5 GHz: "
        f"{aprobados}/{len(ZONAS)}"
    )

    print(
        f"AP que superan -67 dBm en 5 GHz: "
        f"{cumplen}/{len(ZONAS)}"
    )

    print("\nIMPORTANTE:")
    print(
        "Este resultado representa solamente cobertura teorica."
    )

    print(
        "La capacidad de usuarios simultaneos no es calculada "
        "por este programa."
    )


# ============================================================================
# 10. MENU PRINCIPAL
# ============================================================================

def mostrar_menu():

    print("\n" + "=" * 80)
    print("MENU PRINCIPAL - DEMO INTERACTIVA")
    print("=" * 80)

    print("1. Ver longitudes de onda")
    print("2. Ver tabla de referencia")
    print("3. Evaluar enlace personalizado")
    print("4. Evaluar un AP del rediseno")
    print("5. Ver resumen del rediseno")
    print("6. Ver parametros utilizados")
    print("0. Salir")

    print("=" * 80)


# ============================================================================
# 11. PROGRAMA PRINCIPAL
# ============================================================================

def main():

    mostrar_encabezado()

    while True:

        mostrar_menu()

        opcion = input("\nSeleccione una opcion: ").strip()

        if opcion == "1":

            mostrar_longitudes_onda()

        elif opcion == "2":

            mostrar_tabla_referencia()

        elif opcion == "3":

            evaluar_enlace_personalizado()

        elif opcion == "4":

            ap = seleccionar_ap()
            mostrar_ap(ap)

        elif opcion == "5":

            resumen_rediseno()

        elif opcion == "6":

            mostrar_parametros()

        elif opcion == "0":

            print("\nPrograma finalizado.")
            print("Gracias por utilizar la calculadora WLAN.")
            break

        else:

            print("\nOpcion invalida. Intente nuevamente.")


# ============================================================================
# EJECUCION
# ============================================================================

if __name__ == "__main__":
    main()