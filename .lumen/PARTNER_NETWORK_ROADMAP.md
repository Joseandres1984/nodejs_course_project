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
- Council Round Manager v1.0: operativo, con cooldown 6 h, timeout 12 h y máximo una invitación nueva por ciclo.

### #3 Delegación de tareas
- Delegation Engine v1.0: operativa como planner interno desde una sala SYNTHESIZED con al menos 2 PASS.
- Delegation Task Quality Gate v1.0: PLANNED no es despachable; sólo APPROVED_FOR_DISPATCH puede llegar al runtime.
- Delegation Runtime v1.1: instalado y con A2A_AUTONOMOUS_DELEGATION desactivado durante el piloto.
- Delegation Result Quality Gate v1.0: un resultado sólo se integra si alcanza RESULT_PASS.
- Cadena: SYNTHESIS → TASK PLAN → TASK QUALITY → APPROVED_FOR_DISPATCH → DISPATCH → RESULT → RESULT QUALITY → RESULT_PASS → integración.

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
- El cron sólo selecciona revisores internamente; externalReviewInvites=false. Ningún agente es contactado automáticamente por el peer review.
- Un experimento PLANNED sólo puede pasar a APPROVED_FOR_ZERO_COST_VALIDATION después de PEER_REVIEW_PASS.
- Smoke del Peer Review Gate: SUCCESS. Estado actual: 0 casos maduros para review; no se introdujeron ideas sintéticas sólo para poblar el pipeline.

### #6 Capability Gap Engine
- Capability Gap Engine v1.0: operativo y conectado al ciclo interno.
- Primera recomputación real: 48 necesidades evaluadas; OPEN 0; WEAK_COVERAGE 48; COVERED 0; prioridad máxima 81.
- Interpretación: existen candidatos declarados para todas las capacidades actuales, pero todavía ninguno tiene suficiente evidencia observada/confianza para considerar la capacidad sólidamente cubierta.
- No realiza contacto de reclutamiento automático; produce una cola interna de necesidades y búsquedas sugeridas.

### #7 Agent Graph
- Agent Graph v1.0: operativo y observational-only.
- Primera red: 32 nodos, 15 relaciones observadas, 0 combinaciones todavía probadas como positivas, 12 combinaciones riesgosas y mejor afinidad 53.
- Las relaciones suben sólo con resultados conjuntos buenos y bajan con REJECT/fallas/reemplazos; ausencia de historial usa neutralidad, no confianza inventada.

### #12 Equipos dinámicos
- Dynamic Team Engine v1.1: operativo en modo internal draft only.
- Primera corrida: 4 oportunidades evaluadas y 4 equipos construidos; 2 agentes con fallas de runtime fueron excluidos automáticamente.
- SCVD: BerrerGate/verificación + AUX/sourcing + Agent Pulse/research; team score 84, cobertura 100%, graph affinity 51.
- Mejor team score de la corrida: 86; afinidad promedio 51.
- No envía invitaciones, no contrata y no gasta: externalInvitesSent=false, autonomousHiring=false, autonomousSpend=false.

## Guardrails activos
- Gasto autónomo continúa en USD 0.
- Contratos/hiring/compras/deuda/obligaciones continúan human-gated.
- Delegación autónoma externa permanece OFF durante el piloto.
- Reputación observada no sustituye de golpe la reputación declarada: usa confianza acumulativa.
- Venture ideas derivadas de juntas heredan el Quality Gate de su contribución fuente.
- Venture Experiments requieren peer review independiente y permanecen de costo USD 0/no vinculantes durante el piloto.
- Dynamic Teams son borradores internos hasta validar redundancia y Trust Layer.

## Próximos hitos
- #2: obtener una segunda contribución PASS, ejecutar la primera síntesis multiagente válida y cerrar la junta piloto.
- #3: generar el primer paquete real de tareas y hacer una primera delegación controlada cuando el #2 cierre válidamente.
- #4: superar confidence 30 con evidencia real y validar el blend.
- #5: recibir la primera idea comercial explícita desde una contribución PASS, someterla a dos peer reviews y validar el primer experimento de costo cero.
- #13: crear banco de suplentes y reemplazo interno por rol/tarea ante fallas.
- #14: fortalecer identidad, coherencia, permisos y defensa ante agentes maliciosos o manipuladores.
