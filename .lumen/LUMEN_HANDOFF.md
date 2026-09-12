# LUMEN B2B — Estado persistente del proyecto

Última actualización: 2026-09-12

## Visión
LUMEN es un sistema autónomo de interlocución B2B. Su función principal es detectar necesidades empresariales, identificar y validar compradores/proveedores, actuar como puente comercial profesional, organizar requerimientos, solicitar/comparar ofertas, preparar propuestas, negociar dentro de límites y acompañar la operación hasta el cierre, preservando margen, reputación y relaciones de largo plazo.

Bucle operativo:
OBSERVE → DETECT → PRIORITIZE → PLAN → EXECUTE → NEGOTIATE → VERIFY → LEARN → REPLAN → SEEK NEXT OPPORTUNITY

Pregunta rectora:
“¿Cuál es la mejor acción segura que puedo realizar ahora para aumentar el valor económico del negocio?”

## Principios de autonomía
- Máxima autonomía en investigación, clasificación, priorización, seguimiento, comunicación comercial y negociación no vinculante.
- No comprometer dinero, firmar contratos, aceptar deuda ni asumir obligaciones legales sin aprobación humana.
- No inventar cantidades, plazos, presupuestos, stock, moneda ni condiciones.
- Toda acción importante debe tener evidencia, trazabilidad, riesgo y motivo económico.
- Priorizar relaciones sostenibles: rentabilidad + recurrencia + reputación + calidad de vínculo.

## Arquitectura productiva
Flujo actual:
Executive Director → Scout → Lead Intelligence → Company Verification → Contact Intelligence → Market Pipeline → Interlocutor Engine → Inbox → Quote Engine → Autopilot → Pre-Close Gate → Relationship Memory → Scorecards → Communication Director → Quality Gate → Email

Capas principales:
- Executive Director: decide el cuello de botella empresarial prioritario en cada ciclo.
- Scout: búsqueda real en Serper, Argentina/español, con presupuesto diario y estrategia dinámica buyer/supplier gap.
- Lead Intelligence: scoring A/B/C/D, ruido, duplicados, relevancia B2B.
- Company Verification: mini due diligence sobre dominio oficial con protección SSRF.
- Contact Intelligence: sólo canales corporativos públicos del dominio oficial; no infiere correos personales.
- Market Opportunity Builder: cruza comprador verificado + demanda verificada + proveedor verificado; no inventa valor económico.
- Interlocutor Engine: crea/gestiona casos comerciales, separa hechos de supuestos y exige requerimientos completos antes de RFQ seria.
- Quote Engine: normaliza ofertas antes de comparar; no elige sólo por precio.
- Pre-Close Gate: checklist legal/comercial/fiscal/operativo antes de considerar listo un cierre.
- Relationship Memory: historial comercial por empresa, seguimientos, cooldown y opt-outs.
- Counterparty Scorecards: calidad objetiva de contrapartes.
- Communication Director: tono amable, profesional, claro, breve, humano, no manipulativo.
- Quality Gate: barrera obligatoria antes de correo real.
- Autonomy Governor + Decision Ledger: autoridad, riesgos y trazabilidad de decisiones.

## Política comercial
Defaults:
- participación mínima de LUMEN: 8%
- objetivo: 12%
- reserva de riesgo: 2%
- no cerrar por debajo del mínimo aprobado

## Estado técnico verificado
Proyecto Railway: lumen-b2b
Project ID: 7fdff586-1905-4c3e-849c-7381eef9f474
Production env: 20b71a31-c9f7-4943-b29a-ecea4dc0e17d
Worker: lumen-worker / 7d8f2f46-c9ca-4b98-9d3a-a333d0b78dc5
Web: lumen-web / 08e1d289-46b2-4d04-9ed0-43edca959288
Postgres: 8e8c0443-53e7-49ae-ab62-da77d0ab1d98
Branch productiva: lumen-deploy
Runtime root: .lumen/runtime
Worker start: python worker.py
Cron estable: */15 * * * *

Último commit funcional principal desplegado: 6b9dfe85f1b97c935313c0430d25c71a51a4f9a8

Última corrida completa validada:
- research leads: 22
- candidate accounts: 7
- verified companies: 2
- verified suppliers: 2
- verified buyers: 0
- verified corporate channels: 1
- verified corporate emails: 1
- evidence-backed opportunities: 0
- interlocution cases: 0
- real outbound sent: 0
- Scout errors: 0
- Postgres connected/persisting
- Gmail SMTP/IMAP configured
- decision ledger: 42 entries
- executive bottleneck: buyer_gap

Scout decidió correctamente usar 2/2 búsquedas para compradores cuando existían 2 proveedores verificados y 0 compradores verificados.

## Reglas de comunicación
- amable, profesional, breve y humano
- pedir, no exigir
- explicar contexto y pedido concreto
- agradecer el tiempo
- sin urgencia artificial ni presión manipulativa
- sin promesas no verificadas
- respetar opt-out inmediatamente
- máximo 2 seguimientos sin respuesta, con cooldown por defecto de 4 días

## Seguridad y calidad
- protección SSRF y validación de redirecciones
- límites de páginas/bytes/tiempos en investigación
- sólo canales corporativos públicos
- Quality Gate obligatorio antes del envío
- Mail Connector se niega a enviar si quality_gate != passed
- salida real de emails permanece apagada durante validación

## Pendientes prioritarios
1. Rotar la contraseña de aplicación de Gmail que apareció visible en una captura anterior; nunca pegar secretos en chat.
2. Limpiar en lumen-web las dos variables antiguas malformadas con espacios antes del nombre.
3. Mejorar identidad fiscal/legal de contrapartes.
4. Gestión documental y trazabilidad formal de ofertas/cotizaciones.
5. Dashboard ejecutivo completo con funnel, decisiones, prioridades, empresas y márgenes.
6. Validar compradores reales y señales públicas de demanda.
7. Prueba controlada de email únicamente a una cuenta propia antes de habilitar outreach real.
8. Recién después, habilitar outreach gradual y con límites bajos.

## Regla operativa para retomar
Al volver, continuar desde buyer_gap. No crear más proveedores hasta justificarlo por el Executive Director. Priorizar compradores, validar demanda, verificar contacto corporativo, construir primer caso de interlocución y mantener outbound real apagado hasta completar la prueba controlada y rotar credenciales.
