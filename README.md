# RecoverAI

Autonomous revenue recovery controller — simulation-first agentic system for
Razorpay Buildathon Track 3.

See `docs/architecture.md` and `docs/roadmap.md` for the full design and
phased build plan.

## Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Visit http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs

## Running tests

```bash
cd backend
pytest
```
