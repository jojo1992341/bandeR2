from typing import List, Dict, Any

def full_text_search(studio_id: int, query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    G-3.5 — Full-text search on transcriptions (PostgreSQL FTS in real impl).
    """
    # Placeholder results
    return [
        {
            "project_id": 12,
            "project_title": "Le Comte de Monte-Cristo",
            "replica_id": 847,
            "text_snippet": f"...{query}...",
            "start_ms": 124500,
            "relevance": 0.94
        },
        {
            "project_id": 19,
            "project_title": "Astérix et Obélix",
            "replica_id": 1203,
            "text_snippet": f"...{query}...",
            "start_ms": 452300,
            "relevance": 0.81
        }
    ][:limit]
