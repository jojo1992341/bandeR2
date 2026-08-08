"""
Test unitaire pour le calcul du débit d'élocution (syllabes/seconde) comparé aux seuils
configurables par langue (5-7 syll/s en FR standard, §12.3).
Condition d'achèvement :
- vérifie le calcul sur un texte de référence
- vérifie le déclenchement de l'alerte au-delà du seuil configuré
"""

import pytest
from app.services.speech_rate_service import (
    count_syllables,
    compute_speech_rate,
    evaluate_speech_rate,
    DEFAULT_SPEECH_RATE_THRESHOLDS,
)


def test_syllable_counting_and_speech_rate_calculation_on_reference_text():
    """
    Vérifie le comptage syllabique et le calcul du débit d'élocution sur un texte de référence en FR standard (§12.3).
    """
    reference_text = "Bonjour à tous les comédiens du studio Rythmo"

    # 1. Vérification du comptage syllabique
    syllables = count_syllables(reference_text, language="fr")
    assert syllables == 13, (
        f"13 syllabes attendues ('Bon-jour à tous les co-mé-diens du stu-dio Ryth-mo'), trouvé {syllables}"
    )

    # 2. Vérification du calcul du débit d'élocution avec une durée normale (2.0 secondes = 2000 ms)
    # 13 syllabes / 2.0 s = 6.5 syll/s (dans la plage standard FR 5.0 - 7.0 syll/s)
    rate = compute_speech_rate(reference_text, 2000, language="fr")
    assert rate == 6.5, (
        f"Débit attendu 6.5 syll/s pour 13 syllabes en 2000 ms, trouvé {rate}"
    )

    eval_result = evaluate_speech_rate(reference_text, 2000, language="fr")
    assert eval_result["syllable_count"] == 13
    assert eval_result["speech_rate"] == 6.5
    assert eval_result["min_rate"] == 5.0
    assert eval_result["max_rate"] == 7.0
    assert eval_result["is_alert"] is False
    assert eval_result["alert_type"] == "normal"
    assert eval_result["alert_message"] == ""


def test_alert_triggered_above_configured_threshold():
    """
    CONDITION D'ACHÈVEMENT :
    Vérifie le déclenchement de l'alerte dès que le débit dépasse le seuil configuré (§12.3).
    """
    reference_text = "Bonjour à tous les comédiens du studio Rythmo"  # 13 syllabes

    # ------------------------------------------------------------------
    # A. DÉBIT TROP ÉLEVÉ (> 7.0 syll/s en FR standard)
    # ------------------------------------------------------------------
    # 13 syllabes en 1300 ms (1.3 s) = 10.0 syll/s -> dépasse strictement max_rate (7.0)
    res_fast = evaluate_speech_rate(reference_text, 1300, language="fr")

    assert res_fast["speech_rate"] == 10.0
    assert (
        res_fast["is_alert"] is True
    ), "Une alerte doit être déclenchée au-delà du seuil configuré (7.0 syll/s)"
    assert res_fast["alert_type"] == "too_fast"
    assert "trop élevé" in res_fast["alert_message"].lower()
    assert "10.0" in res_fast["alert_message"] or "10" in res_fast["alert_message"]
    assert "7.0" in res_fast["alert_message"]
    assert "§12.3" in res_fast["alert_message"]

    # ------------------------------------------------------------------
    # B. DÉBIT TROP LENT (< 5.0 syll/s en FR standard)
    # ------------------------------------------------------------------
    # 13 syllabes en 4000 ms (4.0 s) = 3.25 syll/s -> sous min_rate (5.0)
    res_slow = evaluate_speech_rate(reference_text, 4000, language="fr")

    assert res_slow["speech_rate"] == 3.25
    assert (
        res_slow["is_alert"] is True
    ), "Une alerte doit être déclenchée en deçà du seuil configuré (5.0 syll/s)"
    assert res_slow["alert_type"] == "too_slow"
    assert "trop lent" in res_slow["alert_message"].lower()

    # ------------------------------------------------------------------
    # C. SEUILS CONFIGURABLES PAR LANGUE (ex. personnalisation studio / projet)
    # ------------------------------------------------------------------
    # En redéfinissant un seuil haut personnalisé à 12.0 syll/s, le débit 10.0 syll/s n'est plus en alerte
    res_custom = evaluate_speech_rate(
        reference_text,
        1300,
        language="fr",
        custom_thresholds={"min_rate": 8.0, "max_rate": 12.0},
    )

    assert res_custom["speech_rate"] == 10.0
    assert res_custom["min_rate"] == 8.0
    assert res_custom["max_rate"] == 12.0
    assert (
        res_custom["is_alert"] is False
    ), "Avec le seuil configurable redéfini [8.0 - 12.0], 10.0 syll/s ne doit plus alerter"
    assert res_custom["alert_type"] == "normal"
