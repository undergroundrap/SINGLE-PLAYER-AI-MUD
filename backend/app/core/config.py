from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    LM_STUDIO_URL: str = "http://localhost:1234/v1"
    VECTOR_DB_PATH: str = "./data/mud_vector_db"
    DEBUG: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
