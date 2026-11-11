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

    
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384

    # Target size of one chunk, counted in words
    chunk_max_words: int = 300


    google_api_key: str = ""
    groq_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    groq_model: str = "llama-3.3-70b-versatile"

    # How many chunks go to the LLM
    top_k: int = 5
    # How many candidates each search returns before they are merged
    candidate_pool: int = 20
    # Standard RRF constant. A bigger number makes lower ranks count more.
    rrf_k: int = 60

    # Reranking: a small local model that re-scores the search results
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # How many search results go into the reranker
    rerank_pool: int = 20

    # OCR for scanned pages. Leave tesseract_cmd empty if Tesseract is on your PATH.
    tesseract_cmd: str = ""
    ocr_language: str = "eng"
    ocr_dpi: int = 200
    # A page with fewer words than this and a picture on it is treated as a scan
    min_words_per_page: int = 20

    # Most extra chunks that the cross-reference lookup may add
    max_cross_reference_chunks: int = 3
        # Which provider each LLM role tries first. The other one is the backup.
    fast_provider: str = "groq"
    smart_provider: str = "gemini"

    # Keep each provider under its free-tier limit. Calls wait instead of failing.
    gemini_requests_per_minute: int = 8
    groq_requests_per_minute: int = 20
    # How many times a failed LLM call is tried again (with growing pauses)
    llm_max_attempts: int = 3

    # The agent
    # How many times the agent may search (1 = no second try)
    agent_max_attempts: int = 2
    # How many times an answer may be written (2 = one rewrite after a failed check)
    agent_max_generate_attempts: int = 2
    agent_max_sub_questions: int = 3
    agent_chunks_per_sub_question: int = 5
    agent_max_chunks: int = 10
    # Passages are cut to this length when the grader reads them
    grade_chunk_chars: int = 900

    # LangSmith tracing
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "contract-intelligence"
    
   # Security. Turn the scan off only to measure what it adds.
    security_scan_enabled: bool = True

    # Short-term memory (Redis)
    stm_ttl_seconds: int = 7200
    stm_max_turns: int = 4
    stm_answer_chars: int = 300

    # Caches (Redis)
    response_cache_enabled: bool = True
    response_cache_ttl_seconds: int = 86400
    embedding_cache_ttl_seconds: int = 2592000
    llm_cache_enabled: bool = True
    llm_cache_ttl_seconds: int = 604800
    
        # Rate limits: requests per minute. A value of 0 turns a limit off.
    rate_limit_login_per_minute: int = 10
    rate_limit_ask_per_minute: int = 20
    rate_limit_upload_per_minute: int = 10

    # The largest JSON request body, in bytes. Uploads are limited by max_upload_mb instead.
    max_json_body_bytes: int = 100000

    # "json" for servers (one JSON object per line), "text" for reading logs on your own computer
    log_format: str = "json"
    
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")


settings = Settings()