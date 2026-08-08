from pydantic import BaseModel, Field
from functools import lru_cache


class Settings(BaseModel):
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost/rythmoai"
    )
    SECRET_KEY: str = Field(default="changeme")
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30)
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)
    SECRET_KEY: str = Field(default="r3ythm0a1-super-secret-key-32bytes-long!!")
    S3_ENDPOINT_URL: str = Field(default="http://localhost:9000")
    S3_BUCKET: str = Field(default="rythmoai-media")
    S3_ACCESS_KEY: str = Field(default="minioadmin")
    S3_SECRET_KEY: str = Field(default="minioadmin")

    # Config handled via Field defaults; no extra Config class required


@lru_cache
def get_settings() -> Settings:
    import os

    return Settings()
