import os
from pydantic import BaseModel, Field
from functools import lru_cache


class Settings(BaseModel):
    DATABASE_URL: str = Field(default=os.getenv("DATABASE_URL", "sqlite:///:memory:"))
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
    # §19.3 Feature flag — déploiement progressif synchronisation labiale (§8.2.6, §11.4)
    # Utiliser default_factory pour lecture dynamique de l'env à chaque instanciation
    FEATURE_LIP_SYNC_ENABLED: bool = Field(
        default_factory=lambda: os.getenv(
            "FEATURE_LIP_SYNC",
            os.getenv("FEATURE_FLAG_LIP_SYNC", os.getenv("ENABLE_LIP_SYNC", "false")),
        ).lower()
        in ("1", "true", "yes", "on")
    )
    # Alternative: LIP_SYNC_ENABLED alias for backwards compatibility
    LIP_SYNC_ENABLED: bool = Field(
        default_factory=lambda: os.getenv(
            "FEATURE_LIP_SYNC",
            os.getenv("FEATURE_FLAG_LIP_SYNC", os.getenv("ENABLE_LIP_SYNC", "false")),
        ).lower()
        in ("1", "true", "yes", "on")
    )
    LIP_SYNC_FPS: int = Field(
        default_factory=lambda: int(os.getenv("LIP_SYNC_FPS", "10"))
    )
    LIP_SYNC_CONFIDENCE_THRESHOLD: float = Field(
        default_factory=lambda: float(os.getenv("LIP_SYNC_CONFIDENCE_THRESHOLD", "0.5"))
    )
    # §16.4 — CRDT pour édition collaborative caractère par caractère (remplace verrouillage optimiste où volume le justifie)
    FEATURE_CRDT_ENABLED: bool = Field(
        default_factory=lambda: os.getenv(
            "FEATURE_CRDT",
            os.getenv("FEATURE_FLAG_CRDT", os.getenv("ENABLE_CRDT", "false")),
        ).lower()
        in ("1", "true", "yes", "on")
    )
    CRDT_ENABLED: bool = Field(
        default_factory=lambda: os.getenv(
            "FEATURE_CRDT",
            os.getenv("FEATURE_FLAG_CRDT", os.getenv("ENABLE_CRDT", "false")),
        ).lower()
        in ("1", "true", "yes", "on")
    )
    # §12.1 — Séparation de sources (dialogue/musique/effets) pour mixages complets
    # Backend: auto | spectral | demucs | off
    SOURCE_SEPARATION_BACKEND: str = Field(
        default_factory=lambda: os.getenv("SOURCE_SEPARATION_BACKEND", "auto").lower()
    )
    FEATURE_SOURCE_SEPARATION_ENABLED: bool = Field(
        default_factory=lambda: os.getenv(
            "FEATURE_SOURCE_SEPARATION",
            os.getenv(
                "FEATURE_FLAG_SOURCE_SEPARATION",
                os.getenv("ENABLE_SOURCE_SEPARATION", "false"),
            ),
        ).lower()
        in ("1", "true", "yes", "on")
    )

    def is_feature_enabled(self, feature: str) -> bool:
        """Vérifie si une feature est activée (§19.3) — lecture directe de l'env pour tests"""
        # Vérifier directement l'env pour permettre les tests qui modifient os.environ sans recréer Settings
        import os as _os

        env_flag_lip = _os.getenv(
            "FEATURE_LIP_SYNC",
            _os.getenv("FEATURE_FLAG_LIP_SYNC", _os.getenv("ENABLE_LIP_SYNC", "")),
        ).lower() in ("1", "true", "yes", "on")
        env_flag_crdt = _os.getenv(
            "FEATURE_CRDT",
            _os.getenv("FEATURE_FLAG_CRDT", _os.getenv("ENABLE_CRDT", "")),
        ).lower() in ("1", "true", "yes", "on")
        feature = feature.lower()
        if feature in ("lip_sync", "lipsync", "face_mesh", "synchronisation_labiale"):
            return (
                self.FEATURE_LIP_SYNC_ENABLED or self.LIP_SYNC_ENABLED or env_flag_lip
            )
        if feature in ("crdt", "collaborative", "replica_crdt", "text_crdt"):
            return self.FEATURE_CRDT_ENABLED or self.CRDT_ENABLED or env_flag_crdt
        if feature in (
            "source_separation",
            "source-separation",
            "separation",
            "dialogue_isolation",
        ):
            backend = _os.getenv("SOURCE_SEPARATION_BACKEND", "auto").lower()
            if backend in ("spectral", "demucs"):
                return True
            if backend in ("off", "false", "0", "disabled"):
                return False
            return self.FEATURE_SOURCE_SEPARATION_ENABLED
        # Autres features : désactivées par défaut sauf si env var FEATURE_<NAME>=1
        env_key = f"FEATURE_{feature.upper()}"
        return _os.getenv(env_key, "false").lower() in ("1", "true", "yes", "on")


@lru_cache
def get_settings() -> Settings:
    return Settings()
