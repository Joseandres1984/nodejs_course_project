# CalculaFácil PRO — pago de prueba aislado

**Nunca usar el link real de cobro mpago.li/1NuWTrY para probar.**
Este Worker es independiente de `calculafacil-pro-fulfillment` y no tiene enlace a R2.

## Seguridad

- Vendedor de prueba de Argentina previamente identificado en capturas del panel (ID registrado en `wrangler.toml`).
- Comprador de prueba de Argentina: iniciar sesión exclusivamente en el checkout de PRUEBA desde un navegador privado.
- Las contraseñas y los códigos de prueba aparecieron en capturas: regenerar contraseñas antes de iniciar sesión. **Nunca copiarlos a GitHub, ChatGPT o Cloudflare**.
- **Token test distinto:** `MP_TEST_ACCESS_TOKEN` debe configurarse como **Secret** directamente en Cloudflare Workers → `calculafacil-pro-sandbox` → Settings → Variables and Secrets. Debe corresponder al vendedor de prueba correcto. Mantener `MP_ACCESS_TOKEN` productivo sólo en el Worker de producción.
- Se requiere otra clave secreta `SANDBOX_ADMIN_KEY` de al menos 48 caracteres aleatorios para permitir que GitHub Actions administre una preferencia de prueba sin abrirla públicamente.
- `SANDBOX_ENABLED=false` por defecto. La creación no se habilita antes de verificar tokens y administración. No habilitar en el sitio público.
- Rutas privadas: `POST /admin/create-preference` crea solamente preferencia Mercado Pago, no transacción; `POST /admin/check-payment` valida sólo una operación del vendedor de prueba. Retorna resumen anonimizado; no entrega Excel.
- `GET /health` revela sólo estado técnico, no identidad ni secretos.

## Recorrido de prueba

1. Desplegar Worker separado y confirmar `/health` test_only, `ready=false`.
2. Configurar token **de pruebas** y clave de administración de forma segura.
3. Verificar `GET /users/me` y exigir ID exacto del vendedor test antes de crear preferencia.
4. Activar **solo SANDBOX_ENABLED** del sandbox, nunca `FULFILLMENT_ENABLED` de producción.
5. Con administración autenticada crear preferencia por ARS 9900 marcada `PRUEBA`.
6. Iniciar sesión como comprador de prueba y pagar únicamente usando saldo o tarjeta ficticia; **no se aceptan tarjetas ni dinero reales**.
7. Confirmar ID de pago aprobado vía API con el token test; identificar cualquier diferencia de payload para corregir validaciones. Los mocks no cuentan como venta.
8. Mantener bloqueada la venta productiva hasta validar luego el recorrido real y la atención a fallos.

Referencias oficiales:
- https://www.mercadopago.com.ar/developers/es/docs/checkout-pro-preferences/test-accounts
- https://www.mercadopago.com.ar/developers/es/docs/checkout-pro-preferences/integration-test/introduction
- https://www.mercadopago.com.ar/developers/es/reference/online-payments/checkout-pro-preferences/create-preference/post

Ninguna prueba ficticia constituye settlement ni ingreso comercial.
