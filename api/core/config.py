from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_url: str = "postgresql://quorum:quorum@localhost:5432/quorum"
    database_url: str = ""  # if set, overrides postgres_url (e.g. sqlite:///./data/quorum.db)
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True

    storage_backend: str = "s3"  # s3 | local
    local_data_dir: str = "./data"

    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "quorum-uploads"
    minio_region: str = "us-east-1"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_mode: str = "server"  # server | local
    qdrant_local_path: str = "./data/qdrant"
    qdrant_collection: str = "quorum_chunks"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    session_ttl_days: int = 7
    worker_poll_interval_seconds: int = 2
    worker_batch_size: int = 5
    # Run the job worker inside the API process (required for embedded/local Qdrant).
    run_worker_in_api: bool = False
    llm_concurrency_limit: int = 10
    ask_timeout_seconds: int = 30

    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    reranker_model_name: str = "BAAI/bge-reranker-base"
    embedding_model_version: str = "bge-small-en-v1.5"

    upload_chunk_size_bytes: int = 5 * 1024 * 1024
    live_eval_sample_rate: float = 0.2  # fraction of /ask calls to log as live_sample

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return self.postgres_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
