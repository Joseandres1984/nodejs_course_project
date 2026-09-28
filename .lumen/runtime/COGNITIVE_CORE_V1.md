# LUMEN Cognitive Core v1

Cognitive Core v1 is the supervisory reasoning layer above LUMEN's existing Autonomy Core, commercial engines and learning modules.

## Runtime loop

`observe -> reason -> map to governed action -> constitutional check -> shadow/advisory/active execution -> persist compact memory`

The core does not replace the existing Market Hunter, Director, Economic Operator or execution modules. It gives them a shared decision context and a single constitutional gate.

## Default behavior

- `LUMEN_COGNITIVE_CORE_V1_ENABLED=true` by default.
- `LUMEN_COGNITIVE_CORE_V1_MODE=shadow` by default.
- `LUMEN_COGNITIVE_CORE_V1_EVERY_N_TICKS=3` by default.
- `LUMEN_COGNITIVE_WORKER_URL` optionally points to the existing `lumen-zero-cognitive` worker. If unavailable, the core falls back to a deterministic funnel-first policy and the worker continues normally.

Shadow mode stores recommendations and summaries but never executes tools.

## Modes

- `shadow`: reason, validate and remember. Execute nothing.
- `advisory`: same execution authority as shadow; intended for dashboards/review flows.
- `active`: execution is possible only through an explicitly registered tool and only if `operating_constitution.constitutional_check()` allows it.

There is no wildcard tool execution. Unknown actions default to human-required handling.

## Constitutional safety

The current operating constitution remains authoritative. Payments, financial commitments, orders, contracts and binding terms remain `human_required`. Kill switches are checked again after model reasoning. The Cognitive Core cannot widen authority.

Model context is secret-redacted before transport. The system stores concise rationale summaries rather than private chain-of-thought.

## Memory

Each cognitive cycle writes a compact `cognitive_core_v1` result plus a capped `cognitive_core_history` of the latest 40 decisions. This memory contains decision summaries, authority, confidence, expected value and execution outcome.

## Rollout

1. Merge with default `shadow` mode.
2. Observe decisions against real cycles and verified revenue truth.
3. Connect the existing Cognitive Worker URL if the runtime does not already expose it.
4. Register only reversible, constitutionally autonomous tools.
5. Promote individual tool classes to `active` after measured shadow accuracy; never globally bypass human-required actions.

## Tests

`python -m unittest -v test_cognitive_core_v1.py`

The safety suite verifies shadow non-execution, payment blocking, kill-switch enforcement, model-failure fallback, secret redaction and bounded active execution.
