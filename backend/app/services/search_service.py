"""
Service de recherche full-text §16.1
- PostgreSQL full-text search (to_tsvector french + GIN) avec fallback SQLite LIKE
- Recherche dans TranscriptSegment.text, Word.text, Replica.text
- Option Meilisearch/OpenSearch si volume le justifie (documenté, non activé par défaut)
"""
import time
import re
import uuid
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_, text, select
from sqlalchemy.sql import column
from app.models import Studio, Project, MediaAsset, TranscriptSegment, Word, Replica, Speaker
from app.core.database import engine

# Détection si PostgreSQL (pour utiliser tsvector)
IS_POSTGRES = engine.dialect.name == "postgresql" if engine else False

# Pour Meilisearch/OpenSearch : si les env vars sont définies et volume > seuil, on pourrait basculer.
# Pour l'instant, on documente l'option mais on utilise la recherche native.
USE_EXTERNAL_SEARCH = False

def _is_postgres_db(db: Session) -> bool:
    try:
        return db.bind.dialect.name == "postgresql" if db.bind else IS_POSTGRES
    except:
        return IS_POSTGRES

def _normalize_query(query: str) -> str:
    # Nettoie la requête : trim, enlève les caractères spéciaux dangereux pour tsquery
    query = query.strip()
    # Pour LIKE, on garde tel quel. Pour tsquery, on échappe les caractères spéciaux
    return query

def _build_tsquery(query: str) -> str:
    # Transforme "bonjour monde" en "bonjour & monde" pour tsquery plainto_tsquery
    # On enlève les caractères non alphanumériques sauf espaces et on remplace espaces par &
    cleaned = re.sub(r"[^\w\sàâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ']", " ", query, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    # Pour plainto_tsquery, on peut simplement passer la phrase
    # Pour to_tsquery, on joint par &
    tokens = cleaned.split()
    # Filtrer les tokens trop courts (<2) sauf si c'est un mot complet
    tokens = [t for t in tokens if len(t) >= 2]
    if not tokens:
        tokens = cleaned.split()
    return " & ".join(tokens) if tokens else cleaned

class SearchService:
    def __init__(self, db: Session):
        self.db = db

    def search(
        self,
        studio_id: uuid.UUID,
        query: str,
        limit: int = 20,
        offset: int = 0,
        include_replicas: bool = True,
        include_transcripts: bool = True,
        rank_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Recherche full-text dans l'ensemble des projets d'un studio.
        - Si PostgreSQL : utilise to_tsvector('french', ...) @@ plainto_tsquery('french', ...)
        - Sinon (SQLite) : utilise ILIKE %query% avec lower()
        Retourne : projets et répliques pertinents, avec highlights et latence.
        """
        start_time = time.time()
        query = _normalize_query(query)
        if not query or len(query.strip()) < 2:
            return {
                "query": query,
                "studio_id": str(studio_id),
                "projects": [],
                "replicas": [],
                "transcripts": [],
                "total_projects": 0,
                "total_replicas": 0,
                "total_transcripts": 0,
                "latency_ms": 0,
                "engine": "none",
                "took_ms": 0,
            }

        is_pg = _is_postgres_db(self.db)
        projects_found: List[Dict[str, Any]] = []
        replicas_found: List[Dict[str, Any]] = []
        transcripts_found: List[Dict[str, Any]] = []

        # Récupérer les projets du studio
        projects = self.db.query(Project).filter(Project.studio_id == studio_id).all()
        project_ids = [p.id for p in projects]
        if not project_ids:
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "query": query,
                "studio_id": str(studio_id),
                "projects": [],
                "replicas": [],
                "transcripts": [],
                "total_projects": 0,
                "total_replicas": 0,
                "total_transcripts": 0,
                "latency_ms": latency_ms,
                "engine": "postgres" if is_pg else "sqlite",
                "took_ms": latency_ms,
            }

        # Récupérer les media_ids pour ces projets
        media_ids = [m.id for m in self.db.query(MediaAsset.id).filter(MediaAsset.project_id.in_(project_ids)).all()]

        # Recherche dans les répliques
        if include_replicas and media_ids:
            if is_pg:
                # PostgreSQL full-text search
                try:
                    ts_query = _build_tsquery(query)
                    # Utiliser plainto_tsquery pour plus de tolérance
                    # On fait une requête avec ts_rank pour le tri
                    # Note : on utilise text() pour éviter les problèmes de compilation
                    # Recherche sur Replica.text
                    # On utilise une requête brute pour profiter de l'index GIN
                    # Fallback en LIKE si pas de résultats
                    replicas_q = self.db.query(Replica).filter(Replica.media_id.in_(media_ids))
                    # Filtre via to_tsvector
                    # On utilise ilike comme fallback si tsquery échoue (ex: si pas d'index)
                    # Pour l'instant, on fait un filtre hybride : d'abord ts_vector, puis ilike si 0 résultats
                    # On essaie la recherche tsvector
                    try:
                        # Utiliser func pour générer la requête
                        # to_tsvector('french', text) @@ plainto_tsquery('french', :query)
                        ts_vector = func.to_tsvector('french', Replica.text)
                        ts_q = func.plainto_tsquery('french', query)
                        filtered = replicas_q.filter(ts_vector.op('@@')(ts_q))
                        # Ordonner par rank
                        ranked = filtered.order_by(func.ts_rank(ts_vector, ts_q).desc())
                        results = ranked.offset(offset).limit(limit).all()
                        if not results:
                            # Fallback LIKE
                            like_pattern = f"%{query.lower()}%"
                            results = self.db.query(Replica).filter(Replica.media_id.in_(media_ids), func.lower(Replica.text).like(like_pattern)).offset(offset).limit(limit).all()
                        else:
                            # Si on a des résultats tsvector, on les utilise
                            pass
                    except Exception as e:
                        # Fallback LIKE en cas d'erreur (ex: pas d'extension french)
                        like_pattern = f"%{query.lower()}%"
                        results = self.db.query(Replica).filter(Replica.media_id.in_(media_ids), func.lower(Replica.text).like(like_pattern)).offset(offset).limit(limit).all()
                except Exception:
                    like_pattern = f"%{query.lower()}%"
                    results = self.db.query(Replica).filter(Replica.media_id.in_(media_ids), func.lower(Replica.text).like(like_pattern)).offset(offset).limit(limit).all()
            else:
                # SQLite : LIKE insensible à la casse
                like_pattern = f"%{query.lower()}%"
                results = self.db.query(Replica).filter(Replica.media_id.in_(media_ids), func.lower(Replica.text).like(like_pattern)).offset(offset).limit(limit).all()

            # Pour chaque réplique, trouver son projet et ajouter highlight
            for r in results:
                # Trouver le media et le projet
                media = self.db.query(MediaAsset).filter(MediaAsset.id == r.media_id).first()
                project = self.db.query(Project).filter(Project.id == media.project_id).first() if media else None
                # Highlight simple : entourer le match de <mark>
                highlighted = self._highlight(r.text, query)
                replicas_found.append({
                    "id": str(r.id),
                    "media_id": str(r.media_id),
                    "project_id": str(project.id) if project else None,
                    "project_title": project.title if project else None,
                    "text": r.text,
                    "highlighted": highlighted,
                    "start_ms": r.start_ms,
                    "end_ms": r.end_ms,
                    "order_index": r.order_index,
                    "typo_codes": r.typo_codes or {},
                    "speaker_id": str(r.speaker_id) if r.speaker_id else None,
                    "confidence_score": float(r.confidence_score) if r.confidence_score is not None else None,
                    "rank": self._compute_rank(r.text, query),
                })

            # Compter total pour pagination
            if is_pg:
                try:
                    total_replicas = self.db.query(Replica).filter(Replica.media_id.in_(media_ids), func.lower(Replica.text).like(f"%{query.lower()}%")).count()
                except:
                    total_replicas = len(replicas_found)
            else:
                total_replicas = self.db.query(Replica).filter(Replica.media_id.in_(media_ids), func.lower(Replica.text).like(f"%{query.lower()}%")).count()
        else:
            total_replicas = 0

        # Recherche dans les transcripts (segments)
        if include_transcripts and media_ids:
            if is_pg:
                like_pattern = f"%{query.lower()}%"
                # Essayer tsvector sur TranscriptSegment.text
                try:
                    ts_vector = func.to_tsvector('french', TranscriptSegment.text)
                    ts_q = func.plainto_tsquery('french', query)
                    filtered = self.db.query(TranscriptSegment).filter(TranscriptSegment.media_id.in_(media_ids)).filter(ts_vector.op('@@')(ts_q))
                    results = filtered.offset(offset).limit(limit).all()
                    if not results:
                        results = self.db.query(TranscriptSegment).filter(TranscriptSegment.media_id.in_(media_ids), func.lower(TranscriptSegment.text).like(like_pattern)).offset(offset).limit(limit).all()
                except:
                    results = self.db.query(TranscriptSegment).filter(TranscriptSegment.media_id.in_(media_ids), func.lower(TranscriptSegment.text).like(like_pattern)).offset(offset).limit(limit).all()
            else:
                like_pattern = f"%{query.lower()}%"
                results = self.db.query(TranscriptSegment).filter(TranscriptSegment.media_id.in_(media_ids), func.lower(TranscriptSegment.text).like(like_pattern)).offset(offset).limit(limit).all()

            for seg in results:
                media = self.db.query(MediaAsset).filter(MediaAsset.id == seg.media_id).first()
                project = self.db.query(Project).filter(Project.id == media.project_id).first() if media else None
                highlighted = self._highlight(seg.text, query)
                transcripts_found.append({
                    "id": str(seg.id),
                    "media_id": str(seg.media_id),
                    "project_id": str(project.id) if project else None,
                    "project_title": project.title if project else None,
                    "text": seg.text,
                    "highlighted": highlighted,
                    "start_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "language": seg.language,
                    "confidence_score": float(seg.confidence_score) if seg.confidence_score is not None else None,
                    "rank": self._compute_rank(seg.text, query),
                })
            if media_ids:
                like_pattern = f"%{query.lower()}%"
                total_transcripts = self.db.query(TranscriptSegment).filter(TranscriptSegment.media_id.in_(media_ids), func.lower(TranscriptSegment.text).like(like_pattern)).count()
            else:
                total_transcripts = 0
        else:
            total_transcripts = 0

        # Projets pertinents = projets qui ont au moins une réplique ou transcript match
        project_ids_matched = set()
        for r in replicas_found:
            if r["project_id"]:
                project_ids_matched.add(r["project_id"])
        for t in transcripts_found:
            if t["project_id"]:
                project_ids_matched.add(t["project_id"])
        projects_found = []
        for pid in project_ids_matched:
            proj = self.db.query(Project).filter(Project.id == uuid.UUID(pid)).first()
            if proj:
                # Compter les matches par projet
                replica_matches = sum(1 for r in replicas_found if r["project_id"] == pid)
                transcript_matches = sum(1 for t in transcripts_found if t["project_id"] == pid)
                projects_found.append({
                    "id": str(proj.id),
                    "title": proj.title,
                    "status": proj.status,
                    "source_lang": proj.source_lang,
                    "target_lang": proj.target_lang,
                    "replica_matches": replica_matches,
                    "transcript_matches": transcript_matches,
                    "total_matches": replica_matches + transcript_matches,
                })
        # Trier les projets par total_matches décroissant
        projects_found.sort(key=lambda x: x["total_matches"], reverse=True)

        # Filtrer par rank_threshold si demandé
        if rank_threshold > 0:
            replicas_found = [r for r in replicas_found if r["rank"] >= rank_threshold]
            transcripts_found = [t for t in transcripts_found if t["rank"] >= rank_threshold]

        # Trier replicas/transcripts par rank décroissant
        replicas_found.sort(key=lambda x: x["rank"], reverse=True)
        transcripts_found.sort(key=lambda x: x["rank"], reverse=True)

        latency_ms = int((time.time() - start_time) * 1000)
        # Déterminer le moteur utilisé
        engine_name = "postgres" if is_pg else "sqlite"
        if USE_EXTERNAL_SEARCH:
            engine_name = "meilisearch"  # documenté comme option si volume > seuil

        return {
            "query": query,
            "studio_id": str(studio_id),
            "projects": projects_found,
            "replicas": replicas_found,
            "transcripts": transcripts_found,
            "total_projects": len(projects_found),
            "total_replicas": total_replicas,
            "total_transcripts": total_transcripts,
            "latency_ms": latency_ms,
            "engine": engine_name,
            "took_ms": latency_ms,
        }

    def _highlight(self, text: str, query: str) -> str:
        # Simple highlight : entourer les occurrences de <mark>
        if not text or not query:
            return text
        try:
            # Échapper les caractères spéciaux regex
            pattern = re.compile(re.escape(query), re.IGNORECASE)
            return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", text)
        except:
            return text

    def _compute_rank(self, text: str, query: str) -> float:
        # Rank simple basé sur la fréquence du terme et la position
        if not text or not query:
            return 0.0
        text_lower = text.lower()
        query_lower = query.lower()
        # Compter les occurrences
        count = text_lower.count(query_lower)
        if count == 0:
            return 0.0
        # Bonus si le match est au début
        pos = text_lower.find(query_lower)
        pos_score = 1.0 - (pos / len(text)) if len(text) > 0 else 0
        # Rank = count * (1 + pos_score*0.5) / (len(text)/100 + 1)
        rank = count * (1 + pos_score * 0.5) / (len(text) / 100 + 1)
        return round(min(rank, 1.0), 3)

    def search_fast(self, studio_id: uuid.UUID, query: str, limit: int = 20) -> Dict[str, Any]:
        """Version rapide pour le dashboard (utilisée pour l'autocomplétion)."""
        return self.search(studio_id, query, limit=limit, offset=0)
