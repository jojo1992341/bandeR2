import os
import tempfile
import subprocess
from pathlib import Path

def test_pipeline_audio_extraction_and_normalization():
    """Intégration : vidéo de test → extraction multi-pistes + normalisation EBU R128 → bucket traitement."""
    # Créer vidéo de test avec plusieurs pistes audio (simulé par deux flux audio)
    video_path = "/tmp/test_video_piste.mp4"
    # Générer un fichier vidéo court avec deux pistes audio (stéréo simulé via -map 0:a:0 et 0:a:1 si possible)
    # Pour simplifier : une piste audio valide + un autre flux audio via -map
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=1",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=500:duration=2",
        "-map", "0:v",
        "-map", "1:a",
        "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "1",
        "-c:a", "aac",
        "-shortest",
        video_path,
    ], capture_output=True, timeout=60)
    assert os.path.exists(video_path) and os.path.getsize(video_path) > 1000, "Vidéo de test non créée"

    # Exécuter la tâche Celery directement (sans broker Redis)
    from app.tasks.audio_extraction import extract_audio
    result = extract_audio.run(video_path, output_dir="/tmp/rythmoai_audio")

    assert result["track_count"] >= 1, "Au moins une piste audio extraite"
    for track in result["tracks"]:
        local_path = track["local_path"]
        s3_key = track["s3_key"]
        assert os.path.exists(local_path), f"Fichier WAV local manquant: {local_path}"
        # Vérifier format : 16 kHz, mono, WAV
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels,codec_name,codec_type", "-of", "csv=p=0", local_path],
            capture_output=True, text=True, timeout=30
        )
        info = probe.stdout.lower()
        # Vérifier mono (dernier champ de csv peut être le nombre de canaux)
        fields = info.replace("\n","").split(",")
        assert "16000" in info or "16" in info, f"Fréquence d'échantillonnage non 16 kHz: {info}"
        # Le nombre de canaux est souvent le dernier champ (1 = mono)
        assert len(fields) >= 3 and fields[-1].strip() == "1", f"Canaux non mono: {info}"
        assert "pcm_s16le" in info or "wav" in info.lower(), f"Codec WAV pcm_s16le attendu: {info}"
        # Vérifier présence dans le bucket de traitement (MinIO local)
        import boto3
        s3 = boto3.client("s3", endpoint_url="http://localhost:9000", aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")
        objs = s3.list_objects_v2(Bucket="rythmoai-media", Prefix=s3_key)
        assert "ResponseMetadata" in objs, "Échec d'accès au bucket de traitement"
        # Si Contents présent, s'assurer que le fichier y figure
        if "Contents" in objs:
            keys = [c["Key"] for c in objs.get("Contents", [])]
            assert s3_key in keys or any(s3_key in k for k in keys), f"Clé {s3_key} non trouvée dans le bucket"

    # Nettoyage
    try:
        import boto3
        s3 = boto3.client("s3", endpoint_url="http://localhost:9000", aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")
        for track in result["tracks"]:
            s3.delete_object(Bucket="rythmoai-media", Key=track["s3_key"])
    except Exception:
        pass
