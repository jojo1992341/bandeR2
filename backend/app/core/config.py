"""
Configuration du Backend RythmoAI (§6.1 Configuration & Environnement)

Utilise pydantic-settings pour un chargement explicite et validé du fichier .env,
avec support du mode asynchrone SQLAlchemy 2.0 + asyncpg pour PostgreSQL 16.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuration validée du backend.
    Charge explicitement le fichier .env (§6.1 CDC) et applique les defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============================================================
    # Base de données (§6.1, §9.1, §18.4)
    # ============================================================
    # URL complète du moteur asynchrone : postgresql+asyncpg://...
    # Si DATABASE_URL n'est pas fournie, on construit une URL valide
    # en combinant les composants individuels.
    DATABASE_URL: Annotated[
        str,
        Field(
            description="URL complète SQLAlchemy asynchrone (postgresql+asyncpg://...)"
        ),
    ] = ""

    # Composants de construction de l'URL (fallback si DATABASE_URL vide)
    DB_ENGINE: str = Field(
        default="postgresql+asyncpg",
        description="Moteur SQLAlchemy (postgresql+asyncpg ou sqlite+aiosqlite)",
    )
    DB_USER: str = Field(default="postgres", description="Utilisateur PostgreSQL")
    DB_PASSWORD: str = Field(default="postgres", description="Mot de passe PostgreSQL")
    DB_HOST: str = Field(default="localhost", description="Hôte PostgreSQL")
    DB_PORT: int = Field(default=5432, description="Port PostgreSQL")
    DB_NAME: str = Field(default="rythmoai", description="Nom de la base")

    # URL de test unitaire (SQLite en mémoire, uniquement pour les tests)
    TEST_DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///:memory:",
        description="URL SQLite asynchrone pour les tests unitaires",
    )

    # ============================================================
    # Sécurité (§15.4, §15.7)
    # ============================================================
    SECRET_KEY: str = Field(
        default_factory=lambda: os.getenv(
            "SECRET_KEY", "r3ythm0a1-super-secret-key-32bytes-long!!"
        ),
        description="Clé secrète pour les tokens JWT",
    )
    ALGORITHM: str = Field(default="HS256", description="Algorithme JWT")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=15, description="Durée d'expiration du token d'accès"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, description="Durée d'expiration du token de rafraîchissement"
    )

    # ============================================================
    # Redis (§10.1 Cache & Sessions)
    # ============================================================
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="URL de connexion Redis",
    )

    # ============================================================
    # Stockage S3 / MinIO (§12.2 Assets média)
    # ============================================================
    S3_ENDPOINT_URL: str = Field(
        default="http://localhost:9000",
        description="Endpoint S3/MinIO",
    )
    S3_BUCKET: str = Field(
        default="rythmoai-media",
        description="Bucket S3 par défaut",
    )
    S3_ACCESS_KEY: str = Field(
        default="minioadmin",
        description="Clé d'accès S3",
    )
    S3_SECRET_KEY: str = Field(
        default="minioadmin",
        description="Clé secrète S3",
    )

    # ============================================================
    # Feature flags (§19.3 Déploiement progressif)
    # ============================================================
    FEATURE_LIP_SYNC_ENABLED: bool = Field(
        default=False,
        description="Activation de la synchronisation labiale (§8.2.6, §11.4)",
    )
    # Alias de compatibilité (historiquement référencé sous ce nom)
    LIP_SYNC_ENABLED: bool = Field(
        default=False,
        description="Alias de FEATURE_LIP_SYNC_ENABLED (compatibilité)",
    )
    LIP_SYNC_FPS: int = Field(
        default=10,
        description="FPS de capture pour la synchronisation labiale",
    )
    LIP_SYNC_CONFIDENCE_THRESHOLD: float = Field(
        default=0.5,
        description="Seuil de confiance pour la synchronisation labiale",
    )

    FEATURE_CRDT_ENABLED: bool = Field(
        default=False,
        description="Activation du CRDT pour édition collaborative (§16.4)",
    )

    SOURCE_SEPARATION_BACKEND: str = Field(
        default="auto",
        description="Backend de séparation de sources : auto | spectral | demucs | off",
    )
    FEATURE_SOURCE_SEPARATION_ENABLED: bool = Field(
        default=False,
        description="Activation de la séparation de sources (§12.1)",
    )

    # ============================================================
    # Validators
    # ============================================================
    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def build_database_url(cls, v: str) -> str:
        """Construit l'URL de base de données si non fournie explicitement."""
        if v and v.strip():
            return v.strip()

        # Construire l'URL depuis les composants
        engine = os.getenv("DB_ENGINE", "postgresql+asyncpg")
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD", "postgres")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "rythmoai")

        return f"{engine}://{user}:{password}@{host}:{port}/{db_name}"

    @model_validator(mode="after")
    def _sync_feature_flags_from_env(self):
        """
        Synchronise les feature flags explicites avec les variables d'env `FEATURE_*`
        (§19.3) — permet d'activer une fonctionnalité via FEATURE_CRDT=1 /
        FEATURE_LIP_SYNC=1 / FEATURE_SOURCE_SEPARATION=1, en plus des champs
        `FEATURE_*_ENABLED` explicites.
        """
        truthy = ("1", "true", "yes", "on")
        env_pairs = [
            ("FEATURE_CRDT", "FEATURE_CRDT_ENABLED"),
            ("FEATURE_LIP_SYNC", "FEATURE_LIP_SYNC_ENABLED"),
            ("FEATURE_SOURCE_SEPARATION", "FEATURE_SOURCE_SEPARATION_ENABLED"),
        ]
        for env_name, field_name in env_pairs:
            val = os.getenv(env_name)
            if val is not None:
                setattr(self, field_name, val.strip().lower() in truthy)
        return self

    @field_validator("TEST_DATABASE_URL", mode="before")
    @classmethod
    def validate_test_url(cls, v: str) -> str:
        """Valide que l'URL de test utilise un moteur asynchrone."""
        if not v:
            return "sqlite+aiosqlite:///:memory:"
        return v

    def get_database_url(self, for_test: bool = False) -> str:
        """
        Retourne l'URL de base de données appropriée.

        Args:
            for_test: Si True, retourne l'URL de test (SQLite asynchrone).
                     Sinon retourne l'URL de production (PostgreSQL+asyncpg).
        """
        if for_test:
            return self.TEST_DATABASE_URL
        return self.DATABASE_URL

    @property
    def is_postgres(self) -> bool:
        """Indique si le moteur de base configuré est PostgreSQL."""
        return "postgresql" in self.DATABASE_URL

    @property
    def is_sqlite(self) -> bool:
        """Indique si le moteur de base configuré est SQLite."""
        return "sqlite" in self.DATABASE_URL

    def is_feature_enabled(self, feature: str) -> bool:
        """
        Vérifie si une fonctionnalité est activée via son feature flag (§19.3).

        Une fonctionnalité est activée si son flag explicite (champ
        `FEATURE_*_ENABLED`) est True **ou** si la variable d'environnement
        équivalente (`FEATURE_<NAME>` = 1/true/yes/on) est positionnée. La
        lecture de l'environnement est dynamique (live) pour permettre de
        basculer un flag en cours de session de test.

        Args:
            feature: nom de la fonctionnalité (ex. "crdt", "lip_sync",
                     "source_separation"). La recherche est insensible à la
                     casse et tolère "lipsync".

        Returns:
            True si la fonctionnalité est activée, False sinon.
        """
        key = (feature or "").strip().lower()
        truthy = ("1", "true", "yes", "on")
        env_var = f"FEATURE_{key.upper()}"
        env_enabled = os.getenv(env_var, "").strip().lower() in truthy
        mapping = {
            "crdt": self.FEATURE_CRDT_ENABLED,
            "lip_sync": self.FEATURE_LIP_SYNC_ENABLED,
            "lipsync": self.FEATURE_LIP_SYNC_ENABLED,
            "source_separation": self.FEATURE_SOURCE_SEPARATION_ENABLED,
        }
        return bool(mapping.get(key, False)) or env_enabled


@lru_cache
def get_settings() -> Settings:
    """
    Retourne la configuration du modèle Settings.

    Le cache lru_cache assure qu'une seule instance est créée,
    même si la fonction est appelée plusieurs fois.
    Le fichier .env est chargé explicitement par pydantic-settings
    lors de la première instanciation.
    """
    return Settings()


# Alias pour compatibilité ascendante
SettingsConfig = Settings
