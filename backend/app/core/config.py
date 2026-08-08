import os
from pydantic import BaseModel, Field
from functools import lru_cache


class Settings(BaseModel):
    DATABASE_URL: str = Field(
        default=os.getenv("DATABASE_URL", "sqlite:///:memory:")
    )
    SECRET_KEY: str = Field(
        default=os.getenv("SECRET_KEY", "r3ythm0a1-super-secret-key-32bytes-long!!")
    )
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)
    REDIS_URL: str = Field(default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    S3_ENDPOINT_URL: str = Field(default="http://localhost:9000")
    S3_BUCKET: str = Field(default="rythmoai-media")
    S3_ACCESS_KEY: str = Field(default="minioadmin")
    S3_SECRET_KEY: str = Field(default="minioadmin")


@lru_cache
def get_settings() -> Settings:
    return Settings()
