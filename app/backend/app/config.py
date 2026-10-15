from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / "app" / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_user: str = "postgres"
    db_password: str = ""
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "postgres"
    postgres_url: str = Field(default="", validation_alias="DATABASE_URL")

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"

    generation_model: str = "openai/gpt-oss-120b"
    vision_model: str = "qwen/qwen3.8-27b"
    verifier_model: str = "qwen/qwen3.8-27b"
    judge_model: str = "openai/gpt-oss-120b"
    transcription_model: str = "whisper-large-v3"
    tts_model: str = "canopylabs/orpheus-v1-english"
    tts_voice: str = "tara"

    tokens_per_minute: int = 8000
    requests_per_minute: int = 60
    max_retries: int = 6
    request_timeout_seconds: float = 180.0
    max_backoff_seconds: float = 45.0
    circuit_breaker_threshold: int = 6
    circuit_breaker_cooldown_seconds: float = 120.0
    max_consecutive_page_failures: int = 5

    access_keys: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_origin_regex: str = ""

    redis_url: str = ""
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    upstash_poll_seconds: float = 1.0
    upstash_idle_poll_seconds: float = 6.0
    use_upstash_for_events: bool = True
    share_token_budget: bool = True
    access_key: str = ""
    realtime_state_ttl_seconds: int = 3600
    sse_max_seconds: float = 900.0
    sse_retry_ms: int = 3000

    interactive_completion_estimate: int = 600
    batch_completion_estimate: int = 500
    chat_max_tokens: int = 1500
    notes_max_tokens: int = 4800
    notes_context_chars: int = 5500
    notes_top_k: int = 8
    generation_max_tokens: int = 4000
    # Groq admits a request against prompt + max_completion_tokens, so this ceiling is
    # reserved on every page whatever the model writes. Measured over 228 vision calls
    # on the demo corpus: median completion 174 tokens, p95 536, longest 712. 850 keeps
    # headroom above the longest observed description while booking 250 fewer tokens
    # per page than the old 1100.
    page_image_max_tokens: int = 850
    keyframe_max_tokens: int = 500
    warm_embedder_on_start: bool = True

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int = 384
    query_instruction: str = "Represent this sentence for searching relevant passages: "

    enable_ocr: bool = False
    ocr_fallback_chars_per_page: int = 90
    figure_image_scale: float = 1.6
    docling_threads: int = 8

    chunk_target_tokens: int = 320
    chunk_overlap_tokens: int = 60
    transcript_window_seconds: float = 45.0
    keyframe_interval_seconds: float = 90.0

    retrieval_candidates: int = 40
    retrieval_top_k: int = 8
    rrf_k: int = 60
    grounding_threshold: float = 0.38
    # Refuse before generating when the best passage does not stand clear of the rest
    # by this much. Chosen on evaluation/datasets/dev.json: no false refusals there,
    # while catching five of eight off-material questions before a token is spent.
    grounding_margin: float = 0.028
    novelty_threshold: float = 0.88

    storage_dir: Path = Field(default=BACKEND_ROOT / "storage")
    ingestion_workers: int = 1

    @property
    def upstash_url(self) -> str:
        return self.upstash_redis_rest_url.strip().strip('"')

    @property
    def upstash_token(self) -> str:
        return self.upstash_redis_rest_token.strip().strip('"')

    @property
    def access_key_spec(self) -> str:
        """Accepts ACCESS_KEYS (key:Name pairs) or a single ACCESS_KEY."""
        if self.access_keys.strip():
            return self.access_keys
        single = self.access_key.strip()
        return f"{single}:Owner" if single else ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def figures_dir(self) -> Path:
        return self.storage_dir / "figures"

    @property
    def audio_dir(self) -> Path:
        return self.storage_dir / "audio"

    @property
    def database_url(self) -> str:
        """A managed Postgres (Neon, Railway, Supabase) hands out one libpq URL, so that
        wins when it is set. The discrete DB_* settings stay for local work."""
        raw = self.postgres_url.strip().strip('"')
        if raw:
            if raw.startswith("postgres://"):
                raw = "postgresql://" + raw[len("postgres://") :]
            if raw.startswith("postgresql://"):
                raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
            return raw

        from sqlalchemy.engine import URL

        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        ).render_as_string(hide_password=False)

    def ensure_directories(self) -> None:
        for path in (self.uploads_dir, self.figures_dir, self.audio_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


settings = get_settings()
