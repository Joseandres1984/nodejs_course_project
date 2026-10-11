# CalculaFácil PRO — entrega privada verificada en producción

## Estado y alcance

El checkout comercial oficial está integrado con la preferencia de Mercado Pago
`59348768-483e73d1-8b3f-450c-a610-b7ce39d70da9` y producto
**CalculaFácil PRO – Kit Excel** por **AR$ 9.900**.
El enlace anterior `mpago.li/1NuWTrY` queda como referencia histórica y **no debe promocionarse**: la validación de entrega está atada a la nueva preferencia.

Este módulo implementa entrega **autogestionada** (no envío automático por
email): luego de un pago aprobado, el comprador va a \`/claim\`, informa el
correo usado para pagar y el número de operación. Un Worker consulta la API
oficial de Mercado Pago y valida todos los siguientes datos:
- pago existente con estado \`approved\`, monto exacto **ARS 9900** y fecha de aprobación;
- correo del pagador;
- titular de la cuenta autenticada por la credencial secreta;
- orden comercial vinculada al pago;
- único producto coincidente (descripción, unidad y monto);
- opcionalmente, \`EXPECTED_PREFERENCE_ID\` conocido de la preferencia original.

Solo si pasan todas las condiciones y **existe el archivo privado** se emite
un enlace de descarga firmado por 15 minutos. Una captura de pago, un redirect,
un pago pendiente o un pedido de pago NO equivalen a aprobación.

### Checklist operativo (implementado y verificado; instrucciones para recuperación)

1. Crear bucket R2 **privado** \`calculafacil-pro-private\` en la cuenta
   Cloudflare de LUMEN, sin dominio público y sin acceso anónimo.
2. Subir en R2 el archivo de entrega real
   \`CalculaFacil_PRO_Kit_v1.xlsx\` con la clave de objeto
   \`calculafacil-pro/CalculaFacil_PRO_Kit_v1.xlsx\`. **No subir el Excel a
   GitHub, al directorio público del sitio ni a un enlace público de Drive.**
3. Configurar los secrets del Worker \`MP_ACCESS_TOKEN\` (token productivo del
   mismo negocio LUMEN; no ponerlo en Git ni en el chat) y
   \`DOWNLOAD_SIGNING_KEY\` (clave aleatoria única de al menos 32 caracteres).
   \`EXPECTED_MERCHANT_ID\` y \`EXPECTED_PREFERENCE_ID\` refuerzan la validación,
   si son conocidos. Nunca reutilizar el token MP para firmar descargas.
4. Desplegar con \`wrangler deploy --config wrangler.toml\` en este directorio,
   asegurando que el Worker use los secrets y bindings declarados. Configurar
   secrets con \`wrangler secret put NAME\` en el entorno correcto.
5. Verificar \`/health\`: \`ready: true\` solo confirma configuración y objeto,
   **no autenticación efectiva ni una venta**.
6. Probar con escenarios simulados locales; antes de publicar, realizar
   al menos una compra real legítima de un tercero si se acepta la comisión
   y comprobar el pago mediante API, descarga y atención de incidencias.
   No declarar ingresos antes de un proveedor que los acredite.
7. Al completar la verificación real, enlazar el botón de compra de
   \`/pro.html\` con el checkout correspondiente e incluir instrucciones
   visibles para que el comprador pueda acceder a \`/claim\`.

### Límites importantes

- Enlace y página de producto son públicos; **archivo y credenciales son privados**.
- Se usan únicamente GET autenticados a Mercado Pago. **No se ejecutan pagos**.
- No hay notificaciones webhook, email automático ni conciliación contable
  desplegados. Sin el identificador de la operación, el usuario necesitará soporte.
- Una orden puede carecer de algunos campos, en cuyo caso se deniega la entrega y
  se debe asistir al comprador. No relajar las validaciones sin evidencia del
  formato real de respuestas de Mercado Pago.
- Usar el comprobante real y revisión de protección de datos antes del
  lanzamiento. No registrar ni compartir correos de compradores.
- No publicar checkout mientras se pueda cobrar sin una entrega probada.

## Conexión verificada de R2 (fase no comercial)

El bucket privado `calculafacil-pro-private` y el objeto
`calculafacil-pro/CalculaFacil_PRO_Kit_v1.xlsx` fueron mostrados por el titular
mediante capturas del panel de Cloudflare el 11/10/2026.

El workflow `.github/workflows/calculafacil-pro-r2-bind.yml` despliega
exclusivamente el Worker aislado de entrega y verifica que puede consultar
el objeto sin exponer ni descargar bytes, manteniendo
`FULFILLMENT_ENABLED="false"`, incluso cuando existan otros secretos.
La prueba de lectura usa solamente `head()` y espera `privateWorkbookPresent=true`
junto con `ready=false` y `enabled=false`.

**Ninguna redirección, captura de pago o comprobante habilita por sí solo la descarga.**
El Worker de producción consulta el pago y la orden a Mercado Pago, exige vendedor,
producto, preferencia y correo del pagador, y solo entonces firma una descarga de 15 min.
La prueba end-to-end con pago simulado y la descarga R2 privada fueron exitosas;
no hay un pago ni un settlement productivo de prueba. Revisar la primera venta real.

## Actualización verificada 11/10/2026: Checkout Pro de producción

- La cuenta real de vendedor LUMEN superó `GET /users/me` por API con el token secreto de Cloudflare.
- Se creó y releyó (GET de la API) una nueva preferencia de **producción**:
  `59348768-483e73d1-8b3f-450c-a610-b7ce39d70da9`.
- El único producto es `CalculaFácil PRO – Kit Excel`, cantidad 1, ARS 9.900, con URL de retorno a `/claim`.
- La preferencia está fijada como `EXPECTED_PREFERENCE_ID` en Wrangler. Esto evita que otras órdenes legítimas del mismo vendedor permitan descargar el Excel.
- El enlace anterior `mpago.li/1NuWTrY` **no debe utilizarse para el lanzamiento** porque no está demostrado que su orden sea compatible con la validación comercial de nuestro Worker.
- La prueba real en Mercado Pago Sandbox, operación de prueba confirmada por API, superó todas las verificaciones de producto, vendedor, orden, preferencia y correo.
- El R2 privado entregó correctamente 17.016 bytes de Excel con 7 hojas mediante una descarga HTTP temporal protegida y eliminada de inmediato.
- El acceso comercial sigue controlado por `FULFILLMENT_ENABLED` y `checkout_enabled`: ambos deben habilitarse solo después de validar el Worker y publicar la URL oficial de esta preferencia en el sitio.
- El comprador será redirigido desde Checkout Pro a `/claim`; el ID del pago puede venir precargado como **dato no confiable**, pero el Worker debe verificarlo ante la API de Mercado Pago junto al correo antes de permitir la descarga.

## Lanzamiento controlado

El checkout de producción se habilitó en la web pública luego de verificar:
- link oficial de Mercado Pago por API (titular, producto, importe y retornos);
- Worker privado activo (`/health` listo, R2 privado encontrado);
- bloqueo de descargas sin firma;
- pago simulado aprobado por API y vinculado a vendedor, producto, orden y preferencia;
- Excel real de 17.016 bytes descargado por HTTP privado e inspeccionado con 7 hojas.

El comprador va desde `/pro.html` al checkout y vuelve a `/claim` para introducir correo
utilizado al pagar y número de operación. La verificación es automática, **la carga
del correo y de la operación es manual**. Los pagos pendientes no liberan descargas.

No hay notificación por email ni almacenamiento público del Excel. El lanzamiento
no constituye ventas, cobros ni settlements verificados hasta tener registros de
Mercado Pago de producción. El primer cobro de un cliente real debe monitorearse
para resolver diferencias de proveedor sin relajar las validaciones.
