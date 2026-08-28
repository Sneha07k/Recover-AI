from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central place for all configurable values. Every field here can be
    overridden by an environment variable of the same name (case-insensitive),
    which we load from a .env file during development.
    """

    model_config = SettingsConfigDict(env_file=".env")

    APP_NAME: str = "RecoverAI"
    ENVIRONMENT: str = "development"

    # SQLite file lives inside data/ so it's easy to find and .gitignore
    DATABASE_URL: str = "sqlite:///../data/recoverai.db"


# Created once, imported everywhere else that needs config.
settings = Settings()
