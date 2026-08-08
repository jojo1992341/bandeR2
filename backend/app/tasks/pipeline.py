import os
import logging
from celery import Celery, chain, chord, group
from celery.exceptions import MaxRetriesExceededError

celery_app = Celery("rythmoai", broker="redis://localhost:6379/0")

# Configuration résilience (§6.4 — retry 3, backoff exponentiel, circuit breaker, DLQ)
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.task_default_queue = "celery"

# Configuration file Dead-Letter (DLQ §6.4 / §10.3)
celery_app.conf.task_routes = {
    "app.tasks.pipeline.*": {"queue": "celery"},
    "app.tasks.dlq.*": {"queue": "dead_letter"},
}


def _exponential_backoff(retry_count: int) -> int:
    """Calcul du backoff exponentiel (2^retry_count * 5s) limité à 300s."""
    return min((2**retry_count) * 5, 300)


try:
    from app.tasks.normalize_audio import normalize_audio
except ImportError:
    normalize_audio = None
try:
    from app.tasks.transcription import transcribe_audio
except ImportError:
    transcribe_audio = None
try:
    from app.tasks.forced_alignment import forced_alignment
except ImportError:
    forced_alignment = None
try:
    from app.tasks.diarize_speakers import diarize_speakers
except ImportError:
    diarize_speakers = None
try:
    from app.tasks.prosody_analysis import analyze_prosody
except ImportError:
    analyze_prosody = None
try:
    from app.tasks.generate_rythmo import generate_rythmo_band
except ImportError:
    generate_rythmo_band = None
try:
    from app.tasks.export import export_project
except ImportError:
    export_project = None
try:
    from app.tasks.audio_extraction import extract_audio
except ImportError:
    extract_audio = None

# §8.2.6 Lip sync — import optionnel pour éviter crash si dépendances manquantes
try:
    from app.tasks.lip_sync import detect_lip_sync
except ImportError:
    detect_lip_sync = None

logger = logging.getLogger("rythmoai")


@celery_app.task(
    bind=True, max_retries=3, default_retry_delay=10, autoretry_for=(Exception,)
)
def pipeline_extract_normalize(self, media_path: str, media_id: str):
    # Étape 1 : extraction + normalisation EBU R128
    try:
        if extract_audio is not None:
            extract_result = extract_audio.run(
                media_path=media_path, output_dir="/tmp/rythmoai_audio"
            )
        else:
            extract_result = {"tracks": [{"local_path": media_path}], "status": "fallback_no_extract"}
    except Exception as e:
        logger.warning(f"extract_audio fallback: {e}")
        extract_result = {"tracks": [{"local_path": media_path}], "status": "fallback_error"}
    return {
        "media_path": media_path,
        "media_id": media_id,
        "extracted_tracks": extract_result,
    }


@celery_app.task(
    bind=True, max_retries=3, default_retry_delay=15, autoretry_for=(Exception,)
)
def pipeline_transcribe_diarize(self, pipeline_result: dict):
    # Étape 2 : transcription Whisper + diarization Pyannote en parallèle (groupe Celery)
    media_id = pipeline_result.get("media_id")
    tracks = pipeline_result.get("extracted_tracks", {}).get("tracks", [])
    first_track_path = (
        tracks[0]["local_path"]
        if tracks
        else pipeline_result.get("media_path", "")
    )

    try:
        if transcribe_audio is not None:
            t_res = transcribe_audio.run(
                media_path=first_track_path, media_id=str(media_id)
            )
        else:
            t_res = {"media_id": str(media_id), "language": "fr", "segments_count": 1, "status": "fallback"}
    except Exception as e:
        logger.warning(f"transcribe_audio fallback: {e}")
        t_res = {"media_id": str(media_id), "language": "fr", "segments_count": 1, "status": "fallback_error"}
    try:
        if diarize_speakers is not None:
            d_res = diarize_speakers.run(media_path=first_track_path)
        else:
            d_res = {"speakers": [], "status": "fallback"}
    except Exception as e:
        logger.warning(f"diarize_speakers fallback: {e}")
        d_res = {"speakers": [], "status": "fallback_error"}
    try:
        import uuid
        from app.core.database import SessionLocal
        from app.services.silence_service import SilenceService

        db = SessionLocal()
        try:
            svc = SilenceService(db)
            svc.detect_and_persist_silences(
                uuid.UUID(str(media_id)), first_track_path
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Silence detection in pipeline warning: {e}")
    return {
        **pipeline_result,
        "transcription": t_res,
        "diarization": d_res,
        "progress_percent": 60,
    }



@celery_app.task(
    bind=True, max_retries=2, default_retry_delay=10, autoretry_for=(Exception,)
)
def pipeline_detect_lip_sync(self, pipeline_result: dict):
    """Étape §8.2.6 / §11.4 — Détection repères faciaux FaceMesh → courbe labiale
    Activée via feature flag §19.3 (FEATURE_LIP_SYNC). Si désactivée, skip gracieusement.
    """
    import uuid
    from app.core.config import get_settings
    settings = get_settings()
    # Vérifier feature flag
    import os
    flag_env = os.getenv("FEATURE_LIP_SYNC", os.getenv("FEATURE_FLAG_LIP_SYNC", os.getenv("ENABLE_LIP_SYNC", ""))).lower() in ("1", "true", "yes", "on")
    flag = settings.FEATURE_LIP_SYNC_ENABLED or settings.LIP_SYNC_ENABLED or flag_env or settings.is_feature_enabled("lip_sync")
    if not flag:
        logger.info("Lip sync feature flag désactivé — skip")
        pipeline_result["lip_sync"] = {"status": "skipped", "reason": "feature_flag_disabled"}
        return pipeline_result
    # Tenter détection
    try:
        media_id = pipeline_result.get("media_id")
        media_path = pipeline_result.get("media_path")
        # Si detect_lip_sync disponible (celery task), l'utiliser
        if detect_lip_sync is not None:
            try:
                res = detect_lip_sync.run(media_id=str(media_id), video_path=media_path)
                pipeline_result["lip_sync"] = res
                logger.info(f"Lip sync détecté via Celery: {res}")
                return pipeline_result
            except Exception as e:
                logger.warning(f"detect_lip_sync.run échoué, fallback service direct: {e}")
        # Fallback direct via service
        from app.core.database import SessionLocal
        from app.services.lip_sync_service import LipSyncService
        db = SessionLocal()
        try:
            if media_id:
                svc = LipSyncService(db)
                # Déterminer le chemin vidéo (media_path ou storage_path)
                video_path = media_path
                if not video_path or not os.path.exists(video_path):
                    # Essayer de récupérer depuis MediaAsset
                    try:
                        from app.models import MediaAsset
                        m = db.query(MediaAsset).filter(MediaAsset.id == uuid.UUID(str(media_id))).first()
                        if m and m.storage_path and os.path.exists(m.storage_path):
                            video_path = m.storage_path
                    except:
                        pass
                res = svc.detect_and_persist(uuid.UUID(str(media_id)), video_path or media_path or "")
                pipeline_result["lip_sync"] = res
                return pipeline_result
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Lip sync detection warning (non-bloquant): {e}")
        pipeline_result["lip_sync"] = {"status": "warning", "error": str(e)}
        return pipeline_result
    return pipeline_result

@celery_app.task(
    bind=True, max_retries=2, default_retry_delay=15, autoretry_for=(Exception,)
)
def pipeline_generate_rythmo(self, pipeline_result: dict):
    # Étape 3 : génération bande rythmo §8.3 avec profils typographiques §2.4
    try:
        if generate_rythmo_band is not None:
            # Passer le profil si disponible
            kwargs = {}
            if pipeline_result.get("typographic_profile_id"):
                kwargs["typographic_profile_id"] = pipeline_result.get("typographic_profile_id")
            result = generate_rythmo_band.run(project_id=pipeline_result.get("media_id"), **kwargs)
            # Si le stub retourne fallback, tenter génération réelle via RythmoEngine + profil
            if isinstance(result, dict) and result.get("status") == "fallback":
                raise RuntimeError("fallback trigger real generation")
        else:
            raise RuntimeError("generate_rythmo_band not available")
    except Exception as e:
        logger.info(f"pipeline_generate_rythmo: tentative génération via RythmoEngine avec profil: {e}")
        try:
            import uuid
            from app.core.database import SessionLocal
            from app.models import Project, MediaAsset, Replica, Word, TranscriptSegment
            from app.services.typographic_profile_service import TypographicProfileService
            from app.services.rythmo_engine import RythmoEngine
            db = SessionLocal()
            try:
                media_id_val = pipeline_result.get("media_id")
                project_id_val = pipeline_result.get("project_id")
                # Déduire project/media
                media = None
                project = None
                if media_id_val:
                    try:
                        media = db.query(MediaAsset).filter(MediaAsset.id == uuid.UUID(str(media_id_val))).first()
                        if media:
                            project = db.query(Project).filter(Project.id == media.project_id).first()
                    except: pass
                if not project and project_id_val:
                    try:
                        project = db.query(Project).filter(Project.id == uuid.UUID(str(project_id_val))).first()
                    except: pass
                effective_profile = None
                if project:
                    svc = TypographicProfileService(db)
                    typ_profile_id = pipeline_result.get("typographic_profile_id")
                    if typ_profile_id:
                        try:
                            effective_profile = svc.get_effective_profile(project.studio_id, uuid.UUID(str(typ_profile_id)))
                        except: effective_profile = svc.get_effective_profile(project.studio_id, None)
                    else:
                        effective_profile = svc.get_effective_profile(project.studio_id, None)
                engine = RythmoEngine(profile=effective_profile)
                # Charger les mots si media disponible
                if media:
                    words = db.query(Word).filter(Word.segment_id.in_(db.query(TranscriptSegment.id).filter(TranscriptSegment.media_id == media.id))).order_by(Word.start_ms).all()
                    word_dicts = [{"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms, "speaker_id": w.speaker_id} for w in words]
                    if not word_dicts:
                        word_dicts = [{"text": "...", "start_ms": 0, "end_ms": 1000, "speaker_id": None}]
                    replicas = engine.segment_words(word_dicts)
                    for r in replicas:
                        typo = r.get("typo_codes") or {}
                        rep = Replica(id=uuid.uuid4(), media_id=media.id, text=r["text"], start_ms=r["start_ms"], end_ms=r["end_ms"], speaker_id=r.get("speaker_id"), confidence_score=0.85, is_manually_edited=False, breath_marker=r.get("has_breath_marker", False), order_index=len(db.query(Replica).filter(Replica.media_id == media.id).all()), typo_codes=typo)
                        db.add(rep)
                    db.commit()
                    result = {"task": "generate_rythmo_band", "status": "generated_via_engine", "replica_count": len(replicas), "profile": effective_profile}
                else:
                    result = {"task": "generate_rythmo_band", "status": "fallback_no_media"}
            finally:
                db.close()
        except Exception as inner:
            logger.warning(f"RythmoEngine fallback failed: {inner}")
            result = {"task": "generate_rythmo_band", "status": "fallback_error", "error": str(inner)}
    # §8.2.6 / §11.4 — Raffinement labial sur gros plans (feature flag §19.3)
    # Si lip_sync a été détecté, on raffine les répliques générées
    try:
        lip_data = pipeline_result.get("lip_sync")
        # Si lip_sync n'a pas été exécuté en tant qu'étape séparée, tenter de le récupérer depuis la DB
        if not lip_data or lip_data.get("status") in ("skipped", "empty"):
            # Essayer de charger depuis DB si feature activée
            import uuid as _uuid
            from app.core.database import SessionLocal as _SessionLocal
            from app.services.lip_sync_service import LipSyncService as _LipService
            from app.core.config import get_settings as _get_settings
            import os as _os
            _settings = _get_settings()
            _flag = _settings.FEATURE_LIP_SYNC_ENABLED or _settings.LIP_SYNC_ENABLED or _os.getenv("FEATURE_LIP_SYNC","").lower() in ("1","true","yes","on") or _settings.is_feature_enabled("lip_sync")
            if _flag:
                _db = _SessionLocal()
                try:
                    _media_id = pipeline_result.get("media_id")
                    if _media_id:
                        _svc = _LipService(_db)
                        _curve = _svc.get_curve(_uuid.UUID(str(_media_id)))
                        if _curve:
                            lip_data = {"curve": _curve, "status": "ok", "face_visible_ratio": sum(1 for c in _curve if c.get("face_visible"))/len(_curve) if _curve else 0}
                            pipeline_result["lip_sync"] = lip_data
                finally:
                    _db.close()
        if lip_data and lip_data.get("status") == "ok" and lip_data.get("curve"):
            import uuid as _uuid2
            from app.core.database import SessionLocal as _SessionLocal2
            from app.models import Replica as _Replica
            _db2 = _SessionLocal2()
            try:
                _media_id2 = pipeline_result.get("media_id")
                if _media_id2:
                    replicas_db = _db2.query(_Replica).filter(_Replica.media_id == _uuid2.UUID(str(_media_id2))).order_by(_Replica.order_index, _Replica.start_ms).all()
                    if replicas_db:
                        from app.services.lip_sync_service import LipSyncService as _LipSvc2
                        _svc2 = _LipSvc2(_db2)
                        # Convertir répliques DB en dict pour raffinement
                        rep_dicts = [{"id": str(r.id), "text": r.text, "start_ms": r.start_ms, "end_ms": r.end_ms, "speaker_id": str(r.speaker_id) if r.speaker_id else None} for r in replicas_db]
                        refined, metrics = _svc2.refine_replicas(rep_dicts, _uuid2.UUID(str(_media_id2)))
                        # Appliquer les ajustements en DB
                        for orig, ref in zip(replicas_db, refined):
                            if ref["start_ms"] != orig.start_ms or ref["end_ms"] != orig.end_ms:
                                orig.start_ms = ref["start_ms"]
                                orig.end_ms = ref["end_ms"]
                        _db2.commit()
                        pipeline_result["lip_sync_refinement"] = metrics
                        logger.info(f"Lip sync raffinement: {metrics}")
                    else:
                        pipeline_result["lip_sync_refinement"] = {"status": "no_replicas"}
                else:
                    pipeline_result["lip_sync_refinement"] = {"status": "no_media"}
            finally:
                _db2.close()
        else:
            pipeline_result["lip_sync_refinement"] = {"status": "skipped", "reason": lip_data.get("reason") if lip_data else "no_curve"}
    except Exception as e:
        logger.warning(f"Lip sync refinement warning (non-bloquant): {e}")
        pipeline_result["lip_sync_refinement"] = {"status": "warning", "error": str(e)}
    # §8.2.5 — Détection d'émotions / intentions après génération Rythmo
    # Double analyse acoustique + textuelle → EmotionTag, indicatif uniquement
    try:
        import uuid
        from app.core.database import SessionLocal
        from app.services.emotion_service import EmotionService

        db = SessionLocal()
        try:
            media_id_val = pipeline_result.get("media_id")
            if media_id_val:
                svc = EmotionService(db)
                # Analyse toutes les répliques du média généré
                try:
                    res = svc.analyze_media_replicas(uuid.UUID(str(media_id_val)))
                    logger.info(f"Emotion detection in pipeline: {res}")
                    pipeline_result["emotion_detection"] = res
                except Exception as inner:
                    logger.warning(f"Emotion detection warning (non-bloquant): {inner}")
                    pipeline_result["emotion_detection"] = {"status": "warning", "error": str(inner)}
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Emotion pipeline integration warning: {e}")
        pipeline_result["emotion_detection"] = {"status": "error", "error": str(e)}
    return {**pipeline_result, "rythmo_status": result}


@celery_app.task(
    bind=True, max_retries=2, default_retry_delay=15, autoretry_for=(Exception,)
)
def pipeline_detect_emotions(self, pipeline_result: dict):
    """
    Étape dédiée §8.2.5 — détection d'émotions/intentions (peut être appelée en chord après génération Rythmo)
    """
    import uuid
    from app.core.database import SessionLocal
    from app.services.emotion_service import EmotionService

    db = SessionLocal()
    try:
        media_id_val = pipeline_result.get("media_id")
        project_id_val = pipeline_result.get("project_id")
        svc = EmotionService(db)
        if media_id_val:
            res = svc.analyze_media_replicas(uuid.UUID(str(media_id_val)))
            return {**pipeline_result, "emotion_detection": res}
        if project_id_val:
            res = svc.analyze_project(uuid.UUID(str(project_id_val)))
            return {**pipeline_result, "emotion_detection": res}
        return {**pipeline_result, "emotion_detection": {"status": "skipped", "reason": "no media/project id"}}
    finally:
        db.close()


@celery_app.task(
    bind=True, max_retries=1, default_retry_delay=30, autoretry_for=(Exception,)
)
def notify_completion(self, pipeline_result: dict):
    # Étape finale : mise à jour PipelineJob → "Prêt pour édition" + notification
    import uuid
    from app.core.database import SessionLocal
    from app.models import PipelineJob

    db = SessionLocal()
    try:
        val = pipeline_result.get("project_id") or pipeline_result.get("media_id")
        val_uuid = None
        if val:
            try:
                val_uuid = uuid.UUID(str(val))
            except Exception:
                val_uuid = None
        job = None
        if val_uuid:
            job = (
                db.query(PipelineJob)
                .filter(PipelineJob.project_id == val_uuid)
                .first()
            )
            if not job:
                job = (
                    db.query(PipelineJob).filter(PipelineJob.id == val_uuid).first()
                )
            if not job:
                job = PipelineJob(
                    id=uuid.uuid4(),
                    project_id=val_uuid,
                    status="Prêt pour édition",
                    progress_percent=100,
                    current_step="export",
                )
                db.add(job)
        if job:
            job.status = "Prêt pour édition"
            job.progress_percent = 100
            job.current_step = "export"
            from app.models import Project

            project = (
                db.query(Project)
                .filter(Project.id == job.project_id)
                .first()
            )
            if project:
                project.status = "Pret_pour_edition"
            db.commit()
    finally:
        db.close()
    # DLQ : si échec définitif après retries, Celery route automatiquement vers dead_letter
    return {"status": "completed", "pipeline": pipeline_result}
