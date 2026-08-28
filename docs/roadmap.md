# RecoverAI — Roadmap

Each phase ends with a STOP checkpoint. We do not proceed to the next phase
until the current one is understood and working.

## Phase 0 — System Design (this phase)
Architecture, problem statement, data flow, roadmap. No code.

## Phase 1 — Project Setup
Python virtual environments, FastAPI basics, project structure, config,
environment variables, database basics. Minimal scaffold only.

## Phase 2 — Merchant & Transaction Simulator
Synthetic data generation, probability distributions, event simulation,
state transitions. Start at 1,000 transactions, make it configurable.

## Phase 3 — Event System
Event-driven architecture: event types, producers, consumers, state
transitions. Define the core event vocabulary (PAYMENT_CREATED,
PAYMENT_FAILED, CHECKOUT_ABANDONED, RECOVERY_ATTEMPTED, etc).

## Phase 4 — Revenue Risk Engine
What "revenue at risk" means, rule-based detection, feature engineering,
scoring. Fully deterministic — no LLM yet.

## Phase 5 — ML Recovery Prediction
Supervised learning, train/test split, leakage, precision/recall/F1/ROC-AUC,
confusion matrix. Predicts "will this revenue opportunity be recoverable?"
Evaluated honestly on held-out data.

## Phase 6 — Recovery Strategy Engine
Decision systems, expected value, cost-sensitive decisions. Strategies:
retry, delayed_retry, alternate_payment, incentive, reminder, escalation,
stop.

## Phase 7 — Agent Layer (LLM introduced here, not before)
LLM agents, tool calling, structured outputs, why the LLM must not directly
control financial state. Agent emits a structured decision; tools execute.

## Phase 8 — Policy / Guardrail Engine
Authorization, deterministic safety, separation of reasoning and execution.
Explicit test cases: allowed retry, retry limit exceeded, high-value
transaction, too many interventions, excessive discount, opt-out, invalid
action.

## Phase 9 — Closed-Loop Agent
Wire Phases 2–8 into the full detect → diagnose → predict → decide → policy
→ act → observe → measure loop, running autonomously over simulated events.

## Phase 10 — Audit Trail
Structured audit records for every decision. APIs: /transactions,
/recovery-events, /agent-decisions, /audit-log, /metrics.

## Phase 11 — Dashboard
Revenue processed / at risk / recovered, recovery rate, funnel chart,
recovery over time, failure reasons, recovery by strategy/payment method,
agent decisions, policy violations. Transaction detail view with full
decision timeline.

## Phase 12 — Experimentation
Compare No-intervention / Rule-based / ML / Agent strategies on equivalent
simulated populations with fixed seeds. Report recovery rate, recovered
revenue, intervention cost, false interventions, escalation rate, average
recovery time.

## Phase 13 — Scale the Simulator
1,000 → 10,000 → 100,000 transactions. Performance, batching, indexing,
caching, async processing. Measure runtime and throughput.

## Phase 14 — Razorpay Test-Mode Integration (optional, only after Phase 13)
Investigate current Razorpay test-mode APIs, integrate only what is
verified against real documentation. Simulator remains the primary,
reproducible environment.

## Phase 15 — Failure Demonstration
Deliberately show the system failing gracefully: retry denied by policy,
retry attempted and failing, retry limit reached, escalation triggered.

---

## Research questions to keep in view throughout
- RQ1: Can an agent recover more revenue than static recovery policies?
- RQ2: Can recovery strategies be selected by expected monetary value?
- RQ3: How does customer history affect recovery decisions?
- RQ4: How much does an agent reduce unnecessary interventions?
- RQ5: How much revenue is recovered per unit of intervention cost?
- RQ6: How does performance change as transaction volume increases?

## Evaluation discipline
- Fixed random seeds when comparing strategies.
- Equivalent simulated populations across strategies.
- Real train/validation/held-out test splits for ML.
- Report honestly if the agent underperforms a baseline — do not adjust the
  simulator to flatter the AI.
