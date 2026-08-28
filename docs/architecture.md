# RecoverAI — Architecture

## 1. Objective

RecoverAI is a simulation-first, agentic revenue recovery controller. It detects
revenue at risk in a synthetic merchant ecosystem, diagnoses why the risk exists,
decides on a bounded intervention, checks that intervention against explicit
policy, executes it in a simulated environment, measures whether money was
actually recovered, and records a full audit trail for every decision.

The system deliberately does **not** start with real payment infrastructure.
It starts as a closed, reproducible simulation so that recovery strategies can
be compared fairly (same population, same random seed, different strategy).

## 2. Problem Statement

Merchants lose revenue through many small, individually-recoverable leaks:
transient payment failures, checkout abandonment, failed subscription renewals,
and overdue invoices. Blanket recovery ("retry everything", "discount everyone")
is expensive and sometimes against policy. The problem is to recover revenue
that is *actually recoverable*, using actions that are *actually permitted*,
in a way that is *provably effective* — not just reported as effective.

## 3. Core Principle

Detection is not the deliverable. The deliverable is the full chain:

```
Detect risk → Diagnose cause → Decide on action → Check policy
   → Execute (bounded) → Observe outcome → Measure → Audit
```

If any link is missing, the system is a reporting tool, not a controller.

## 4. High-Level Architecture

```
                    ┌─────────────────────┐
                    │ Merchant Simulator  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Event Stream / Bus  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Revenue Risk Engine │  (deterministic)
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Diagnosis Engine    │  (rules + ML)
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Recovery Agent      │  (ML → later LLM)
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Policy / Guardrails │  (deterministic, authoritative)
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Action Executor     │  (simulated, later Razorpay test-mode)
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Outcome Evaluator   │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
             Metrics Engine          Audit Log
                    │
                    ▼
               Dashboard
```

### Design principles

1. **Not every component is an LLM.**
   - Risk scoring: deterministic formula.
   - Recovery-likelihood prediction: classical ML (logistic regression /
     random forest first).
   - Action *selection under ambiguous context*: this is the one place an
     LLM adds real value, introduced only in Phase 7.

2. **Separation of reasoning, authority, and execution.**
   The agent (ML or LLM) only *proposes* a structured decision. The Policy
   Engine is the only component with authority to ALLOW / DENY / ESCALATE.
   The Action Executor is the only component that mutates simulated
   financial state. The agent can never bypass the policy engine.

3. **Every state change emits an event and an audit record.**
   This is what makes the "click a transaction, see its full decision
   timeline" dashboard feature possible without extra plumbing later.

4. **Simulation stays authoritative even after Razorpay integration (Phase 14).**
   Only the execution step of a bounded action may eventually call a real
   test-mode API. Risk detection, diagnosis, decisioning, and policy continue
   to run against our own simulated state so experiments remain reproducible.

## 5. What stays simulated permanently

- Customers' true underlying payment behavior / reliability.
- The "would this have recovered anyway without intervention" counterfactual
  (ground truth needed to fairly evaluate strategies).
- Provider degradation events (used to test whether the agent adapts).

There is no safe or practical way to obtain this ground truth from a real
system without live A/B testing on real money, which is out of scope here.

## 6. What may eventually connect to real Razorpay test-mode (Phase 14 only)

Only the **execution of a specific bounded action** (e.g., firing a real
test-mode retry). This happens only after the fully simulated closed loop
works, and only using verified, current Razorpay documentation — no
fabricated API behavior.

## 7. Example data flow

```
10:01  Simulator: payment attempt for txn_8492 fails (provider timeout)
10:01  Event bus: PAYMENT_FAILED emitted
10:01  Risk Engine: risk_score = fail_prob × amount × recover_prob
10:02  Diagnosis Engine: classifies as "transient_failure"
10:02  Recovery Agent: recommends retry_payment
10:02  Policy Engine: retry_count < MAX_RETRIES, amount < threshold → ALLOW
10:02  Action Executor: schedules retry at 16:02
16:02  Action Executor: executes retry → outcome: success
16:02  Outcome Evaluator: txn_8492 marked RECOVERED, amount_recovered = ₹4,999
16:02  Audit Log: full structured record written
16:02  Metrics Engine: revenue_recovered and recovery_count incremented
```

## 8. Technology choices (initial, may evolve)

- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, SQLite → Postgres later.
- **Simulation:** Python, Pandas, NumPy, Faker, custom event simulator.
- **ML:** Logistic Regression / Random Forest first; XGBoost/LightGBM only if
  genuinely justified by results. No deep learning unless a concrete need
  emerges.
- **Agent:** LLM API with structured outputs / function calling, introduced
  only in Phase 7. Never given direct write access to financial state.
- **Frontend:** React + TypeScript + a simple charting library (or a lighter
  frontend first if that speeds up early iteration).

## 9. Explicit non-goals for early phases

- No Kubernetes, no microservices, no Kafka/Redis until an actual need for
  them is demonstrated by the system's requirements.
- No hardcoded "impressive" metrics — every number in the final dashboard
  must be produced by the simulator and pipeline, not typed in.
- No hiding of failure cases — the system must be able to show retries that
  fail, policies that block actions, and escalations that occur.
