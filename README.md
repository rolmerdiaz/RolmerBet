# RolmerBet 0.5.1

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

1. Desactiva **Modo demostración** desde la barra superior o desde **Configuración**.
2. Mantén **Navegador oculto (headless)** activado.
3. Pulsa **Guardar** y después **Analizar fecha**. Ya no necesitas registrarte ni pegar un token estadístico.

Las cuotas provienen exclusivamente de los textos visibles en Triunfobet. La fuente pública de ESPN se usa solo para resultados, forma, córners, remates y alineaciones; nunca aporta ni reemplaza una cuota.

## Qué hace el análisis

- Lee eventos previos visibles y descarta partidos en vivo.
- Filtra los partidos por la fecha seleccionada. Triunfobet debe tener cuotas publicadas para ese día.
- Conserva la cuota exactamente como se ve en Triunfobet. Si está en formato americano la convierte a decimal; si ya es decimal, evita convertirla dos veces.
- Evalúa 1x2, doble oportunidad, totales de goles del partido y de cada equipo. En **Total de goles** recorre las líneas alternativas visibles 0.5, 1.5, 2.5, 3.5 y 4.5, sin limitarse a la línea principal.
- Evalúa córners totales y por equipo cuando Triunfobet publica el mercado y existen al menos cinco partidos recientes con ese dato para ambos equipos.
- Evalúa remates a puerta totales del partido y de cada equipo. Los remates a puerta de un jugador solo pueden entrar si aparece como titular confirmado y hay al menos tres apariciones recientes con estadísticas.
- Aplica una penalización por incertidumbre, muestra calidad de datos y compara la estimación prudente con la probabilidad implícita de la casa.
- Busca una sola combinación de partidos distintos entre cuota 3.00 y 4.00.
- Si para alcanzar esa cuota tendría que bajar los filtros, muestra **NO APOSTAR**.

## Limitaciones honestas de esta versión

- El lector reproduce el recorrido de la web: cierra el aviso promocional, abre **Apuestas deportivas**, entra en **Fútbol**, elige **Partidos de hoy**, **Partidos de mañana** o **Próximos partidos**. Después abre cada liga configurada por separado, comprueba que quedó desplegada y lee sus partidos antes de continuar.
- El recolector abre el detalle de cada partido de la fecha elegida y lee los nombres y precios visibles de los mercados compatibles. No asigna nombres ni cuotas inventadas a mercados desconocidos.
- La fuente estadística no cubre de forma uniforme todas las copas y selecciones. Esos partidos pueden aparecer en **Partidos**, pero quedan descartados si no hay estadísticas verificables.
- A primera hora normalmente no existen titulares confirmados; por eso los remates a puerta de jugadores se muestran pero se descartan hasta que la alineación oficial esté disponible.
- Una cuota “conservadora” no es segura. No persigas pérdidas y usa un monto que puedas perder.

## Programación diaria

En Windows, pulsa **Programar 8:00 A. M.**. Se crea una tarea local que abre la aplicación y ejecuta el análisis según la hora de tu computador. Comprueba que Windows tenga la zona horaria de Venezuela y que el equipo esté encendido.

## Actualizaciones

La aplicación consulta el repositorio público `rolmerdiaz/RolmerBet` al iniciar. Cuando existe una versión nueva, el botón superior cambia a **ACTUALIZAR A X.X.X**. La descarga verifica cada archivo mediante SHA-256 antes de cerrar la aplicación e instalarlo.

El actualizador nunca reemplaza `data/`, `diagnostics/`, `.venv/` ni `.git/`. Por eso conserva la configuración y el historial. Si la copia falla, restaura los archivos anteriores y deja el detalle en `diagnostics/update.log`.

## Archivos importantes

| Ruta | Función |
|---|---|
| `RolmerBet.pyw` | Lanzador sin consola |
| `RolmerBetUpdater.pyw` | Instala una actualización y permite restaurar los archivos anteriores |
| `version.json` | Versión disponible y firmas SHA-256 de los archivos públicos |
| `rolmerbet/scrapers/triunfobet.py` | Lectura headless y parser de cuotas |
| `rolmerbet/providers/espn.py` | Forma, resultados, córners, remates y titulares |
| `rolmerbet/engine.py` | Probabilidades, filtros y construcción de combinada |
| `rolmerbet/storage.py` | Historial local SQLite |
| `assets/` | Imágenes reutilizadas de la app anterior |
| `diagnostics/` | Evidencias de errores del navegador |
| `data/` | Configuración e historial creados al usar la app |

## Pruebas

Ejecuta `PROBAR.bat`. Las pruebas cubren conversión de cuotas, interpretación del DOM, descarte de eventos en vivo, regla de no forzar una combinada y persistencia del historial.
