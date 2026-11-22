# LUMEN Play — Largometrajes completos

Edición web en español. El catálogo contiene exclusivamente películas de **al menos 60 minutos** con fuentes audiovisuales abiertas y reproducción dentro de la misma página, sin navegación a plataformas externas.

## Catálogo (22 de noviembre de 2026)

| Película | Duración aprox. | Licencia / titular | Medio |
| --- | ---: | --- | --- |
| Valkaama (2010) | 93 min | Tim Baumann, CC BY-SA 3.0 | iframe autorizado YouTube |
| Star Wreck: In the Pirkinning (2005) | 103 min | Autores de Star Wreck, CC BY-SA 3.0 | MP4 Internet Archive, iframe de respaldo |
| The Internet's Own Boy (2014) | 105 min | Brian Knappenberger / Luminant, CC BY-NC-SA 4.0 | MP4 Internet Archive, iframe de respaldo |
| Sita Sings the Blues (2008) | 82 min | Nina Paley; video CC0, derechos musicales separados | MP4 Internet Archive |
| Seder-Masochism (2018) | 78 min | Nina Paley; animación CC0, **música con derechos separados** | MP4 Internet Archive, iframe de respaldo |
| Decay (2012) | 75 min | H2ZZ Productions, CC BY-NC 3.0 | MP4 HD Internet Archive, iframe de respaldo |
| BloodSpell (2007) | 84 min | Strange Company / Hugh Hancock, CC BY-NC 3.0 | MP4 Internet Archive, iframe de respaldo |
| Insecurity (2007) | 76 min | Rohan Harris, CC BY-NC-ND 3.0 | MP4 Internet Archive, iframe de respaldo |
| Paywall: The Business of Scholarship (2018) | 65 min | Jason Schmitt, CC BY 4.0 | iframe Vimeo |

## Política de reproducción

- No hay cortometrajes ni títulos comerciales sin fuentes autorizadas. El código también filtra cualquier película de menos de 60 minutos por seguridad.
- Los botones de reproducción abren el video **dentro de LUMEN Play**. En los nuevos títulos se prioriza HTML5 MP4, con respaldo incrustado de Internet Archive donde esté disponible.
- Los iframes se limitan mediante sandbox sin permisos de ventanas emergentes ni navegación de nivel superior.
- Los archivos de video no son alojados en Render ni por LUMEN. La reproducción aún depende de la disponibilidad de Archive.org, Vimeo y YouTube, de compatibilidad H.264/MP4 y del ancho de banda.
- Los reproductores deben probarse en iPhone, Android y Smart TV; una compilación de código correcta o un despliegue LIVE no prueban que se haya reproducido el largometraje completo.

## Derechos: leer antes de monetizar

- **CC BY-NC y CC BY-NC-ND / CC BY-NC-SA**: no permiten usos comerciales. No monetizar esos títulos mediante publicidad, cuotas de suscripción ni alianzas comerciales sin obtener autorización expresa.
- **CC BY-SA**: requiere atribución y respetar la obligación de compartir adaptaciones bajo la misma licencia.
- **Sita Sings the Blues / Seder-Masochism**: la liberación por Nina Paley no cubre necesariamente los derechos de las canciones incorporadas. No distribuir por separado bandas sonoras ni ofrecer explotación comercial sin revisión legal.
- Se incluyen los autores y la información de licencia en las fichas. Para futuras licencias comerciales contactar a los titulares.
- La retransmisión de archivos desde Internet Archive no equivale a propiedad del catálogo.

## Archivos

- `films-extra.js`: datos de las nueve películas, metadatos y fuentes directas / alternativas.
- `app.js`: filtros, favoritos, historial HTML5, reproductor y respaldo in-app.
- `index.html`, `styles.css`: interfaz responsive.
- `sw.js`, `manifest.webmanifest`, `icon.svg`: PWA; solo se cachea la estructura, no las películas.


## Módulo inalámbrico para TV — Wi-Fi (22/11/2026)

Se sumaron botones **Ver en TV** en el encabezado y el reproductor con tres caminos:

1. **AirPlay**: en iPhone/iPad Safari, usar video HTML5 con `webkitShowPlaybackTargetPicker` y el atributo `x-webkit-airplay="allow"`. Requiere un Apple TV o Smart TV compatible con AirPlay, en la misma red Wi-Fi. En películas con iframe el botón de LUMEN no puede controlar AirPlay directamente; se puede intentar Duplicar pantalla desde Centro de control (función del sistema, no de la web).
2. **Google Cast**: en Chrome compatible de Android o computadora, el módulo `tv.js` carga el SDK Web Sender, utiliza el receptor multimedia predeterminado de Google Cast (sin registrar un receptor personalizado), solicita una sesión y envía el video directo público MP4/WebM mediante `LoadRequest`. Controles básicos de pausar/reanudar y desconectar en el panel. **No funciona Google Cast desde Safari/Chrome en iPhone**, por limitación del SDK Web Sender. Las películas que solo ofrecen un iframe, sin una URL MP4 pública, no pueden enviarse con este método.
3. **Navegador Smart TV**: ingresar `https://lumen-play-premium.onrender.com/?tv=1` desde el navegador integrado del televisor. Se aplica un modo de foco y navegación por teclado/control remoto. No vincula automáticamente el teléfono a la TV ni promete funciones de control remoto bidireccional.

### Condiciones y limitaciones
- El dispositivo emisor y receptor deben estar en la **misma red Wi-Fi** (sin aislamiento de clientes ni red de invitados incompatible).
- El archivo reproducido en TV depende de la disponibilidad y codificación de la fuente pública. Un MP4 válido en el celular puede fallar en el Chromecast o navegador de la TV. La conexión y el streaming completos requieren pruebas con equipos reales.
- Los iframes de YouTube, Vimeo o Internet Archive pueden tener restricciones de proveedor. La versión web no controla las opciones AirPlay/Cast internas de estos reproductores.
- Los videos locales cargados como `blob:` no son accesibles desde un Chromecast (no existe URL pública).
- El SDK de Google se carga solo en navegadores potencialmente compatibles y desde HTTPS; no se carga en iPhone.
- El botón Cast usa el receptor multimedia genérico sin app ID personalizado. No crea una conexión directa entre el navegador y cualquier TV; requiere un dispositivo Google Cast real.
- `tv.js` y las opciones del panel no eluden DRM ni licencias, y no se redistribuye contenido comercial sin permiso.

### Prueba manual
1. En iPhone Safari, reproducir MP4 y pulsar Ver en TV → Elegir TV con AirPlay con Apple TV/televisor AirPlay en el mismo Wi-Fi.
2. En Android Chrome o Chrome desktop, reproducir una película con MP4 público y pulsar Ver en TV → Buscar dispositivos Cast. Seleccionar el receptor y verificar reproducción, controles y desconexión.
3. Intentar Cast con Valkaama (iframe sin MP4), comprobar mensaje claro, sin falsas conexiones.
4. Abrir la web en el navegador de una Smart TV y navegar con control remoto.
5. Verificar cierre de panel y reproductor y que no se abren ventanas externas.

## Lista de verificación

1. Confirmar nueve fichas y duraciones >=60 min, sin cortos.
2. Reproducir inicio y avance de cada archivo MP4 en Safari iPhone y Chrome Android.
3. Cortar la reproducción y reanudar desde el historial HTML5.
4. Probar fallback embebido en una fuente MP4 fallida sin abrir nueva ventana.
5. Verificar que los iframes se cierran al salir del reproductor, dejando de reproducir audio.
6. Comprobar filtro de géneros, favoritos y biblioteca local.
