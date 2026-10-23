# LUMEN LeadFlow AI — MVP inmobiliarias

**Estado inicial: DEMO sin captura de datos y sin gastos de terceros.** Módulo aislado del Worker de LUMEN existente. Ningún cambio en pagos x402, Travel, Instagram ni funciones comerciales actuales.

## Incluye
- Landing responsive y simulación 100% local con datos ficticios, sin llamadas a modelos de IA ni gastos por token.
- API de salud y estado; POST /api/leads con validación, consentimiento, honeypot y límite de 10 solicitudes por hora por IP anonimizada con sal secreta.
- Persistencia solo cuando D1, secreto de administración, sal, correo de privacidad y bandera de habilitación estén correctamente configurados.
- Priorización transparente por plazo declarado: alta, media o exploratoria; **no** evaluación crediticia, no comprobación de propiedades, no agendamiento.
- Listado privado con GET /api/admin/leads y borrado individual con DELETE /api/admin/leads/:id mediante Bearer LEADFLOW_ADMIN_TOKEN.
- Webhook opcional autenticado. Estado de notificación distinguido: sent, failed, not_configured. Errores de entrega nunca se confunden con ventas.
- Limpieza programada de datos tras RETENTION_DAYS (por defecto 90), una vez configurado un cron en Wrangler.
- Tests con Node nativo sin dependencias.

## Test local
Desde leadflow-ai:
~~~
npm test
npx wrangler@4 dev
~~~
Abrir http://localhost:8787. La interfaz funciona en modo demo, pero POST /api/leads devuelve 503 deliberadamente.

## Para habilitar captación REAL (NO realizado todavía)
1. Acordar responsable del tratamiento, aviso de privacidad, contenido del consentimiento, requisitos aplicables y correo oficial. Actualizar la página antes de capturar datos reales.
2. Crear una base D1 **aislada**: npx wrangler@4 d1 create lumen-leadflow
3. Añadir el bloque [[d1_databases]] comentado de wrangler.toml con el UUID real y migrations_dir = "migrations"; no reutilizar las bases de los demás Workers.
4. Ejecutar migración primero local: npx wrangler@4 d1 migrations apply lumen-leadflow --local. Solo después de revisar: --remote en la base correcta.
5. Crear secretos separados con: npx wrangler@4 secret put LEADFLOW_ADMIN_TOKEN y secret put LEADFLOW_RATE_SALT (mínimo 32 caracteres aleatorios cada uno). Nunca guardarlos en Git.
6. Configurar PRIVACY_EMAIL en [vars] y SUBMISSIONS_ENABLED = "true". Confirmar con GET /api/status y pruebas reales autorizadas. Para avisos automáticos: secreto HTTPS NOTIFY_WEBHOOK_URL más secreto NOTIFY_WEBHOOK_TOKEN. No configurar URLs externas arbitrarias.
7. Configurar [[triggers]] crons = ["0 3 * * *"] para ejecutar eliminación diaria; sin cron, la retención **no se ejecuta automáticamente**. Las solicitudes de borrado puntuales se gestionan por el administrador.
8. Antes de lanzar públicamente: controles operativos antiabuso (WAF/Turnstile), aviso de privacidad revisado, limitación de acceso a los datos, respaldo y borrado, verificación de WhatsApp/API si se incorpora, pruebas integradas con D1 real.

## Despliegue de la demo no persistente
Desde leadflow-ai, con cuenta Cloudflare autorizada:
~~~
npx wrangler@4 deploy
~~~
El nombre es lumen-leadflow-demo y no comparte nombres ni bindings con el entorno productivo existente. Sin acceso a Cloudflare no puede considerarse desplegado; no se añadió ninguna acción automática de deploy.

## API
- GET /: demo.
- GET /client.js: script de interfaz.
- GET /health: prueba técnica.
- GET /api/status: bandera de captación sin revelar secretos.
- POST /api/leads: registro solo con consentimiento y configuración completa.
- GET /api/admin/leads: consulta privada limitada a 100 registros recientes.
- DELETE /api/admin/leads/:id: supresión individual privada.

## Métricas honestas
Solo una venta efectivamente cobrada es una venta. Una consulta almacenada es un lead, un aviso enviado es una notificación; no son cierres ni ingresos. No se hacen envíos no solicitados ni se contacta a prospectos sin autorización.
