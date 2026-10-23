# RolmerBet 0.4.0

Aplicación de escritorio para Windows que lee cuotas públicas de Triunfobet, las convierte a formato decimal, contrasta los mercados con forma reciente y decide si existe una combinada conservadora dentro de la cuota configurada. El análisis se muestra dentro de la aplicación: no usa correo y nunca realiza la apuesta por ti.

Las cuatro imágenes de la aplicación anterior se reutilizan como cabeceras de **Inicio**, **Partidos**, **Análisis** y **Combinada**, dentro de una interfaz azul, celeste y naranja.

## Instalación rápida

1. Descomprime toda la carpeta en Windows.
2. Instala Python 3.11, 3.12 o 3.13. El instalador lo busca en `PATH`, el Registro de Windows, Python Install Manager y paquetes de Microsoft Store.
3. Ejecuta `INSTALAR.bat` una sola vez.
4. Ejecuta `EJECUTAR.bat`.
5. Elige la fecha en la barra superior con **Hoy**, **Mañana** o escribe `AAAA-MM-DD`.
6. Prueba primero el **Modo demostración**. Después desmarca **Usar datos de demostración** para utilizar datos reales.

## Pasar al modo real

1. Regístrate en [Football-Data.org](https://www.football-data.org/client/register) y copia tu token API.
2. En **Configuración**, pega el token. Desactiva **Modo demostración** desde esa pestaña o desde la barra superior.
3. Mantén **Navegador oculto (headless)** activado.
4. Pulsa **Guardar** y después **Analizar hoy**.

Las cuotas provienen exclusivamente de los textos visibles en Triunfobet. Football-Data.org se usa solo para resultados y forma reciente; nunca aporta ni reemplaza una cuota.

## Qué hace el análisis

- Lee eventos previos visibles y descarta partidos en vivo.
- Filtra los partidos por la fecha seleccionada. Triunfobet debe tener cuotas publicadas para ese día.
- Conserva la cuota exactamente como se ve en Triunfobet. Si está en formato americano la convierte a decimal; si ya es decimal, evita convertirla dos veces.
- Evalúa 1x2 y totales de goles expuestos en la cartelera pública.
- Solo evalúa córners cuando el mercado se pudo leer y ambos equipos tienen al menos ocho partidos de datos de córners. El proveedor estadístico real actual no entrega córners, así que el motor los descarta en vez de inventarlos.
- Aplica una penalización por incertidumbre, muestra calidad de datos y compara la estimación prudente con la probabilidad implícita de la casa.
- Busca una sola combinación de partidos distintos entre cuota 3.00 y 4.00.
- Si para alcanzar esa cuota tendría que bajar los filtros, muestra **NO APOSTAR**.

## Limitaciones honestas de esta versión

- El lector reproduce el recorrido de la web: cierra el aviso promocional, abre **Apuestas deportivas**, entra en **Fútbol**, elige **Partidos de hoy**, **Partidos de mañana** o **Próximos partidos**. Después abre cada liga configurada por separado, comprueba que quedó desplegada y lee sus partidos antes de continuar.
- El recolector 0.3 cubre los mercados 1x2 y total de goles expuestos en la vista por liga. No asigna nombres inventados a mercados desconocidos.
- Football-Data.org no cubre de forma uniforme copas domésticas, selecciones y algunas competiciones. Esos partidos pueden aparecer en **Partidos**, pero quedan descartados si no hay estadísticas verificables.
- A primera hora normalmente no existen titulares confirmados; por eso esta versión no recomienda remates al arco.
- Una cuota “conservadora” no es segura. No persigas pérdidas y usa un monto que puedas perder.

## Programación diaria

En Windows, pulsa **Programar 8:00 A. M.**. Se crea una tarea local que abre la aplicación y ejecuta el análisis según la hora de tu computador. Comprueba que Windows tenga la zona horaria de Venezuela y que el equipo esté encendido.

## Actualizaciones

La aplicación consulta el repositorio público `rolmerdiaz/RolmerBet` al iniciar. Cuando existe una versión nueva, el botón superior cambia a **ACTUALIZAR A X.X.X**. La descarga verifica cada archivo mediante SHA-256 antes de cerrar la aplicación e instalarlo.

El actualizador nunca reemplaza `data/`, `diagnostics/`, `.venv/` ni `.git/`. Por eso conserva la configuración, el token estadístico y el historial. Si la copia falla, restaura los archivos anteriores y deja el detalle en `diagnostics/update.log`.

## Archivos importantes

| Ruta | Función |
|---|---|
| `RolmerBet.pyw` | Lanzador sin consola |
| `RolmerBetUpdater.pyw` | Instala una actualización y permite restaurar los archivos anteriores |
| `version.json` | Versión disponible y firmas SHA-256 de los archivos públicos |
| `rolmerbet/scrapers/triunfobet.py` | Lectura headless y parser de cuotas |
| `rolmerbet/providers/football_data.py` | Forma y resultados recientes |
| `rolmerbet/engine.py` | Probabilidades, filtros y construcción de combinada |
| `rolmerbet/storage.py` | Historial local SQLite |
| `assets/` | Imágenes reutilizadas de la app anterior |
| `diagnostics/` | Evidencias de errores del navegador |
| `data/` | Configuración e historial creados al usar la app |

## Pruebas

Ejecuta `PROBAR.bat`. Las pruebas cubren conversión de cuotas, interpretación del DOM, descarte de eventos en vivo, regla de no forzar una combinada y persistencia del historial.
