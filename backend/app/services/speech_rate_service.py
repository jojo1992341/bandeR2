import re
import pyphen
from typing import Optional, Dict, Any
from app.core.logging import logger

_PYPHEN_DICTIONARIES = {}


def _get_pyphen_dict(language: str):
    lang_map = {
        "fr": "fr_FR",
        "fr-fr": "fr_FR",
        "fr_fr": "fr_FR",
        "fr_standard": "fr_FR",
        "en": "en_US",
        "en-us": "en_US",
        "en_us": "en_US",
        "es": "es_ES",
        "es-es": "es_ES",
        "de": "de_DE",
        "de-de": "de_DE",
        "it": "it_IT",
    }
    canon = lang_map.get(language.lower(), "fr_FR")
    if canon not in _PYPHEN_DICTIONARIES:
        try:
            _PYPHEN_DICTIONARIES[canon] = pyphen.Pyphen(lang=canon)
        except Exception:
            try:
                _PYPHEN_DICTIONARIES[canon] = pyphen.Pyphen(lang="fr_FR")
            except Exception:
                _PYPHEN_DICTIONARIES[canon] = None
    return _PYPHEN_DICTIONARIES[canon]


def _count_syllables_regex_fr(word: str) -> int:
    """Fallback heuristique pour le comptage de syllabes en français si pyphen indisponible."""
    word = re.sub(r"[^a-zàâäéèêëîïôöùûüç]", "", word.lower())
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    vowels = "aeiouyàâäéèêëîïôöùûü"
    count = 0
    in_vowel = False
    for char in word:
        if char in vowels:
            if not in_vowel:
                count += 1
                in_vowel = True
        else:
            in_vowel = False
    if word.endswith("e") and count > 1 and not word.endswith("ée"):
        count -= 1
    return max(1, count)


def count_syllables(text: str, language: str = "fr") -> int:
    """
    Compte le nombre total de syllabes dans un texte transcrit ou édité (§12.3).
    """
    if not text:
        return 0
    words = [
        re.sub(r"[^a-zA-ZàâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ]", "", w)
        for w in text.split()
    ]
    words = [w for w in words if len(w) > 0]
    if not words:
        return 0

    dic = _get_pyphen_dict(language)
    total_syllables = 0
    for w in words:
        if dic:
            try:
                hyphenated = dic.inserted(w)
                count = len(hyphenated.split("-"))
                total_syllables += max(1, count)
            except Exception:
                total_syllables += _count_syllables_regex_fr(w)
        else:
            total_syllables += _count_syllables_regex_fr(w)

    return total_syllables


DEFAULT_SPEECH_RATE_THRESHOLDS = {
    "fr": {"min_rate": 5.0, "max_rate": 7.0},
    "fr-fr": {"min_rate": 5.0, "max_rate": 7.0},
    "fr_standard": {"min_rate": 5.0, "max_rate": 7.0},
    "en": {"min_rate": 4.5, "max_rate": 6.5},
    "en-us": {"min_rate": 4.5, "max_rate": 6.5},
    "es": {"min_rate": 5.5, "max_rate": 7.5},
    "de": {"min_rate": 4.0, "max_rate": 6.0},
}


def compute_speech_rate(
    text: str, duration_ms: int, language: str = "fr"
) -> float:
    """
    Calcule le débit d'élocution (syllabes/seconde) d'une réplique (§12.3).
    """
    if not text or duration_ms <= 0:
        return 0.0

    duration_sec = duration_ms / 1000.0
    syllables = count_syllables(text, language)
    rate = syllables / duration_sec
    return round(rate, 2)


def evaluate_speech_rate(
    text: str,
    duration_ms: int,
    language: str = "fr",
    custom_thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Calcule le débit d'élocution et le compare aux seuils configurables par langue (§12.3).
    Signale un écart significatif (alerte à l'adaptateur).
    """
    syllables = count_syllables(text, language)
    duration_sec = duration_ms / 1000.0 if duration_ms > 0 else 0.0
    rate = round(syllables / duration_sec, 2) if duration_sec > 0 else 0.0

    lang_key = (
        language.lower().strip()
        if language
        and language.lower().strip() in DEFAULT_SPEECH_RATE_THRESHOLDS
        else "fr"
    )
    default_bounds = DEFAULT_SPEECH_RATE_THRESHOLDS.get(
        lang_key, DEFAULT_SPEECH_RATE_THRESHOLDS["fr"]
    )

    min_rate = (
        float(custom_thresholds.get("min_rate", default_bounds["min_rate"]))
        if custom_thresholds and "min_rate" in custom_thresholds
        else default_bounds["min_rate"]
    )
    max_rate = (
        float(custom_thresholds.get("max_rate", default_bounds["max_rate"]))
        if custom_thresholds and "max_rate" in custom_thresholds
        else default_bounds["max_rate"]
    )

    is_alert = False
    alert_type = "normal"
    alert_message = ""

    if rate > max_rate:
        is_alert = True
        alert_type = "too_fast"
        alert_message = (
            f"Débit d'élocution trop élevé ({rate:.2f} syll/s > seuil {max_rate:.1f} syll/s en {language.upper()}). "
            "Risque de désynchronisation labiale ou de diction trop rapide pour le comédien (§12.3)."
        )
    elif rate < min_rate and rate > 0.0:
        is_alert = True
        alert_type = "too_slow"
        alert_message = (
            f"Débit d'élocution trop lent ({rate:.2f} syll/s < seuil {min_rate:.1f} syll/s en {language.upper()}). "
            "Risque de désynchronisation labiale ou de diction trop lente pour le comédien (§12.3)."
        )

    return {
        "syllable_count": syllables,
        "duration_ms": duration_ms,
        "duration_sec": round(duration_sec, 3),
        "speech_rate": rate,
        "language": language,
        "min_rate": min_rate,
        "max_rate": max_rate,
        "is_alert": is_alert,
        "alert_type": alert_type,
        "alert_message": alert_message,
    }
