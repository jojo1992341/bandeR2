"""
Séparation de sources (dialogue / musique / effets) — §12.1 / V2

Lorsque le fichier fourni est un mixage complet, la transcription peut être
dégradée par une musique ou des effets forts (cf. §24.2). Ce module isole la
piste « dialogue » avant envoi au moteur de transcription pour améliorer le
WER.

Architecture :
    SourceSeparator (ABC)
        ├── SpectralMaskSeparator   — ségrégation temps/fréquence pure numpy/scipy,
        │                             sans dépendance lourde (utilisée en CI/tests)
        └── DemucsSeparator          — backend optionnel (demucs/torch), chargé à
                                      la demande uniquement si disponible

Le moteur est sélectionnable via la variable d'environnement
``SOURCE_SEPARATION_BACKEND`` (``auto`` | ``demucs`` | ``spectral`` | ``off``).
Le module reste importable même si ni demucs ni torch ne sont installés.
"""

from __future__ import annotations

import logging
import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("rythmoai")

# Fréquence d'échantillonnage cible du pipeline (§13.1 : 16 kHz mono)
TARGET_SR = 16000

# Noms de stems normalisés
STEM_DIALOGUE = "dialogue"
STEM_MUSIC = "music"
STEM_EFFECTS = "effects"


@dataclass
class SeparationResult:
    """Résultat d'une séparation de sources."""

    stems: Dict[str, np.ndarray] = field(default_factory=dict)
    sample_rate: int = TARGET_SR
    backend: str = "unknown"
    input_path: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)

    @property
    def dialogue(self) -> Optional[np.ndarray]:
        return self.stems.get(STEM_DIALOGUE)

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "stems": sorted(self.stems.keys()),
            "sample_rate": self.sample_rate,
            "metrics": self.metrics,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Chargement audio (WAV via wave / scipy; fallback av si disponible)
# ─────────────────────────────────────────────────────────────────────────────
def load_audio(path: str, target_sr: int = TARGET_SR) -> Tuple[np.ndarray, int]:
    """Charge un fichier audio en mono float32, ré-échantillonné si besoin.

    Implémentation défensive : dépend de ``wave`` (bibliothèque standard) pour
    les WAV PCM et de ``scipy.signal.resample_poly`` pour le ré-échantillonnage.
    """
    sr = None
    samples = None

    # 1) WAV PCM via la lib standard (le plus fiable en CI sans ffmpeg)
    try:
        import wave

        with wave.open(path, "rb") as wf:
            sr = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(sampwidth)
        if dtype is None:
            raise ValueError(f"sample width non géré: {sampwidth}")
        data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        if dtype == np.uint8:
            data = (data - 128.0) / 128.0
        elif dtype == np.int16:
            data = data / 32768.0
        elif dtype == np.int32:
            data = data / 2147483648.0
        if n_channels > 1:
            data = data.reshape(-1, n_channels).mean(axis=1)
        samples = data
    except Exception as exc:  # pragma: no cover - chemin alternatif
        logger.debug("wave.open indisponible pour %s: %s", path, exc)

    # 2) Fallback PyAV (mp4/mov/aac…)
    if samples is None:
        import av  # type: ignore

        with av.open(path) as container:
            audio_stream = next(
                (s for s in container.streams if s.type == "audio"), None
            )
            if audio_stream is None:
                raise ValueError(f"aucun flux audio dans {path}")
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=target_sr)
            chunks: List[np.ndarray] = []
            for frame in container.decode(audio_stream):
                for r in resampler.resample(frame):
                    chunks.append(r.to_ndarray().reshape(-1))
            samples = np.concatenate(chunks).astype(np.float32)
            sr = target_sr

    # Ré-échantillonnage si nécessaire
    if sr != target_sr:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(int(sr), int(target_sr))
        samples = resample_poly(samples, target_sr // g, sr // g).astype(np.float32)
        sr = target_sr

    # Normalisation défensive contre les clics/NaN
    if not np.isfinite(samples).all():
        samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    return samples, int(sr)


def save_wav(path: str, samples: np.ndarray, sr: int = TARGET_SR) -> str:
    """Écrit un WAV PCM 16 bits mono."""
    import wave

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Interface
# ─────────────────────────────────────────────────────────────────────────────
class SourceSeparator(ABC):
    """Interface de séparation de sources (§12.1)."""

    name: str = "base"

    @abstractmethod
    def separate(self, audio: np.ndarray, sr: int) -> Dict[str, np.ndarray]:
        """Retourne un dict ``{dialogue, music, effects}`` de mêmes forme/fréquence."""

    def separate_file(
        self, input_path: str, output_dir: str, basename: Optional[str] = None
    ) -> SeparationResult:
        samples, sr = load_audio(input_path)
        stems = self.separate(samples, sr)

        os.makedirs(output_dir, exist_ok=True)
        stem_paths: Dict[str, str] = {}
        root = basename or os.path.splitext(os.path.basename(input_path))[0]
        for name, stem in stems.items():
            out_path = os.path.join(output_dir, f"{root}_{name}.wav")
            save_wav(out_path, stem, sr)
            stem_paths[name] = out_path

        # Métrique simple: atténuation RMS relative de la musique sur dialogue
        metrics = {}
        dialogue = stems.get(STEM_DIALOGUE)
        music = stems.get(STEM_MUSIC)
        effects = stems.get(STEM_EFFECTS)
        if dialogue is not None and music is not None:
            metrics["dialogue_rms"] = float(np.sqrt(np.mean(dialogue**2) + 1e-12))
            metrics["music_rms"] = float(np.sqrt(np.mean(music**2) + 1e-12))
            if metrics["music_rms"] > 0:
                metrics["music_attenuation_db"] = float(
                    20.0
                    * math.log10(
                        (metrics["dialogue_rms"] + 1e-12) / metrics["music_rms"]
                    )
                )

        result = SeparationResult(
            stems=stems,
            sample_rate=sr,
            backend=self.name,
            input_path=input_path,
            metrics=metrics,
        )
        result.stem_paths = stem_paths  # type: ignore[attr-defined]
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Séparateur spectral (repose sur des hypothèses de production robustes)
# ─────────────────────────────────────────────────────────────────────────────
class SpectralMaskSeparator(SourceSeparator):
    """Séparateur temps/fréquence sans dépendance lourde.

    Stratégie inspirée des pratiques de prétraitement de la parole :

    * **Dialogue** — filtrage spectral passe-bande modulé par la présence de
      parole (énergie dans la bande 300 Hz–4 kHz), réduction des composantes
      stationnaires (souvent la musique/effets) par soustraction du bruit
      estimé sur les trèses les moins énergétiques, et atténuation des
      transitoires courtes (percussions/effets).
    * **Musique** — composantes stationnaires et basses fréquences (< 300 Hz) +
      hautes fréquences harmoniques persistantes.
    * **Effets** — transitoires courtes isolées (le reste du signal).

    L'algorithme est déterministe et donc testable. Il ne rivalise pas avec un
    modèle profond mais fournit un comportement V2 intégrable au pipeline, avec
    un backend Demucs optionnel pour la production.
    """

    name = "spectral"

    def __init__(
        self,
        n_fft: int = 1024,
        hop_length: int = 256,
        speech_low: float = 200.0,
        speech_high: float = 5000.0,
        stationary_quantile: float = 0.25,
        transient_ms: float = 60.0,
    ) -> None:
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.speech_low = speech_low
        self.speech_high = speech_high
        self.stationary_quantile = stationary_quantile
        self.transient_ms = transient_ms

    def separate(self, audio: np.ndarray, sr: int) -> Dict[str, np.ndarray]:
        if audio.ndim != 1:
            audio = audio.mean(axis=0)
        audio = audio.astype(np.float32, copy=False)

        from scipy import signal

        # STFT
        f, t, Zxx = signal.stft(
            audio,
            fs=sr,
            window="hann",
            nperseg=self.n_fft,
            noverlap=self.n_fft - self.hop_length,
            boundary="zeros",
        )
        magnitude = np.abs(Zxx)
        phase = np.exp(1j * np.angle(Zxx))
        power = magnitude**2

        n_freq = magnitude.shape[0]
        freqs = np.fft.rfftfreq(self.n_fft, d=1.0 / sr)

        # 1) Masque « parole » dans la bande vocale
        speech_band = (freqs >= self.speech_low) & (freqs <= self.speech_high)
        speech_energy = power[speech_band, :].mean(axis=0)
        # Lissage temporel pour stabiliser le masque
        win = max(3, int(0.05 * sr / self.hop_length))
        if win % 2 == 0:
            win += 1
        speech_energy_smooth = np.convolve(
            speech_energy, np.ones(win) / win, mode="same"
        )
        speech_thresh = np.quantile(speech_energy_smooth, 0.30)
        speech_present = (speech_energy_smooth > speech_thresh).astype(np.float32)
        # Éviter les transitions agressives
        speech_present = np.convolve(speech_present, np.ones(win) / win, mode="same")
        speech_present = np.clip(speech_present, 0.0, 1.0)

        # 2) Estimation du bruit stationnaire (musique/effets de fond)
        # Sur chaque fréquence, on prend le quantile bas temporel comme bruit.
        noise_floor = np.quantile(power, self.stationary_quantile, axis=1)
        noise_floor = np.maximum(noise_floor, 1e-10)

        # 3) Masque dialogue : énergie > bruit stationnaire, dans la bande vocale,
        #    pondéré par la présence de parole.
        snr = power / noise_floor[:, None]
        dialogue_mask = 1.0 / (1.0 + np.exp(-(snr - 1.5) * 1.2))  # sigmoïde douce
        band_weight = np.ones(n_freq, dtype=np.float32)
        band_weight[freqs < self.speech_low] = 0.15
        band_weight[freqs > self.speech_high] = 0.35
        dialogue_mask = (
            dialogue_mask
            * band_weight[:, None]
            * (0.35 + 0.65 * speech_present[None, :])
        )
        dialogue_mask = np.clip(dialogue_mask, 0.0, 1.0)

        # 4) Masque transitoires (effets) : pics d'énergie brefs au-dessus du trend
        frame_rms = np.sqrt(power.mean(axis=0) + 1e-12)
        trend = np.convolve(frame_rms, np.ones(win) / win, mode="same")
        transient_ratio = frame_rms / (trend + 1e-9)
        transient_frames = (transient_ratio > 2.0).astype(np.float32)
        # Étendre le masque sur ±transient_ms
        extend = max(1, int((self.transient_ms / 1000.0) * sr / self.hop_length))
        kernel = np.ones(2 * extend + 1)
        transient_frames = np.convolve(transient_frames, kernel, mode="same")
        transient_frames = np.clip(transient_frames, 0.0, 1.0)

        # Les effets = transitoires hors zone de parole
        effects_mask = transient_frames[None, :] * (1.0 - speech_present[None, :])
        # Renforcer les hautes fréquences pour les effets
        effects_mask = effects_mask * np.where(freqs > 2000, 1.0, 0.4)[:, None]
        effects_mask = np.clip(effects_mask, 0.0, 0.9)

        # 5) Masque musique : stationnarité, basse/harmonie persistante hors parole
        stationarity = noise_floor[:, None] / (power + 1e-9)
        music_mask = np.clip(stationarity * 1.5, 0.0, 1.0)
        # La musique est plus présente hors parole
        music_mask *= 1.0 - 0.6 * speech_present[None, :]
        # On retire ce qui est très clairement dialogue ou effets
        music_mask *= 1.0 - 0.8 * dialogue_mask
        music_mask *= 1.0 - 0.7 * effects_mask
        # Basses fréquences souvent musicales
        music_mask[freqs < 250, :] = np.maximum(
            music_mask[freqs < 250, :], 0.4 * (1.0 - speech_present[None, :])
        )
        music_mask = np.clip(music_mask, 0.0, 1.0)

        # Normalisation pour que la somme des masques ≈ 1 (reconstruction parfaite)
        total = dialogue_mask + music_mask + effects_mask
        total = np.maximum(total, 1e-9)
        dialogue_mask /= total
        music_mask /= total
        effects_mask /= total

        # Reconstruction
        def _istft(mask: np.ndarray) -> np.ndarray:
            _, reconstructed = signal.istft(
                Zxx * mask,
                fs=sr,
                window="hann",
                nperseg=self.n_fft,
                noverlap=self.n_fft - self.hop_length,
                input_onesided=True,
            )
            # Aligner la longueur avec l'entrée
            if reconstructed.shape[0] > audio.shape[0]:
                reconstructed = reconstructed[: audio.shape[0]]
            elif reconstructed.shape[0] < audio.shape[0]:
                reconstructed = np.pad(
                    reconstructed, (0, audio.shape[0] - reconstructed.shape[0])
                )
            return reconstructed.astype(np.float32)

        return {
            STEM_DIALOGUE: _istft(dialogue_mask),
            STEM_MUSIC: _istft(music_mask),
            STEM_EFFECTS: _istft(effects_mask),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Backend Demucs (optionnel)
# ─────────────────────────────────────────────────────────────────────────────
class DemucsSeparator(SourceSeparator):
    """Backend de séparation utilisant demucs (HT-Demucs / MDX).

    Demucs sépare en ``drums/bass/other/vocals``; nous remappons :
        vocals  -> dialogue
        bass+other (hors vocals) -> music
        drums   -> effects

    Chargé à la demande pour ne pas imposer torch en CI.
    """

    name = "demucs"

    def __init__(self, model_name: str = "htdemucs", device: str = "cpu") -> None:
        self.model_name = model_name or os.getenv("DEMUCS_MODEL", "htdemucs")
        self.device = device
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import torch  # type: ignore
            from demucs.pretrained import get_model  # type: ignore

            self._device = self.device or (
                "cuda" if torch.cuda.is_available() else "cpu"
            )
            self._model = get_model(self.model_name)
            self._model.to(self._device)
            self._model.eval()
            self._torch = torch
            return self._model
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Demucs non disponible : installez demucs/torch ou utilisez "
                "SOURCE_SEPARATION_BACKEND=spectral"
            ) from exc

    def separate(
        self, audio: np.ndarray, sr: int
    ) -> Dict[str, np.ndarray]:  # pragma: no cover - backend lourd
        import torch

        model = self._load()
        # demucs attend 44.1 kHz stereo; on resample via son approche interne
        ref_sr = getattr(model.samplerate, "item", lambda: model.samplerate)()
        audio_t = torch.from_numpy(audio).float().to(self._device)
        if audio_t.ndim == 1:
            audio_t = audio_t.unsqueeze(0).repeat(2, 1)
        # Ré-échantillonnage simple si besoin
        if sr != ref_sr:
            audio_t = torch.nn.functional.interpolate(
                audio_t.unsqueeze(0),
                scale_factor=ref_sr / sr,
                mode="linear",
                align_corners=False,
            ).squeeze(0)

        from demucs.apply import apply_model  # type: ignore

        with torch.no_grad():
            out = apply_model(model, audio_t.unsqueeze(0), device=self._device)[0]
        sources = {name: out[i] for i, name in enumerate(model.sources)}

        vocals = sources.get("vocals", torch.zeros_like(audio_t))
        if vocals.ndim > 1:
            vocals = vocals.mean(0)
        drums = sources.get("drums", torch.zeros_like(audio_t))
        if drums.ndim > 1:
            drums = drums.mean(0)
        bass = sources.get("bass", torch.zeros_like(audio_t))
        other = sources.get("other", torch.zeros_like(audio_t))
        music = bass + other
        if music.ndim > 1:
            music = music.mean(0)

        # Revenir à la fréquence cible
        def _to_np(x):
            x = x.float().cpu().numpy()
            if ref_sr != sr:
                from scipy.signal import resample_poly

                from math import gcd

                g = gcd(int(ref_sr), int(sr))
                x = resample_poly(x, sr // g, ref_sr // g)
            return x.astype(np.float32)

        return {
            STEM_DIALOGUE: _to_np(vocals),
            STEM_MUSIC: _to_np(music),
            STEM_EFFECTS: _to_np(drums),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Fabrique
# ─────────────────────────────────────────────────────────────────────────────
def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")


def is_separation_enabled() -> bool:
    """Indique si la séparation de sources est activée (§12.1, option pipeline)."""
    backend = os.getenv("SOURCE_SEPARATION_BACKEND", "auto").lower()
    if backend in ("off", "false", "0", "no", "disabled"):
        return False
    # Flags explicites gardés pour rétro-compatibilité
    if _env_flag("FEATURE_SOURCE_SEPARATION") or _env_flag(
        "FEATURE_FLAG_SOURCE_SEPARATION"
    ):
        return True
    if backend in ("spectral", "demucs"):
        return True
    # auto : activable via feature flag uniquement
    return _env_flag("ENABLE_SOURCE_SEPARATION")


def get_separator(backend: Optional[str] = None) -> SourceSeparator:
    """Instancie le séparateur configuré.

    Ordre de résolution :
      1. argument ``backend`` explicite
      2. variable d'env ``SOURCE_SEPARATION_BACKEND``
      3. ``auto`` → Demucs si disponible, sinon spectral
    """
    chosen = (backend or os.getenv("SOURCE_SEPARATION_BACKEND", "auto")).lower()
    if chosen == "off":
        raise RuntimeError("Source separation désactivée (backend=off)")
    if chosen == "demucs":
        return DemucsSeparator()
    if chosen == "spectral":
        return SpectralMaskSeparator()
    # auto
    try:
        import importlib

        importlib.import_module("demucs")
        importlib.import_module("torch")
        return DemucsSeparator()
    except Exception:
        return SpectralMaskSeparator()


def separate_dialogue(
    input_path: str,
    output_path: Optional[str] = None,
    output_dir: str = "/tmp/rythmoai_separation",
    backend: Optional[str] = None,
) -> Tuple[str, SeparationResult]:
    """Raccourci pipeline : isole le dialogue et retourne (chemin_wav, résultat).

    Peut être appelé directement par la tâche de pipeline.
    """
    sep = get_separator(backend)
    result = sep.separate_file(input_path, output_dir=output_dir)
    path = getattr(result, "stem_paths", {}).get(STEM_DIALOGUE)
    if output_path and path and os.path.abspath(output_path) != os.path.abspath(path):
        import shutil

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        shutil.copyfile(path, output_path)
        path = output_path
    if path is None:
        raise RuntimeError("Séparation: stem dialogue introuvable")
    return path, result
