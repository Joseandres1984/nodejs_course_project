# LUMEN Play 2.0 — reproducción dentro de la aplicación

## Regla de reproducción interna (22/11/2026)
**No se muestran películas comerciales ni fichas sin una fuente de video utilizable dentro de LUMEN Play.** El catálogo visible filtra los títulos sin licencias/fuentes internas. El botón Reproducir no abre pestañas ni aplicaciones ajenas. Para los largometrajes con autorizaciones se usa el elemento HTML5 video o un iframe autorizado y limitado mediante sandbox (sin popups ni navegación de nivel superior). Los errores se informan dentro de la app con botón de reintento.

Los MP4 de Blender están enlazados desde su webseed oficial; las obras que ofrecen solo WebM se ocultan automáticamente si el navegador no admite ese formato. En iPhone/Smart TV la compatibilidad real debe verificarse en el dispositivo. Ni LUMEN ni Render alojan los archivos originales. La disponibilidad nunca puede garantizarse al 100% cuando la fuente depende de un servidor ajeno. Para tener garantía plena hace falta distribución propia bajo licencias expresas, almacenamiento y CDN.

La lista de películas comerciales de la etapa anterior se conserva en el código fuente histórico, pero **no aparece en la interfaz** porque no existe una autorización de distribución directa. La lista "Dónde verla" y los partners externos se retiraron de la interfaz.

Webapp independiente en español, sin build ni servicios de pago. Incluye catálogo legal (Blender Studio / Blender Foundation), películas comerciales con enlaces de disponibilidad externos, diseño responsive, favoritos y progreso en localStorage, biblioteca local de archivos, subtítulos WebVTT y PWA.

## Archivos
- index.html: interfaz
- styles.css: sistema visual y diseño adaptable
- app.js: catálogo, filtros, favoritos y reproductor
- manifest.webmanifest, sw.js, icon.svg: instalación PWA

## Desarrollo
Servir desde HTTP localhost o HTTPS para activar service worker: python -m http.server 8080 -d lumen-play

## Contenido y licencias
Los cortos abiertos son creaciones de Blender Studio / Blender Foundation con licencias Creative Commons. Los archivos MP4 se sirven desde video.blender.org y las opciones 2K/4K WebM desde Wikimedia Commons (ver ficha de cada archivo y su licencia específica). Los filmes comerciales no se alojan ni transmiten en LUMEN Play; se redirigen a opciones legales. Imágenes comerciales ilustrativas (Unsplash). Mantener atribuciones y revisar las fuentes al actualizar.

## Limitaciones conscientes
Los medios externos dependen de disponibilidad y formatos del navegador; 4K WebM solo se ofrece cuando el navegador lo admite. Los favoritos e historial son locales al navegador, no se sincronizan entre dispositivos. Los archivos cargados por el usuario permanecen en su dispositivo y deben reabrirse en cada sesión. Sin backend, cuentas ni DRM. El service worker cachea exclusivamente el shell (no las películas).

## Verificación manual
1. Abrir y buscar "Charge". Reproducir MP4 HD.
2. En dispositivo compatible cambiar a 4K y verificar continuidad.
3. Agregar a Mi lista, recargar y verificar persistencia.
4. Reproducir unos segundos, cerrar y verificar Continuar viendo.
5. Buscar por género y por título, probar filtros.
6. Abrir F1: solo debería navegar al proveedor externo.
7. Seleccionar MP4 local: no debe generarse subida de red.
8. Usar iPhone Safari, Android Chrome y teclado.

## Largometrajes completos (22/11/2026)
LUMEN Play incluye una sección exclusiva con fuentes identificadas:

1. **Paywall: The Business of Scholarship** (2018, ~65 min). Jason Schmitt, CC BY 4.0. Reproductor original Vimeo (video 273358286) y archivo fuente de Internet Archive. [Licencia y original](https://archive.org/details/PaywallTheBusinessOfScholarshipFinalMovieMastered). Archivo MP4 máster de ~7,2 GB: no usar como predeterminado móvil.
2. **Valkaama** (2010, ~93 min). Tim Baumann y equipo. Licencia [CC BY-SA 3.0](https://www.valkaama.com/index.php?l=en&page=valkaama). Reproductor integrado de YouTube con salida a la web de los autores. La edición HD original usa MKV, no ideal para Safari.
3. **Sita Sings the Blues** (2008, ~82 min). Nina Paley. Reproducción de los MP4 originales enlazados desde su [página de visualización](https://www.sitasingstheblues.com/watch.html), con selecciones liviana / 720p / 1080p según conexión. Paley puso la obra visual bajo CC0, **pero algunas canciones conservan derechos separados**; no reutilizar pistas musicales ni asumir permiso de explotación comercial audiovisual sin comprobarlo.

### Limitaciones y pruebas adicionales
- Las películas completas no se guardan ni se redistribuyen desde los servidores de LUMEN Play. Se sirven desde Internet Archive, Vimeo o YouTube según cada obra.
- Los reproductores incorporados dependen del ancho de banda, de la disponibilidad de la fuente y de posibles restricciones del proveedor.
- En iPhone se prioriza streaming adaptativo (Vimeo/YouTube) donde está disponible; los MP4 de Internet Archive pueden tener descarga inicial lenta y no se verificaron en iPhone real.
- El historial y «Continuar viendo» funcionan con videos HTML5 propios del reproductor, pero no con iframes externos, que no exponen la posición.
- Revisar licencias, posibilidad de monetización y términos de cada fuente antes de escalar LUMEN Play para un público comercial.
