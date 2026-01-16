from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, List
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration using Pydantic Settings"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # Database
    database_url: str = "postgresql://user:password@localhost:5432/shorts_automation"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_echo: bool = False
    
    # Redis & Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    
    # Storage
    storage_type: Literal["local", "s3", "hybrid"] = "hybrid"
    local_storage_path: str = "./storage"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_s3_bucket: str | None = None
    aws_region: str = "us-east-1"
    
    # AI Services
    openai_api_key: str = ""
    openai_model: str = "gpt-4-vision-preview"
    openai_max_tokens: int = 4096
    
    # Platform APIs
    youtube_api_key: str = ""
    apify_api_key: str = ""
    
    # Rate Limiting
    max_concurrent_downloads: int = 5
    max_concurrent_analysis: int = 3
    rate_limit_per_minute: int = 60
    
    # Video Processing
    max_video_size_mb: int = 500
    supported_formats: List[str] = ["mp4", "webm", "mov"]
    target_resolution: str = "1080x1920"
    target_fps: int = 30
    output_format: str = "mp4"
    
    # Content Moderation
    enable_moderation: bool = True
    moderation_threshold: float = 0.8
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "./logs/app.log"
    
    @property
    def is_development(self) -> bool:
        return self.app_env == "development"
    
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()


# Convenience export
settings = get_settings()
