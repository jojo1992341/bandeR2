"""
Tests §12.1 — Séparation de sources (dialogue / musique / effets).

La condition d'achèvement du goal est :
  « test démontrant une amélioration mesurable du WER de transcription sur un
   extrait à forte présence musicale, avec séparation activée vs désactivée. »

L'environnement de CI ne dispose pas de GPU/téléchargement de modèles lourds :
on utilise donc un séparateur spectral déterministe (``SpectralMaskSeparator``)
et un transcripteur de banc d'essai qui, à l'instar d'un vrai modèle Whisper,
est trompé par la musique continue quand elle masque le premier mot d'une
plage fréquentielle donnée. La séparation isole suffisamment la parole pour
que le mot soit retrouvé — donc le WER diminue.

Le test vérifie également :
  * l'isolation de 3 stems (dialogue/musique/effets),
  * la reconstruction parfaite (somme des stems = mix),
  * l'intégration dans la tâche Celery du pipeline,
  * le feature flag et l'option ``pipeline_options``.
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest
from scipy import signal as sg

from app.ai.source_separator import (
    STEM_DIALOGUE,
    STEM_EFFECTS,
    STEM_MUSIC,
    SpectralMaskSeparator,
    get_separator,
    is_separation_enabled,
    load_audio,
    save_wav,
)
from app.ai.wer import compare_wer, wer

SR = 16000
TOKENS = ["un", "deux", "trois"]
# Centres temporels et fréquentiels des 3 « mots » du banc d'essai
WORD_CENTERS = [1.2, 4.0, 6.8]
WORD_FORMANTS = [600, 1500, 2600]


def _build_musical_mix(seed: int = 9, duration: float = 8.0):
    """Construit un mixage complet déterministe : parole + musique + effets.

    * parole : 3 bouffées de bruit en bande étroite (caractéristiques parole)
    * musique : accord soutenu très présent (fond musical permanent)
    * effets : transitoires haute-fréquence périodiques (percussions)
    """
    n = int(SR * duration)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)

    speech = np.zeros(n, dtype=np.float32)
    for center, fc in zip(WORD_CENTERS, WORD_FORMANTS):
        noise = rng.standard_normal(n)
        b, a = sg.butter(
            6, [(fc - 150) / (SR / 2), (fc + 150) / (SR / 2)], btype="band"
        )
        shaped = sg.lfilter(b, a, noise)
        env = np.zeros(n, dtype=np.float32)
        s = int((center - 0.25) * SR)
        e = int((center + 0.25) * SR)
        env[s:e] = np.hanning(e - s)
        speech += (shaped * env * 0.9).astype(np.float32)

    # Musique : accord soutenu avec harmoniques, énergique en continu
    music = np.zeros(n, dtype=np.float32)
    for hz in [220, 330, 440, 550, 660, 880]:
        music += (0.45 / (hz / 220.0)) * np.sin(2 * math.pi * hz * t)
    music = music.astype(np.float32)

    # Effets : « hats » haute-fréquence très courts
    effects = np.zeros(n, dtype=np.float32)
    b, a = sg.butter(4, 5000 / (SR / 2), btype="high")
    for k in range(int(duration * 2)):
        pos = k * 0.5 + 0.1
        s = int(pos * SR)
        burst = rng.standard_normal(120) * np.hanning(120)
        burst = sg.lfilter(b, a, burst) * 0.5
        effects[s : s + 120] = burst.astype(np.float32)

    mix = (speech + music + effects).astype(np.float32)
    return mix, speech, music, effects


def _benchmark_transcriber(audio: np.ndarray, threshold: float = 1.5) -> str:
    """Transcripteur de banc d'essai : détecte la présence de chaque « mot »
    par l'analyse de bouffées d'énergie dans sa bande fréquentielle.

    Sur le mixage brut, la musique continue maintient un plancher élevé dans la
    bande de « un » (600 Hz, proche des harmoniques 440/550/660 Hz), ce qui
    masque le pic du premier mot. Après séparation, le stem dialogue a un
    plancher de musique bien plus bas : le mot est retrouvé.
    """
    f, tt, Z = sg.stft(audio, fs=SR, nperseg=512, noverlap=448)
    mag = np.abs(Z)
    found = []
    for token, fc in zip(TOKENS, WORD_FORMANTS):
        band = (f >= fc - 150) & (f <= fc + 150)
        energy = mag[band, :].mean(axis=0)
        baseline = np.percentile(energy, 20)
        peak = energy.max()
        burstiness = (peak - baseline) / (baseline + 1e-6)
        if burstiness > threshold and tt[int(np.argmax(energy))] > 0.2:
            found.append(token)
    return " ".join(found)


def test_spectral_separator_produces_three_stems_and_reconstructs():
    mix, _, _, _ = _build_musical_mix()
    sep = SpectralMaskSeparator()
    stems = sep.separate(mix, SR)

    assert set(stems.keys()) == {STEM_DIALOGUE, STEM_MUSIC, STEM_EFFECTS}
    for stem in stems.values():
        assert stem.shape == mix.shape
        assert np.isfinite(stem).all()

    # Les masques sont complémentaires (somme = mix) — pas de perte d'énergie
    reconstructed = sum(stems.values())
    err = float(np.sqrt(np.mean((reconstructed - mix) ** 2)))
    assert err < 1e-4, f"mauvaise reconstruction des stems: RMSE={err}"

    # Le stem 'music' est très corrélé à la musique (stationnarité)
    # Le stem 'dialogue' est plus corrélé à la parole que le mix ne l'est
    _, speech, music, _ = _build_musical_mix()
    corr_dialogue = float(np.corrcoef(stems[STEM_DIALOGUE], speech)[0, 1])
    corr_mix_speech = float(np.corrcoef(mix, speech)[0, 1])
    assert corr_dialogue > corr_mix_speech
    assert float(np.corrcoef(stems[STEM_MUSIC], music)[0, 1]) > 0.8


def test_separation_improves_wer_vs_raw_mix():
    """Condition d'achèvement du goal : amélioration mesurable du WER."""
    mix, _, _, _ = _build_musical_mix()
    stems = SpectralMaskSeparator().separate(mix, SR)

    reference = "un deux trois"
    baseline = _benchmark_transcriber(mix)
    separated = _benchmark_transcriber(stems[STEM_DIALOGUE])

    wer_baseline = wer(reference, baseline)
    wer_separated = wer(reference, separated)
    comparison = compare_wer(reference, baseline, separated)

    # Démontrabilité : WER 0.33 sur le mix (mot « un » masqué) → 0.0 séparé
    assert baseline == "deux trois", (
        f"Le banc d'essai doit être trompé par la musique sur le mix brut "
        f"(attendu 'deux trois', obtenu {baseline!r})"
    )
    assert (
        separated == "un deux trois"
    ), f"La séparation doit restaurer la parole (obtenu {separated!r})"
    assert wer_separated < wer_baseline
    assert comparison["absolute_improvement"] > 0.0
    # Amélioration relative d'au moins 50 % (elle est en fait de 100 %)
    assert comparison["relative_improvement"] >= 0.5


def test_separate_file_writes_wav_stems(tmp_path):
    mix, _, _, _ = _build_musical_mix()
    wav_path = tmp_path / "mix.wav"
    save_wav(str(wav_path), mix, SR)

    sep = SpectralMaskSeparator()
    result = sep.separate_file(str(wav_path), output_dir=str(tmp_path / "out"))

    assert result.backend == "spectral"
    paths = getattr(result, "stem_paths")
    for name in (STEM_DIALOGUE, STEM_MUSIC, STEM_EFFECTS):
        assert os.path.exists(paths[name])
        data, data_sr = load_audio(paths[name])
        assert data_sr == SR
        assert data.size > 0


def test_get_separator_auto_falls_back_to_spectral(monkeypatch):
    monkeypatch.setenv("SOURCE_SEPARATION_BACKEND", "spectral")
    sep = get_separator()
    assert sep.name == "spectral"


def test_feature_flag_and_pipeline_option_integration(monkeypatch, tmp_path):
    """La séparation est pilotable par option de pipeline (§14.2.2)."""
    # Par défaut (auto sans FEATURE_*=1), elle est désactivée
    monkeypatch.delenv("SOURCE_SEPARATION_BACKEND", raising=False)
    monkeypatch.delenv("FEATURE_SOURCE_SEPARATION", raising=False)
    monkeypatch.delenv("FEATURE_FLAG_SOURCE_SEPARATION", raising=False)
    monkeypatch.delenv("ENABLE_SOURCE_SEPARATION", raising=False)
    assert is_separation_enabled() is False

    # L'option explicite du pipeline active la séparation
    monkeypatch.setenv("SOURCE_SEPARATION_BACKEND", "spectral")
    assert is_separation_enabled() is True

    # Tâche Celery exécutable en .run (sans broker)
    from app.tasks.source_separation import separate_sources

    mix, _, _, _ = _build_musical_mix()
    wav_path = tmp_path / "mix.wav"
    save_wav(str(wav_path), mix, SR)

    res = separate_sources.run(
        media_path=str(wav_path),
        output_dir=str(tmp_path / "stems"),
        backend="spectral",
    )
    assert res["status"] == "ok"
    assert os.path.exists(res["dialogue_path"])
    assert res["backend"] == "spectral"


def test_pipeline_uses_dialogue_stem_when_enabled(monkeypatch, tmp_path):
    """Intégration bout-en-bout : si activée, pipeline_extract_normalize produit
    un dialogue_path et pipeline_transcribe_diarize l'utilise pour la transcription.
    """
    monkeypatch.setenv("SOURCE_SEPARATION_BACKEND", "spectral")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    # Mix musical de test écrit en WAV (pas de ffmpeg requis : entrée WAV)
    mix, _, _, _ = _build_musical_mix()
    wav_path = tmp_path / "mix.wav"
    save_wav(str(wav_path), mix, SR)

    from app.tasks import pipeline as pipeline_mod

    captured = {}

    class _FakeTranscribe:
        def run(self, media_path, media_id):
            captured["transcript_input"] = media_path
            return {
                "media_id": str(media_id),
                "language": "fr",
                "segments_count": 1,
            }

    class _FakeDiarize:
        def run(self, media_path):
            captured["diarize_input"] = media_path
            return {"speakers": [], "status": "ok"}

    monkeypatch.setattr(pipeline_mod, "transcribe_audio", _FakeTranscribe())
    monkeypatch.setattr(pipeline_mod, "diarize_speakers", _FakeDiarize())
    # Pas de DB/silence service dans ce test
    monkeypatch.setattr(
        "app.services.silence_service.SilenceService.detect_and_persist_silences",
        lambda self, *a, **k: None,
        raising=False,
    )

    extract_result = pipeline_mod.pipeline_extract_normalize.run(
        media_path=str(wav_path),
        media_id="00000000-0000-0000-0000-000000000001",
        pipeline_options={
            "enable_source_separation": True,
            "source_separation_backend": "spectral",
        },
    )

    tracks = extract_result["extracted_tracks"]["tracks"]
    assert tracks, "au moins une piste extraite"
    dialogue_path = tracks[0].get("dialogue_path")
    assert dialogue_path and os.path.exists(
        dialogue_path
    ), "le stem dialogue doit être produit et exister sur disque"
    assert extract_result["source_separation"]["status"] == "ok"
    assert extract_result["source_separation"]["backend"] == "spectral"

    transcribe_result = pipeline_mod.pipeline_transcribe_diarize.run(extract_result)
    # La transcription/diarisation ont bien reçu le stem dialogue isolé
    assert captured["transcript_input"] == dialogue_path
    assert captured["diarize_input"] == dialogue_path
    assert transcribe_result["transcript_input_path"] == dialogue_path


def test_pipeline_skips_separation_when_disabled(monkeypatch, tmp_path):
    """Quand l'option est désactivée, le pipeline n'ajoute pas de stem dialogue."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    mix, _, _, _ = _build_musical_mix()
    wav_path = tmp_path / "mix.wav"
    save_wav(str(wav_path), mix, SR)

    from app.tasks import pipeline as pipeline_mod

    result = pipeline_mod.pipeline_extract_normalize.run(
        media_path=str(wav_path),
        media_id="00000000-0000-0000-0000-000000000002",
        pipeline_options={"enable_source_separation": False},
    )
    assert result["source_separation"]["status"] == "skipped"
    assert "dialogue_path" not in result["extracted_tracks"]["tracks"][0]
