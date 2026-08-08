"""
Utilitaires d'évaluation de transcription (WER / CER).

Utilisés pour valider l'amélioration mesurée du WER après séparation de sources
(§12.1 — objectif V2). L'implémentation est en bibliothèque standard pour être
exécutable en CI sans dépendance supplémentaire.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def normalize_text(text: str, language: str = "fr") -> str:
    """Normalisation déterministe pour calcul de WER."""
    text = text.lower().strip()
    # Aplatir les accents (transcription automatique / référence)
    replacements = {
        "à": "a",
        "â": "a",
        "ä": "a",
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ö": "o",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ÿ": "y",
        "ç": "c",
        "œ": "oe",
        "æ": "ae",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    # Séparer la ponctuation
    text = re.sub(r"[^\w\s']", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str) -> List[str]:
    return _WORD_RE.findall(normalize_text(text))


def edit_distance(a: Sequence[str], b: Sequence[str]) -> int:
    """Distance de Levenschtien sur tokens (WER)."""
    if len(a) < len(b):
        return edit_distance(b, a)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            current.append(
                min(
                    previous[j] + 1,  # suppression
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + cost,  # substitution
                )
            )
        previous = current
    return previous[-1]


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate dans [0, +∞). 0 = transcription parfaite."""
    ref = tokenize(reference)
    hyp = tokenize(hypothesis)
    if not ref:
        return 0.0 if not hyp else float(len(hyp))
    return edit_distance(ref, hyp) / float(len(ref))


def wer_details(reference: str, hypothesis: str) -> Dict[str, float]:
    ref = tokenize(reference)
    hyp_tokens = tokenize(hypothesis)
    dist = edit_distance(ref, hyp_tokens)
    return {
        "wer": dist / len(ref) if ref else 0.0,
        "distance": dist,
        "ref_words": len(ref),
        "hyp_words": len(hyp_tokens),
    }


def compare_wer(
    reference: str, hypothesis_baseline: str, hypothesis_separated: str
) -> Dict[str, float]:
    """Compare deux hypothèses et retourne la réduction relative du WER."""
    base = wer_details(reference, hypothesis_baseline)
    sep = wer_details(reference, hypothesis_separated)
    abs_improvement = base["wer"] - sep["wer"]
    rel_improvement = abs_improvement / base["wer"] if base["wer"] > 0 else 0.0
    return {
        "wer_baseline": base["wer"],
        "wer_separated": sep["wer"],
        "absolute_improvement": abs_improvement,
        "relative_improvement": rel_improvement,
        "ref_words": base["ref_words"],
    }
