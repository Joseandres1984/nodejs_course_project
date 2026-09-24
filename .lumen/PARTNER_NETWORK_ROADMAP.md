# LUMEN Partner Network — Roadmap oficial

Objetivo: evolucionar LUMEN desde un agente comercial autónomo hacia un orquestador económico multiagente que descubre, recluta, coordina, aprende y forma equipos dinámicos para generar ingresos.

## Principios permanentes
- El descubrimiento, análisis, conversación no vinculante, coordinación y generación de ideas pueden automatizarse.
- Gasto saliente autónomo: USD 0 salvo autorización humana explícita futura.
- Contratos, deuda, compras, hiring pago y compromisos vinculantes requieren aprobación humana.
- Nada de spam masivo: contacto gradual, relevante y con cooldown.
- Reputación basada progresivamente en resultados observados, no sólo en claims del Agent Card.
- Ingresos reales sólo cuentan cuando están verificados/settled.

## 15 puntos de evolución
1. Recruitment Engine — descubrir, calificar, contactar, conocer y convertir candidatos en partners.
2. Sala de Juntas real — conversación multiagente bajo coordinación de LUMEN.
3. Delegación de tareas — repartir trabajo concreto entre especialistas.
4. Reputación basada en hechos — respuesta, tiempo, calidad, cumplimiento, costo y resultado.
5. Venture Council — agentes proponen oportunidades, negocios, mercados y combinaciones nuevas.
6. Capability Gap Engine — detectar capacidades faltantes y salir a reclutarlas.
7. Agent Graph — mapa vivo de agentes, relaciones, capacidades y combinaciones efectivas.
8. Partner Marketplace — publicar necesidades/capacidades y permitir matching entrante.
9. Referral Network — derivación bidireccional de oportunidades con trazabilidad.
10. Economía entre agentes — micropagos y servicios máquina-a-máquina bajo guardrails.
11. Negociador — comparar propuestas, precio, calidad y condiciones antes de recomendar contratación.
12. Equipos dinámicos — formar y disolver coaliciones según cada oportunidad.
13. Redundancia y reemplazo automático — fallback al siguiente socio apto si uno falla.
14. Trust Layer fuerte — firmas, identidad, coherencia, permisos, reputación y defensa ante manipulación.
15. Torre de Control de la Red — partners, juntas, tareas, ideas, reputación, referrals, ingresos y gaps.

## Orden de construcción
Fase A: 1 → 2 → 3 → 4 → 5
Fase B: 6 → 7 → 12 → 13 → 14
Fase C: 8 → 9 → 11 → 10 → 15 (la Torre se amplía incrementalmente durante todas las fases)

## Estado actual
- Partner Discovery: operativo.
- Capability Registry: operativo.
- Council Builder / Partner Matching v1.3: operativo, no vinculante y preparado para reputación observada confidence-aware.
- Recruitment Engine v1.0.1: operativo, con primer contacto real enviado a un candidato fuerte.
- Reclutamiento autónomo continuo: desactivado hasta validar calidad de respuestas y cadencia.
- Council Runtime v1.0: operativo en fase inicial.
- Primera sala real creada: ROOM-4582354AD86443.
- AUX Evidence and Certification: contribución real recibida y Quality Gate PASS 71.
- PHION: detectado como PARTIAL_DISCOVERY_ONLY y reemplazado sin romper la sala.
- GAIP Opportunity & Procurement Broker: seleccionado como fallback, pero el runtime rechazó el formato de envío; quedó registrado como evidencia operativa.
- Packrift A2A Packaging Procurement Router: respondió por A2A, pero el Contribution Quality Gate v1.1 detectó eco de prompt + vertical fuera de foco y lo marcó REJECT 0.
- InsightBind Sales Agent: invitación enviada; por ahora sólo hay acuse técnico, sin contribución de contenido.
- Council Contribution Quality Gate v1.1: operativo.
- Quality-gated Council Synthesis: sólo sintetiza con al menos 2 contribuciones PASS.
- Council Round Manager v1.1: operativo, cooldown 6 h, timeout 12 h, máximo una invitación nueva por ciclo y Trust Gate obligatorio antes de invitar.

### #3 Delegación de tareas
- Delegation Engine v1.0: operativa como planner interno desde una sala SYNTHESIZED con al menos 2 PASS.
- Delegation Task Quality Gate v1.0: PLANNED no es despachable; sólo APPROVED_FOR_DISPATCH puede llegar al runtime.
- Delegation Runtime v1.1: instalado y con A2A_AUTONOMOUS_DELEGATION desactivado durante el piloto.
- Delegation Result Quality Gate v1.0: un resultado sólo se integra si alcanza RESULT_PASS.
- Trusted Delegation Dispatch: una tarea aprobada igualmente requiere Trust ALLOW y score >=70 antes de poder llegar al transporte.
- Cadena: SYNTHESIS → TASK PLAN → TASK QUALITY → APPROVED_FOR_DISPATCH → TRUST GATE → DISPATCH → RESULT → RESULT QUALITY → RESULT_PASS → integración.

### #4 Reputación basada en hechos
- Observed Partner Reputation v1.0: operativo desde evidencia real de runtime/juntas/delegaciones.
- Primera medición: AUX 73/confidence 18; Packrift 23/27; PHION 26/18; GAIP 26/18; InsightBind 45/9.
- Confidence <30 no altera todavía el matching. Desde confidence >=30 entra gradualmente, con peso máximo 45% de la componente reputacional.

### #5 Venture Council
- Partner Venture Board + Venture Suggestion Intake v1.1 + Venture Council v1.1: operativos.
- Una idea proveniente de una junta sólo puede ingresar si la contribución fuente fue PASS y contiene lenguaje explícito de oportunidad de negocio.
- El primer intento derivado de Packrift fue revocado automáticamente al comprobarse que su contribución fuente era REJECT 0.
- AUX PASS no había propuesto una idea comercial explícita, por lo que no se inventó ninguna.
- Los Venture Cases generan experimentos internos de costo USD 0, sin contacto externo ni compromiso vinculante.
- Venture Peer Review Gate v1.0: operativo. Cada Venture Case requiere como mínimo 2 revisiones independientes antes de activar su experimento.
- Las revisiones puntúan mercado, evidencia, ejecución, monetización y riesgo. Dos PASS con promedio suficiente producen PEER_REVIEW_PASS; un REJECT bloquea el experimento.
- El cron sólo selecciona revisores internamente; externalReviewInvites=false.
- Un experimento PLANNED sólo puede pasar a APPROVED_FOR_ZERO_COST_VALIDATION después de PEER_REVIEW_PASS.
- Smoke del Peer Review Gate: SUCCESS. Estado actual: 0 casos maduros para review; no se introdujeron ideas sintéticas sólo para poblar el pipeline.

### #6 Capability Gap Engine
- Capability Gap Engine v1.0: operativo y conectado al ciclo interno.
- Necesidades actuales alimentan automáticamente el Partner Marketplace.
- No realiza contacto de reclutamiento automático; produce una cola interna de necesidades y búsquedas sugeridas.

### #7 Agent Graph
- Agent Graph v1.0: operativo y observational-only.
- Las relaciones suben sólo con resultados conjuntos buenos y bajan con REJECT/fallas/reemplazos; ausencia de historial usa neutralidad, no confianza inventada.

### #8 Partner Marketplace
- Partner Marketplace v1.0: operativo y conectado al ciclo horario.
- Sincroniza únicamente necesidades reales OPEN/WEAK_COVERAGE del Capability Gap Engine con prioridad >=60.
- Primera sincronización real: 53 necesidades internas abiertas.
- Catálogo público v1.1 agrupa esas 53 necesidades en 6 avisos por capacidad para evitar ruido: research 16/prioridad 81; verification 9/81; pricing 8/81; sourcing 7/81; sales 12/77; tender 1/73.
- LUMEN publica además 8 capacidades propias: verification, sourcing, research, pricing, tender, sales, export y automation.
- Agentes externos pueden manifestar interés mediante Agent Card HTTPS pública; el interés entra como PENDING_TRUST y no crea contrato, pago, empleo, exclusividad ni autoridad de delegación.
- Intereses coincidentes sólo pueden llegar a MATCH_CANDIDATE después de descubrimiento/Trust Review y compatibilidad de capacidad.
- No hay contratación, contacto saliente ni pago automático desde el Marketplace.
- Smoke del Marketplace y del catálogo agregado: SUCCESS. Intereses reales actuales: 0; no se cargaron postulantes sintéticos.

### #9 Referral Network
- Referral Network v1.0: operativo y conectado al ciclo horario.
- Es bidireccional: acepta referrals INBOUND_TO_LUMEN mediante Agent Card HTTPS pública y prepara OUTBOUND_TO_PARTNER desde oportunidades comerciales reales.
- Cada referral conserva attribution_key, origen, destino, oportunidad, capacidad, Trust, match, estado y revenue settled asociado.
- Inbound pasa por PENDING_DISCOVERY → PENDING_TRUST → INBOUND_TRUSTED o BLOCKED_TRUST. No hay aceptación automática ni contacto automático.
- Outbound se crea únicamente desde oportunidades commercially_actionable/no-test con commercial score >=60, partner match >=70 y Trust ALLOW/CAUTION limpio.
- Primer candidato outbound real: SCVD Evidence Agent → Attestly / verification; commercial score 71, match 79, Trust CAUTION 60.
- Ese candidato quedó en OUTBOUND_CANDIDATE; outboundMessagesSent=0. No se envió ninguna derivación automáticamente.
- Ingresos de referral sólo pasan a SETTLED cuando existe lumen_revenue_events payment_settled + verified enlazado al referral.
- Commission status permanece NOT_CONFIGURED: la atribución se registra, pero no existe promesa ni pago automático de comisión.
- Smoke Referral Network: SUCCESS. Estado inicial: 1 outbound candidate, 0 inbound, 0 settlements, USD 0 settled referral revenue.

### #11 Negotiator
- Partner Negotiator v1.0: operativo y conectado al ciclo horario en modo recommendation-only.
- Pondera match 25%, Trust 18%, calidad/reputación 22%, reliability 10%, responsiveness 8%, precio 10% y tiempo 7%, con penalización de riesgo de hasta 30 puntos.
- Nunca inventa precio o plazo faltante. Términos provenientes de Recruitment se almacenan como DECLARED_UNVERIFIED y no se tratan como precio verificado.
- Primera corrida real: 1 caso (SCVD Evidence Agent), 12 candidatos comparados, 0 precios y 0 plazos disponibles; por eso el caso queda RANKED_INCOMPLETE_TERMS / TECHNICAL_RANKING_ONLY con confidence 39, no READY_FOR_HUMAN_REVIEW.
- Ranking técnico inicial: AUX Evidence and Certification 64; BerrerGate Tool & Provider Intelligence 60; Agent Pulse Signal Retrieval Agent 58.
- Terms Request Planner v1.0: operativo. Generó 3 borradores no vinculantes para AUX, BerrerGate y Agent Pulse solicitando precio USD/USDC, ETA, alcance/exclusiones, vigencia/constraints y evidencia de calidad.
- Los borradores permanecen DRAFT: externalMessagesSent=0; autonomousNegotiationMessages=false.
- Una comparación comercial completa requiere al menos 2 candidatos y 2 precios declarados comparables antes de pasar a READY_FOR_HUMAN_REVIEW.
- El Negotiator no contrata, no acepta términos, no paga y no envía negociación automáticamente. Cualquier hire/spend/contract sigue human-gated.
- Smoke del Negotiator + Terms Planner: SUCCESS.

### #12 Equipos dinámicos
- Dynamic Team Engine v1.1: operativo en modo internal draft only.
- Forma equipos por oportunidad usando capacidades, reputación y Agent Graph sin invitar, contratar ni gastar.

### #13 Redundancia y reemplazo automático
- Redundancy Engine v1.2: operativo.
- Mantiene hasta 2 suplentes por rol y filtra candidatos por Trust, fallas de runtime, reputación observada, compatibilidad y Agent Graph.
- Última recomputación controlada: 22 suplencias evaluadas, 19 READY, 3 WEAK y 7 agentes excluidos por Trust/Auth.
- Si una futura tarea falla o recibe RESULT_REJECTED, LUMEN puede materializar internamente una nueva tarea PLANNED para el suplente; vuelve a pasar por Delegation Task Quality Gate.
- Automatic internal task materialization: ON. Automatic external redispatch: OFF.

### #14 Trust Layer fuerte
- Trust Layer v1.0 verifica HTTPS, coherencia identidad/endpoint, protocolo, requisitos de auth, firmas JWS cuando están disponibles, seguridad de JWKS, reputación observada, fallas de runtime y señales de manipulación/exfiltración.
- Trust Policy ejecutable: Council admite ALLOW >=70 o CAUTION limpio >=50; Delegation exige ALLOW >=70.
- RESTRICTED, QUARANTINE, auth obligatoria, manipulación, protocolo no soportado o endpoint/card inseguro bloquean acciones externas.
- Agente aún no evaluado: no se envía; espera evaluación en vez de asumir confianza.
- Council Round Manager y Delegation Dispatch ya aplican la política en los puntos de salida reales.
- Smoke conjunto Redundancy + Trust: SUCCESS.

## Guardrails activos
- Gasto autónomo continúa en USD 0.
- Contratos/hiring/compras/deuda/obligaciones continúan human-gated.
- Delegación autónoma externa permanece OFF durante el piloto.
- Reputación observada no sustituye de golpe la reputación declarada: usa confianza acumulativa.
- Venture ideas derivadas de juntas heredan el Quality Gate de su contribución fuente.
- Venture Experiments requieren peer review independiente y permanecen de costo USD 0/no vinculantes durante el piloto.
- Dynamic Teams son borradores internos.
- Council invites, delegation, Marketplace matching y Referral review están Trust-gated.
- Marketplace inbound y Referral inbound son públicos pero siempre no vinculantes y no solicitan secretos/credenciales.
- Referral attribution no implica comisión; cualquier reparto futuro requiere política explícita, revenue settled verificado y guardrails de pago.
- Negotiator sólo recomienda y prepara borradores de condiciones; no envía, no acepta términos ni compromete fondos.

## Próximos hitos
- #2: obtener una segunda contribución PASS, ejecutar la primera síntesis multiagente válida y cerrar la junta piloto.
- #3: generar el primer paquete real de tareas y hacer una primera delegación controlada cuando el #2 cierre válidamente.
- #4: superar confidence 30 con evidencia real y validar el blend.
- #5: recibir la primera idea comercial explícita desde una contribución PASS, someterla a dos peer reviews y validar el primer experimento de costo cero.
- #9: recibir el primer referral inbound real o validar una derivación outbound controlada; comisión sigue NOT_CONFIGURED.
- #11: obtener al menos 2 términos/precios comparables reales, elevar un caso a READY_FOR_HUMAN_REVIEW y validar la primera recomendación comercial completa.
- #10: economía entre agentes y micropagos sólo después de validar Referral + Negotiator y manteniendo human gate para gasto.
- #15: ampliar la Torre de Control con red, marketplace, referrals, tareas, trust, reputación y revenue verificado.