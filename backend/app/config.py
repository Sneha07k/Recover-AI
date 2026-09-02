from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute, computed from this file's location - not relative to whatever
# directory the process happens to be launched from. A relative default
# ("sqlite:///../data/recoverai.db") broke the moment the app was started
# from anywhere other than backend/ itself.
# backend/app/config.py -> parents[2] is the project root, where data/ lives.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "recoverai.db"
_DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """
    Central place for all configurable values. Every field here can be
    overridden by an environment variable of the same name (case-insensitive),
    which we load from a .env file during development.
    """

    model_config = SettingsConfigDict(env_file=_PROJECT_ROOT / "backend" / ".env", extra="ignore")

    APP_NAME: str = "RecoverAI"
    ENVIRONMENT: str = "development"

    # Absolute by default (see _DEFAULT_DB_PATH above). Still fully
    # overridable via .env if you ever point this at a real Postgres
    # instance for production use.
    DATABASE_URL: str = f"sqlite:///{_DEFAULT_DB_PATH}"

    # Required only for Phase 7's agent layer. Leave empty and the agent
    # simply won't be callable — everything else in the system works fine
    # without it, since the LLM is used only for one specific decision step.
    GROQ_API_KEY: str = ""

    # Required only for Phase 14's Razorpay integration. Must be TEST MODE
    # keys (key_id starts with "rzp_test_") — never put live keys here.
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""


# Created once, imported everywhere else that needs config.
settings = Settings()