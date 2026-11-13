# AURA 3D v1 — rostro modelado, sin API de pago

El visor de conversación usa un modelo **3D real** (WebGL2), con rostros GLB
femenino/masculino, parpadeo, cejas, movimiento muy leve de cabeza y dos
estrategias de sincronización de labios:

- **Voz neuronal local:** la biblioteca de código abierto analiza el audio y
  genera visemas antes de reproducirlo. El visor 3D reproduce el audio una sola vez.
- **Voz nativa de Safari:** Web Speech API no ofrece muestras de audio; un
  aproximador de fonemas españoles se reajusta cuando el navegador notifica
  límites de palabras. Es una **aproximación**, no fonemas perfectamente alineados.

Si falla WebGL2, no carga el GLB, el usuario elige la foto o prefiere no descargar
el modelo, AURA conserva la animación 2D existente. El cambio se realiza con el
botón situado sobre el rostro en la pantalla de conversación. La preferencia es
local al navegador. No se suben fotos, voz ni datos a un tercero para generar el
avatar; el cerebro conversacional conserva su configuración independiente.

## Componentes y licencias

- `@interviewflowai/talking-avatar` v0.3.0 (MIT), modelo de visemas y rostros
  Microsoft Rocketbox redistribuidos bajo MIT. Fuente:
  https://github.com/InterviewFlowAI/talking-avatar
- `three` v0.186.0 (MIT): https://github.com/mrdoob/three.js
- Artefactos autoalojados: `assets/3d/female.glb`, `male.glb` y
  `viseme-model.bin` (sin JS/CDN externo en esta integración).
- Licencias de proveedores: `assets/3d/ROCKETBOX-LICENSE.txt`,
  `assets/3d/TALKING-AVATAR-LICENSE.txt`, `assets/3d/THREE-LICENSE.txt`.

## Reconstruir el paquete de navegador

```sh
cd aura-iphone/3d-src
npm ci
npm run build
cd ..
node --test *.test.mjs
```

El resultado `aura-3d.bundle.js` se versiona, porque Render sirve los archivos
directamente y no ejecuta una compilación de frontend al iniciar. Si cambia el
bundle, actualizar también su parámetro de versión en `server.mjs`.

## Limitaciones claras

- Estos son modelos 3D humanos de prueba, **no el mismo rostro fotográfico** de
  AURA 2D. Para preservar idéntica identidad hará falta crear un GLB propio con
  texturas y morfos faciales, y validarlo visualmente antes de reemplazarlo.
- La voz de Safari tiene sincronización estimada. Para audio con sincronización
  labial acústica el usuario debe activar la voz neuronal; su primera descarga
  puede consumir cientos de megabytes y demorar en el iPhone.
- iPhone/Safari reales requieren comprobación manual de rendimiento,
  micrófono, audio desbloqueado y uso de batería.
