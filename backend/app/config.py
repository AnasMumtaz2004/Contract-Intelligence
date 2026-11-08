from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All app settings, read from environment variables or the .env file."""

    database_url: str
    redis_url: str
    secret_key: str

    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 1440

    upload_dir: str = "uploads"
    max_upload_mb: int = 20
    frontend_origin: str = "http://localhost:5173"

    # If you change the model, change the dimension and the migration too.
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384

    # Target size of one chunk, counted in words
    chunk_max_words: int = 300

    # LLM keys and model names. Leave a key empty to skip that provider.
    google_api_key: str = ""
    groq_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    groq_model: str = "llama-3.3-70b-versatile"

    # How many chunks go to the LLM
    top_k: int = 5
    # How many candidates each search returns before they are merged
    candidate_pool: int = 20
    # Standard RRF constant. A bigger number makes lower ranks count more.
    rrf_k: int = 60

    # Look for .env in the backend folder first, then in the project root
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")


settings = Settings()