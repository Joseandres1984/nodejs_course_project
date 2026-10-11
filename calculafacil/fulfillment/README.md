# CalculaFácil PRO — entrega privada (NO desplegada)

## Estado y alcance

La pantalla de Mercado Pago presentada por el vendedor muestra "LUMEN",
"CalculaFácil PRO – Kit Excel" y **AR$ 9.900**. El link aportado es
https://mpago.li/1NuWTrY (checkout real; **nunca comprar para probar**).

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

### Pendientes de infraestructura (no configurados)

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

**Ninguna operación GET, comprobante ni página de cobro habilita por sí sola
la venta ni la entrega.** Falta configurar las credenciales privadas y validar
al menos un caso real antes de cambiar el interruptor explícito.
