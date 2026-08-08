"""
Tâche Celery de séparation de sources (§12.1, option de pipeline V2).

Isole la piste « dialogue » d'un mixage complet (dialogue/musique/effets) afin
d'améliorer la transcription (WER) sur les extraits à forte présence musicale.

Activable :
  * variable d'env ``SOURCE_SEPARATION_BACKEND`` = ``spectral`` | ``demucs``
  * ou ``FEATURE_SOURCE_SEPARATION=1`` (backend par défaut ``auto``)
  * ou ``enable_source_separation=True`` passé dans les options du pipeline
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from celery import Celery

celery_app = Celery("rythmoai", broker="redis://localhost:6379/0")

logger = logging.getLogger("rythmoai")


@celery_app.task(bind=True, max_retries=2, default_retry_delay=15)
def separate_sources(
    self,
    media_path: str,
    output_dir: str = "/tmp/rythmoai_separation",
    backend: Optional[str] = None,
    media_id: Optional[str] = None,
) -> dict:
    """Sépare un mixage en dialogue / musique / effets et retourne les chemins.

    Retourne un dict compatible avec le pipeline :
        {
            "input_path": ...,
            "dialogue_path": ...,
            "stems": {"dialogue": path, "music": path, "effects": path},
            "backend": "spectral" | "demucs",
            "sample_rate": 16000,
            "metrics": {...},
        }
    """
    try:
        from app.ai.source_separator import (
            STEM_DIALOGUE,
            STEM_EFFECTS,
            STEM_MUSIC,
            get_separator,
            is_separation_enabled,
        )
    except Exception as exc:  # l'import ne doit jamais casser le pipeline
        logger.warning("source_separator indisponible: %s", exc)
        return {
            "status": "unavailable",
            "input_path": media_path,
            "error": str(exc),
            "media_id": media_id,
        }

    if not is_separation_enabled() and backend in (None, "auto"):
        return {
            "status": "skipped",
            "reason": "feature_disabled",
            "input_path": media_path,
            "media_id": media_id,
        }

    try:
        sep = get_separator(backend)
        result = sep.separate_file(media_path, output_dir=output_dir)
        stem_paths = getattr(result, "stem_paths", {})
        return {
            "status": "ok",
            "input_path": media_path,
            "dialogue_path": stem_paths.get(STEM_DIALOGUE),
            "stems": stem_paths,
            "backend": result.backend,
            "sample_rate": result.sample_rate,
            "metrics": result.metrics,
            "media_id": media_id,
        }
    except Exception as exc:
        logger.warning("separate_sources échec (non bloquant): %s", exc)
        return {
            "status": "error",
            "input_path": media_path,
            "error": str(exc),
            "media_id": media_id,
        }


def maybe_separate_dialogue(
    media_path: str,
    options: Optional[dict] = None,
    output_dir: str = "/tmp/rythmoai_separation",
) -> str:
    """Raccourci synchrone utilisé par la tâche de transcription.

    Retourne le chemin du WAV « dialogue » si la séparation est activée, sinon
    le ``media_path`` d'origine. En cas d'échec, retourne l'original pour ne
    pas casser le pipeline.
    """
    options = options or {}
    enabled = bool(options.get("enable_source_separation"))
    if not enabled:
        try:
            from app.ai.source_separator import is_separation_enabled

            enabled = is_separation_enabled()
        except Exception:
            enabled = False
    if not enabled:
        return media_path

    backend = options.get("source_separation_backend")
    try:
        result = separate_sources.run(
            media_path=media_path,
            output_dir=output_dir,
            backend=backend,
        )
        if result.get("status") == "ok" and result.get("dialogue_path"):
            return result["dialogue_path"]
        logger.info(
            "Séparation non utilisée (status=%s) — conservation du mix original",
            result.get("status"),
        )
    except Exception as exc:
        logger.warning("maybe_separate_dialogue fallback: %s", exc)
    return media_path
