# Scripts Legacy — Wi-Fi Planner

Este directorio contiene los prototipos iniciales y scripts históricos desarrollados durante las etapas tempranas del proyecto (versiones v1 a v4), previos a la arquitectura modular actual.

## Contenido

* **`calculo_wifi_biblioteca.py` (v1):** Primera versión en script plano para el cálculo básico de propagación en espacio libre (FSPL) y presupuesto de enlace.
* **`CalculoWifi2.py` (v2):** Segunda iteración con desglose tabulado por zonas y comparación preliminar de cobertura.
* **`CODIGO(Interactivo).py` (v3):** Prototipo para consola interactiva que permitía ingresar parámetros de radio y distancias por terminal.
* **`CalculadoraWLAN_Visual.py` (v4):** Prototipo gráfico preliminar construido con Tkinter, predecesor de la interfaz actual.

## Propósito y Estado

1. **Trazabilidad histórica:** Se conservan como registro del proceso evolutivo del proyecto y para verificar la coherencia con los documentos y cálculos originales.
2. **Desacoplamiento:** El simulador principal (`wifi_planner/`) y su suite de pruebas unitarias **no dependen directamente** de la ejecución de estos scripts. Los valores de referencia numéricos del documento base se encuentran congelados en las fixtures del motor (`wifi_planner/tests/fixtures/golden_data.py`).
3. **Mantenimiento:** Estos scripts se encuentran congelados y no reciben mantenimiento activo.
