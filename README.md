# RecoverAI

**An autonomous revenue recovery controller.** Built for the Razorpay Buildathon (Track 3: AI Revenue Recovery).

RecoverAI detects failed payments, diagnoses why each one failed, decides on a bounded recovery
action, checks that decision against a deterministic policy engine neither the strategy engine
nor an LLM agent can bypass, executes it, and records the full explainable trail - end to end,
autonomously. Everything in the dashboard is live and interactive: click a button, watch the real
pipeline run, see real numbers.

**One URL. No setup required to demo.** The app auto-generates a realistic simulated merchant on
first load, so a judge opening the deployed URL sees a populated, working system immediately.

---

## The pipeline

```
Detect  ->  Diagnose  ->  Decide  ->  Authorize  ->  Act  ->  Audit
 (sim)      (risk         (EV           (policy       (only if   (every step
             engine)       strategy      engine:       allowed)    recorded,
                           or LLM        ALLOW/                     explainable)
                           agent)        DENY/
                                         ESCALATE)
```

A failed payment is never acted on directly - every proposed action passes through a deterministic
policy engine first. The strategy engine and the LLM agent both *propose*; only the policy engine
*authorizes*.

---

## What's actually in this project

### Core pipeline
- **Simulator** - synthetic merchant, customers (6 behavioral types), and transactions with realistic failure/recovery ground truth
- **Event-driven architecture** - an in-process pub/sub bus wires detection to diagnosis to decision to execution
- **Deterministic risk engine** - `risk_score = failure_probability x amount x recovery_probability`, blending payment-method and customer-level historical rates
- **ML recovery model** - logistic regression, 5-fold cross-validated, evaluated *honestly* against a rule-based baseline (the rule-based fallback sometimes wins - reported as-is, not hidden)
- **Expected-value strategy engine** - 7 candidate actions compared by EV; `STOP` is always available at exactly Rs.0, a structural guarantee against a money-losing recommendation
- **LLM agent (Groq)** - tool-calling agent invoked only for genuinely ambiguous cases; never in the bulk automatic pipeline (cost/latency), but callable on demand from the dashboard
- **Deterministic policy engine** - 8 independent guardrail checks (opt-out, retry limits, discount limits, intervention frequency, high-value thresholds, and more), combined with strict `DENY > ESCALATE > ALLOW` precedence
- **Real Razorpay integration** - genuine test-mode Payment Links API calls (not mocked), restricted to customer-facing strategies

### Interactive dashboard features
- **Live Control Panel** - run a fresh simulation, train the ML model, run a fair strategy comparison, or trigger the failure-demonstration suite, all from the browser
- **Escalation Queue** - every case the policy engine flagged for human review, with real **Approve** (executes the recovery) / **Deny** (does not) buttons - the human-in-the-loop interface that was missing before
- **Chaos Mode** - simulates a real payment provider outage on one method, then shows the honest before/during shift in failure rate, recovery rate, and how often the policy guardrails engaged - entirely emergent from observed data, never a hardcoded flag
- **Try Your Own Scenario** - type in an amount, payment method, and customer profile; watch the full pipeline reason about it live, optionally consulting the real Groq agent and showing its tool-call trace
- **Customer Explorer** - browse and search customers ranked by failure rate, recovery rate, or volume; drill into any customer's full transaction history
- **Search** - find transactions by ID, payment method, or customer name; find customers by name
- **Fair experimentation** - every strategy condition compared against the same transaction using the same random seed, so differences reflect real decision quality, not luck

### Honest engineering findings (not hidden)
- The trained ML model does not reliably beat the rule-based fallback - this is reported plainly, live, every time you click "Train recovery model," not smoothed over
- A fixed set of database indexes, batched commits, and SQL-side aggregation produced a measured **7x speedup** and near-linear scaling past 20,000 transactions
- The experimentation harness explicitly documents which guardrails are and aren't active in its scope

---

## Tech stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy + SQLite, scikit-learn, Groq API, Razorpay Python SDK
- **Frontend**: a single self-contained HTML file - vanilla JS, Chart.js (CDN), no build step, no framework
- **Tests**: pytest, 74 tests covering every phase of the pipeline

---

## Project structure

```
recover-ai/
|-- backend/
|   |-- app/
|   |   |-- main.py                 # FastAPI app, startup auto-seed, serves the dashboard
|   |   |-- config.py               # Settings, computed absolute DB path
|   |   |-- database.py
|   |   |-- models/                 # SQLAlchemy models + enums
|   |   |-- simulator/              # Ground truth, generator, Chaos Mode
|   |   |-- events/                 # Event bus + consumers (the closed loop's wiring)
|   |   |-- risk/                   # Deterministic risk scoring
|   |   |-- ml/                     # Feature engineering + model training
|   |   |-- strategy/               # Expected-value strategy engine
|   |   |-- agents/                 # Groq LLM agent (tools, client, engine)
|   |   |-- policies/               # Deterministic policy/guardrail engine
|   |   |-- execution/              # Action executor + closed-loop controller
|   |   |-- experiments/            # Fair strategy comparison harness
|   |   |-- integrations/           # Real Razorpay test-mode client
|   |   |-- demo/                   # Failure-demonstration scenarios
|   |   |-- analytics/              # Metrics aggregation
|   |   `-- api/                    # All REST endpoints
|   |-- scripts/                    # CLI equivalents of every dashboard action
|   |-- tests/                      # 74 tests
|   |-- requirements.txt
|   `-- .env.example
|-- frontend/
|   `-- index.html                  # The entire dashboard - one file
|-- data/                            # SQLite files + trained model (gitignored)
`-- render.yaml                      # Deployment config
```

---

## Running it locally

```powershell
cd recover-ai\backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

`GROQ_API_KEY` and the two `RAZORPAY_*` keys in `.env` are **optional** - everything works fully
without them; only the live LLM agent consultation and real Razorpay links need them.

Verify the install:
```powershell
$env:PYTHONPATH="."
pytest
```
Should print `74 passed`.

Run it:
```powershell
uvicorn app.main:app --reload
```
Visit **http://127.0.0.1:8000** - the dashboard is served from the same URL as the API (no
separate frontend server, no CORS setup needed). The database auto-seeds a small population on
first startup, so you'll see real data immediately.

---

## Deployment

The whole project is **one deployable service** - FastAPI serves the dashboard and the API from
the same process, on the same port. That's the entire deployment story: run one Python web
service somewhere.

### Recommended: Render.com (free tier)

**1. Push to GitHub** if you haven't already.

**2. Add `render.yaml` at the project root** (`recover-ai/render.yaml`):
```yaml
services:
  - type: web
    name: recoverai
    runtime: python
    rootDir: backend
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: PYTHONPATH
        value: .
      - key: GROQ_API_KEY
        sync: false
      - key: RAZORPAY_KEY_ID
        sync: false
      - key: RAZORPAY_KEY_SECRET
        sync: false
```

**3. On [render.com](https://render.com)**: New -> Web Service -> connect your GitHub repo -> it
auto-detects `render.yaml` -> Create Web Service. First deploy takes 2-3 minutes.

**4. (Optional)** Add real `GROQ_API_KEY` / `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` values under
Render's **Environment** tab if you want the live LLM agent and real Razorpay links active in the
deployed demo.

**5. Open the URL Render gives you.** That's it - the dashboard *is* the root page, already
populated with data.

### Why SQLite's "ephemeral filesystem" limitation doesn't matter here

Render's free tier resets the filesystem on redeploy or idle spin-down. For most apps that's a
real problem. For this one, it's a non-issue by design: the app **auto-seeds fresh data on every
startup**, and the **"Reset demo data"** button exists specifically so a judge (or you) can
generate a brand-new, self-contained demo run at any time. Nothing here needs data to persist
across restarts.

### Post-deployment checklist

Once live, confirm:
- [ ] Dashboard loads with real numbers already populated (auto-seed)
- [ ] Sidebar navigation scrolls correctly between sections
- [ ] "Run outage simulation" (Chaos Mode) produces a before/during comparison
- [ ] "Try your own scenario" with amount > Rs.25,000 produces an escalation
- [ ] That escalation appears in the queue, and **Approve** genuinely executes it
- [ ] Searching a customer name in both search boxes filters correctly
- [ ] "Train recovery model" and "Run simulation" update the "Under the hood" cards live

---

## A note on honesty

This project deliberately reports its own weak points as readily as its strengths: the ML model's
honest evaluation against a simple baseline, the experimentation harness's documented scope
limits, and a dedicated failure-demonstration suite proving the system fails safely rather than
silently. None of the numbers shown in the dashboard are fabricated or pre-scripted - every click
computes something real, live, from the current database state.