# LUMEN Play 2.0 — edición premium
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
