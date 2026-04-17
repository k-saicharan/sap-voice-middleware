from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "sqlite+aiosqlite:///./voice_profiles.db"
    API_KEYS: str = ""
    PUBLIC_PROFILE_ENDPOINT: bool = True
    GROQ_API_KEY: str = ""
    AUDIO_STORAGE_PATH: str = "/data/audio"
    EMBEDDING_MODEL: str = "speechbrain"  # speechbrain | pyannote | mock
    HUGGINGFACE_TOKEN: str = ""
    ENROLLMENT_MIN_DURATION_SECONDS: int = 10
    LOG_LEVEL: str = "INFO"


settings = Settings()
