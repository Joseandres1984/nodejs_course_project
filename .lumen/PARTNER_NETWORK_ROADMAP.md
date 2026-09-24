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
- Partner Venture Board: operativo.
- Recruitment Engine v1.0.1: operativo, con primer contacto real enviado a un candidato fuerte.
- Reclutamiento autónomo continuo: desactivado hasta validar calidad de respuestas y cadencia.
- Council Runtime v1.0: operativo en fase inicial.
- Primera sala real creada: ROOM-4582354AD86443.
- AUX Evidence and Certification: contribución real recibida y Quality Gate PASS 71.
- PHION: detectado como PARTIAL_DISCOVERY_ONLY y reemplazado sin romper la sala.
- GAIP Opportunity & Procurement Broker: seleccionado como fallback, pero el runtime rechazó el formato de envío; quedó registrado como evidencia operativa.
- Packrift A2A Packaging Procurement Router: respondió por A2A y llevó la sala a DELIBERATING, pero el Contribution Quality Gate v1.1 detectó eco de prompt + vertical fuera de foco y lo marcó REJECT 0.
- Reemplazo por baja calidad: operativo. Packrift fue sustituido por InsightBind Sales Agent sin perder el contexto de la junta.
- InsightBind Sales Agent: invitación enviada; por ahora sólo hay acuse técnico, sin contribución de contenido.
- Council Contribution Quality Gate v1.1: operativo. Evalúa pertinencia, especialidad, evidencia, acción, interacción con pares, eco de prompt y desvío vertical.
- Quality-gated Council Synthesis: operativo. Una junta sólo puede sintetizarse con al menos 2 contribuciones PASS.
- Prueba de síntesis: correctamente bloqueada con 1 PASS disponible; LUMEN no fabrica consenso.
- Council Round Manager v1.0: operativo y verificado en producción.
- Invitaciones de junta autónomas guardadas: activadas, máximo una nueva invitación por ciclo, cooldown de 6 horas y timeout de respuesta de 12 horas.
- Si un agente no aporta dentro del timeout, LUMEN lo reemplaza por el siguiente candidato apto; si una contribución es REJECT, puede reemplazarla por baja calidad.
- Si la junta alcanza 2 aportes PASS, el Round Manager puede ejecutar la síntesis quality-gated sin generar nuevas invitaciones.
- Si una invitación de junta sale en un ciclo, ese ciclo no envía además un outreach comercial nuevo: una sola acción externa saliente desde este flujo por ciclo.

### #3 Delegación de tareas
- Delegation Engine v1.0: instalada y operativa en modo planner interno.
- Sólo puede generar tareas desde una sala SYNTHESIZED con al menos 2 contribuciones PASS.
- Cada tarea incluye rol, objetivo, entregable esperado, exigencia de evidencia y guardrails de no gasto/no contrato.
- Delegation Task Quality Gate v1.0: operativo. PLANNED no es despachable; sólo APPROVED_FOR_DISPATCH puede llegar al runtime.
- Delegation Runtime v1.1: instalado. Puede despachar y seguir tareas A2A no vinculantes y de gasto cero, pero A2A_AUTONOMOUS_DELEGATION permanece desactivado durante el piloto.
- Delegation Result Quality Gate v1.0: operativo. Un resultado recibido no se integra automáticamente; debe alcanzar RESULT_PASS.
- Cadena preparada: SYNTHESIS → TASK PLAN → TASK QUALITY → APPROVED_FOR_DISPATCH → DISPATCH → RESULT → RESULT QUALITY → RESULT_PASS → integración.
- Smoke de seguridad del #3: SUCCESS. Sala DELIBERATING bloqueada correctamente, 0 tareas creadas, task gate exige APPROVED_FOR_DISPATCH, result gate exige RESULT_PASS y dispatch continúa autonomous_delegation_disabled.

### #4 Reputación basada en hechos
- Observed Partner Reputation v1.0: operativo y recomputado desde evidencia real de runtime/juntas/delegaciones.
- Mantiene separada la reputación declarada del Agent Card de la reputación observada por LUMEN.
- Primera medición: 32 partners registrados y 5 con evidencia operativa real.
- AUX: observed 73 / confidence 18.
- Packrift: observed 23 / confidence 27.
- PHION: observed 26 / confidence 18.
- GAIP: observed 26 / confidence 18.
- InsightBind: observed 45 / confidence 9 mientras espera respuesta de contenido.
- Todavía ningún partner alcanza confidence 30, por lo que la reputación observada NO modifica aún las selecciones.
- Partner Matching v1.3 aplica un blend conservador sólo desde confidence >= 30 y limita el peso observado a un máximo del 45% de la componente reputacional.
- Esto permite que la experiencia real gane peso gradualmente sin sobreajustar por uno o dos eventos.

## Guardrails activos
- Gasto autónomo continúa en USD 0.
- Contratos/hiring/compras/deuda/obligaciones continúan human-gated.
- Delegación autónoma externa permanece OFF durante el piloto.
- Reputación observada no sustituye de golpe la reputación declarada: usa confianza acumulativa.

## Próximos hitos
- #2: obtener una segunda contribución PASS, ejecutar la primera síntesis multiagente válida y cerrar la junta piloto.
- #3: generar automáticamente el primer paquete real de tareas, pasarlo por Task Quality Gate y hacer una primera delegación controlada.
- #4: acumular evidencia hasta superar confidence 30 en partners reales y validar que el blend mejore la selección.
- #5: profundizar Venture Council para convertir ideas de agentes en oportunidades investigables y puntuadas.
