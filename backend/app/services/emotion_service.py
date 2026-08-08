import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models import Replica, MediaAsset, Project, EmotionTag
from app.ai.emotion_detector import EmotionDetector
from app.core.logging import logger


class EmotionService:
    """
    Service de double analyse §8.2.5
    Orchestre :
      - analyse acoustique (wav2vec2) → émotion
      - analyse textuelle (NLP FR) → intention
    Persistance en EmotionTag, affichage indicatif,
    sans jamais modifier Replica.text (seulement codes typo suggérés).
    """

    def __init__(self, db: Session):
        self.db = db
        self.detector = EmotionDetector()

    def _get_audio_path_for_replica(self, replica: Replica, media: Optional[MediaAsset]) -> Optional[str]:
        if media and media.storage_path and self._file_exists(media.storage_path):
            return media.storage_path
        # Replica n'a pas de chemin propre ; on utilise le média parent
        return None

    @staticmethod
    def _file_exists(path: str) -> bool:
        import os
        try:
            return os.path.exists(path) and os.path.isfile(path)
        except Exception:
            return False

    def analyze_replica(
        self,
        replica: Replica,
        media: Optional[MediaAsset] = None,
        project: Optional[Project] = None,
        *,
        persist: bool = True,
    ) -> List[EmotionTag]:
        """
        Analyse UNE réplique et produit 1 à 2 EmotionTag :
          - tag_type 'emotion' source audio
          - tag_type 'intention' source texte
        Garantie : ne modifie JAMAIS replica.text
        """
        original_text = replica.text  # sauvegarde pour vérification
        audio_path = self._get_audio_path_for_replica(replica, media)
        text = replica.text or ""

        # Double analyse
        detection = self.detector.detect(audio_path=audio_path, text=text)
        emo = detection.get("emotion", {})
        intent = detection.get("intention", {})
        suggested = detection.get("suggested_typo_codes", {})

        # Capturer media/project si non fournis
        media_id = replica.media_id
        if media is not None:
            media_id = media.id
        project_id = None
        if project is not None:
            project_id = project.id
        elif media is not None:
            # déduire project via media
            try:
                # media.project_id déjà disponible
                project_id = getattr(media, "project_id", None)
            except Exception:
                project_id = None
        else:
            # fallback via DB lookup
            try:
                m = self.db.query(MediaAsset).filter(MediaAsset.id == replica.media_id).first()
                if m:
                    media_id = m.id
                    project_id = m.project_id
            except Exception:
                pass

        # Purge anciens tags de cette réplique (idempotence)
        if persist:
            self.db.query(EmotionTag).filter(EmotionTag.replica_id == replica.id).delete(synchronize_session=False)

        tags: List[EmotionTag] = []

        # Tag émotion (audio)
        emo_tag = EmotionTag(
            id=uuid.uuid4(),
            replica_id=replica.id,
            media_id=media_id,
            project_id=project_id,
            tag_type="emotion",
            label=emo.get("label", "neutre"),
            score=float(emo.get("score", 0.70)),
            source=emo.get("source", "audio"),
            suggested_typo_codes=suggested,
            details={
                "emotion": emo,
                "intention": intent,
                "audio_path": audio_path,
                "text_snapshot": text[:240],
            },
        )
        tags.append(emo_tag)

        # Tag intention (texte)
        intent_tag = EmotionTag(
            id=uuid.uuid4(),
            replica_id=replica.id,
            media_id=media_id,
            project_id=project_id,
            tag_type="intention",
            label=intent.get("label", "affirmation"),
            score=float(intent.get("score", 0.70)),
            source=intent.get("source", "texte"),
            suggested_typo_codes=suggested,
            details={
                "emotion": emo,
                "intention": intent,
                "text_snapshot": text[:240],
            },
        )
        tags.append(intent_tag)

        if persist:
            for t in tags:
                self.db.add(t)
            self.db.commit()
            for t in tags:
                self.db.refresh(t)

        # Vérification critique : le texte n'a pas été altéré
        # (recharger depuis DB pour s'assurer qu'aucune écriture n'a fuité)
        if persist:
            self.db.refresh(replica)
            assert replica.text == original_text, "EmotionService ne doit jamais modifier Replica.text"

        return tags

    def analyze_media_replicas(
        self,
        media_id: uuid.UUID,
        *,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Analyse toutes les répliques d'un média et persiste les EmotionTag.
        Retourne un résumé pour pipeline.
        """
        replicas: List[Replica] = (
            self.db.query(Replica).filter(Replica.media_id == media_id).order_by(Replica.order_index, Replica.start_ms).all()
        )
        if not replicas:
            return {"media_id": str(media_id), "replica_count": 0, "tags_created": 0, "status": "no_replicas"}

        media = self.db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
        project = None
        if media:
            project = self.db.query(Project).filter(Project.id == media.project_id).first()

        total_tags = 0
        for rep in replicas:
            # Sauvegarder texte avant
            original = rep.text
            tags = self.analyze_replica(rep, media=media, project=project, persist=persist)
            total_tags += len(tags)
            # Vérification post-analyse : texte inchangé
            assert rep.text == original, f"Réplique {rep.id} : text altéré pendant l'analyse émotionnelle"

        return {
            "media_id": str(media_id),
            "project_id": str(project.id) if project else None,
            "replica_count": len(replicas),
            "tags_created": total_tags,
            "status": "ok",
        }

    def analyze_project(
        self,
        project_id: uuid.UUID,
        *,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Analyse toutes les répliques d'un projet (tous médias).
        """
        media_ids = [m.id for m in self.db.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()]
        if not media_ids:
            # fallback : répliques sans média ? (devrait pas arriver)
            replicas = self.db.query(Replica).filter(Replica.media_id.in_(media_ids)).all() if media_ids else []
        else:
            replicas = self.db.query(Replica).filter(Replica.media_id.in_(media_ids)).order_by(Replica.order_index).all()

        total = 0
        per_media = []
        for mid in media_ids:
            res = self.analyze_media_replicas(mid, persist=persist)
            total += res.get("tags_created", 0)
            per_media.append(res)

        return {
            "project_id": str(project_id),
            "media_count": len(media_ids),
            "replica_count": len(replicas) if 'replicas' in locals() else sum(r["replica_count"] for r in per_media),
            "tags_created": total,
            "per_media": per_media,
            "status": "ok",
        }

    def list_by_replica(self, replica_id: uuid.UUID) -> List[EmotionTag]:
        return self.db.query(EmotionTag).filter(EmotionTag.replica_id == replica_id).order_by(EmotionTag.tag_type).all()

    def list_by_media(self, media_id: uuid.UUID) -> List[EmotionTag]:
        return self.db.query(EmotionTag).filter(EmotionTag.media_id == media_id).order_by(EmotionTag.created_at).all()

    def list_by_project(self, project_id: uuid.UUID) -> List[EmotionTag]:
        return self.db.query(EmotionTag).filter(EmotionTag.project_id == project_id).order_by(EmotionTag.created_at).all()

    @staticmethod
    def serialize(tag: EmotionTag) -> Dict[str, Any]:
        return {
            "id": str(tag.id),
            "replica_id": str(tag.replica_id),
            "media_id": str(tag.media_id) if tag.media_id else None,
            "project_id": str(tag.project_id) if tag.project_id else None,
            "tag_type": tag.tag_type,
            "label": tag.label,
            "score": float(tag.score) if tag.score is not None else 0.0,
            "source": tag.source,
            "suggested_typo_codes": tag.suggested_typo_codes or {},
            "details": tag.details or {},
            "created_at": tag.created_at.isoformat() if tag.created_at else None,
        }
