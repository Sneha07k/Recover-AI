from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "recoverai.db"
_DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    

    model_config = SettingsConfigDict(env_file=_PROJECT_ROOT / "backend" / ".env", extra="ignore")

    APP_NAME: str = "RecoverAI"
    ENVIRONMENT: str = "development"

    
    DATABASE_URL: str = f"sqlite:///{_DEFAULT_DB_PATH}"

   
    GROQ_API_KEY: str = ""

    
    
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""



settings = Settings()