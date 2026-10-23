# RolmerBet 0.6.2

Aplicación de escritorio para Windows que compara los mercados visibles de Triunfobet con evidencia deportiva independiente y decide si existe una combinada conservadora. El análisis se muestra dentro de la app: no envía correos, no inicia sesión y no realiza apuestas.

## Instalación rápida

1. Descomprime la carpeta completa.
2. Instala Python 3.11, 3.12 o 3.13.
3. Ejecuta `INSTALAR.bat` una vez.
4. Abre `EJECUTAR.bat`.
5. Elige **Hoy**, **Mañana** o escribe una fecha `AAAA-MM-DD`.
6. Desactiva **Usar datos de demostración** para analizar la cartelera real.

El navegador trabaja oculto cuando la opción *Headless* está activa.

## Separación estricta de fuentes

- **Triunfobet:** partidos disponibles, torneo, horario, nombre exacto del mercado, selección y cuota. La app no sustituye esos precios por los de otra casa.
- **ESPN y Sofascore:** forma, goles, rendimiento local/visitante, córners, remates y alineaciones. La búsqueda contempla el día anterior y posterior para absorber diferencias horarias, y Sofascore dispone de dos rutas de conexión.
- **Football-Data.org:** tercera fuente opcional de corroboración si el usuario ya posee un token. Nunca puede ser la única base de una recomendación y sus campos no disponibles no borran córners o remates aportados por otras fuentes.

Si una fuente falla, el análisis continúa con las demás, pero pierde calidad. Los mercados sensibles pueden quedar descartados por evidencia insuficiente. La pestaña **Análisis** muestra las fuentes activas, sus avisos y los bloqueos más frecuentes para que una caída externa no quede oculta.

## Perfil Conservador v2

Cada mercado tiene su propio filtro:

| Familia | Probabilidad prudente mínima | Muestra mínima |
|---|---:|---:|
| Doble oportunidad | 72% | 8 partidos |
| Victoria 1X2 | 64% | 8 partidos |
| Más de 1.5 / menos de 4.5 goles | 74% | 8 partidos |
| Otras líneas de goles | 68% | 8 partidos |
| Goles de equipo | 70% | 8 partidos |
| Córners | 68% | 8 partidos con ese dato |
| Remates al arco del equipo | 68% | 8 partidos con ese dato |
| Remates al arco de jugador | 65% | 5 apariciones y titular confirmado |

La probabilidad prudente es el límite inferior de un intervalo que considera tamaño de muestra, cantidad y acuerdo de fuentes, rotación y tipo de competición. La probabilidad implícita de la cuota sirve como control de precio, no como un segundo castigo automático.

Las victorias y dobles oportunidades no pueden recomendarse mientras las bajas y sanciones sigan sin verificar. Si dos fuentes deportivas discrepan de forma importante, el mercado también queda fuera de la recomendación.

## Orden visual

La pestaña **Análisis** no muestra todas las cuotas juntas:

1. **Lo mejor:** un máximo de un mercado principal por partido.
2. **Alternativas:** selecciones cercanas al filtro, separadas de las recomendaciones.
3. **Descartadas:** ocultas por defecto y disponibles solo para diagnóstico.

Una selección con probabilidad prudente inferior a 55% nunca aparece en la vista principal.

## Combinada

- Cuota total objetivo de 3.00 a 4.00.
- De 2 a 5 partidos, preferiblemente 3 o 4.
- Un solo mercado por partido.
- Probabilidad prudente conjunta mínima de 28%.
- No se añaden cuotas diminutas ni patas débiles para completar el objetivo.
- Si no existe una combinación válida, la app muestra **NO APOSTAR**.

## Actualizaciones

RolmerBet consulta el repositorio público `rolmerdiaz/RolmerBet` al iniciar. Cuando existe una versión nueva, el botón superior permite descargarla, verificar cada archivo mediante SHA-256 e instalarla conservando `data/`, `diagnostics/` y el historial.

## Pruebas

Ejecuta `PROBAR.bat`. La versión 0.6 incluye pruebas de filtros específicos por mercado, jerarquía visual, selección de un mercado por partido, requisito de titularidad, cruce de fuentes y compatibilidad con historiales anteriores.

## Aviso

“Conservadora” describe los filtros; no garantiza resultados. No persigas pérdidas y utiliza únicamente dinero que puedas perder.

