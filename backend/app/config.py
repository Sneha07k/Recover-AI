from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central place for all configurable values. Every field here can be
    overridden by an environment variable of the same name (case-insensitive),
    which we load from a .env file during development.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "RecoverAI"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "sqlite:///../data/recoverai.db"

    GROQ_API_KEY: str = ""

    # Required only for Phase 14's Razorpay integration. Must be TEST MODE
    # keys (key_id starts with "rzp_test_") — never put live keys here.
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""


settings = Settings()
