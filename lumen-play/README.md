# LUMEN Play — Solo largometrajes

Edición web premium, en español, con catálogo **exclusivamente de películas completas de 60 minutos o más**. No se incluyen cortometrajes de 3, 4, 8 ni 15 minutos. Tampoco se muestran fichas de películas comerciales que requieran abrir plataformas externas.

## Catálogo activo
| Película | Duración nominal | Reproductor | Licencia / fuente |
| --- | --- | --- | --- |
| Valkaama (2010) | 93 minutos | Video YouTube incrustado en LUMEN Play | Tim Baumann y equipo, CC BY-SA 3.0 · https://www.valkaama.com |
| Sita Sings the Blues (2008) | 82 minutos (aprox.) | Video HTML5 desde Internet Archive | Nina Paley · https://www.sitasingstheblues.com/watch.html |
| Paywall: The Business of Scholarship (2018) | 65 minutos | Video Vimeo incrustado en LUMEN Play | Jason Schmitt · CC BY 4.0 · https://vimeo.com/273358286 |

**Nota de derechos:** las imágenes y la película Sita Sings the Blues tienen condiciones de licencia particulares, y parte de la música puede estar sujeta a derechos independientes. No monetizar ni reutilizar este material sin una revisión jurídica adicional.

## Garantías y límites
- El botón «Reproducir» muestra el video **dentro de LUMEN Play**; el catálogo no ofrece enlaces de reproducción a servicios externos.
- Los reproductores de Vimeo/YouTube se integran en la página; siguen dependiendo de esos proveedores, que podrían bloquear el iframe, imponer restricciones regionales, o cambiar su configuración. No significa que LUMEN aloje el contenido.
- Los archivos MP4 de Internet Archive dependen de la conectividad y compatibilidad del navegador. Ninguna opción se ofrece como una garantía de funcionamiento sin pruebas de reproducción en cada dispositivo.
- Los favoritos e historial de video HTML5 se guardan en almacenamiento local. Los reproductores iframe externos no exponen su progreso a la app.
- La biblioteca de videos propios del usuario funciona por separado; admite los formatos permitidos por el navegador, sin subir archivos.
- Para asegurar reproducción independiente a largo plazo se requieren copias propias de videos con derechos claros, CDN/transcodificación y pruebas reales de iPhone y Smart TV.

## Código y mantenimiento
- index.html, styles.css: interfaz adaptable.
- films-extra.js: únicos 3 largometrajes disponibles.
- app.js: catálogo, filtros, controles y reproductor (filtra también en runtime cualquier título menor de 60 minutos).
- manifest.webmanifest, sw.js, icon.svg: instalación PWA y caché del código, no de videos.

## Pruebas mínimas
1. Confirmar que solo aparecen 3 películas en todo el catálogo y que ninguna dura menos de 60 minutos.
2. Verificar portada Valkaama y reproducción dentro de la página.
3. Abrir Paywall y Sita; verificar audio y video en el mismo reproductor.
4. Comprobar la navegación de vuelta, favoritos, búsqueda, filtros y pantalla de error con «Reintentar acá».
5. Probar en iPhone Safari y televisor, y registrar fallos de formato o restricciones de iframe.
6. Si los reproductores externos dejan de funcionar, retirar el título del catálogo en vez de enviarlo a otra aplicación.
