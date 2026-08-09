#!/usr/bin/env python3
"""
Génère le contrat OpenAPI 3.1 (docs/openapi.json) depuis l'application FastAPI.

Usage:
    PYTHONPATH=backend python3 backend/scripts/generate_openapi.py

Le fichier généré est déterministe (clés triées) pour permettre la vérification
de non-régression en CI (aucun diff attendu si le code n'a pas changé).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ajoute backend/ au path pour importer app.main
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import app.main  # noqa: E402

OUTPUT = BACKEND_DIR.parent / "docs" / "openapi.json"


def main() -> None:
    schema = app.main.app.openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # indent=2 + sort_keys pour un diff déterministe
    OUTPUT.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI 3.1 généré: {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
    print(f"  version: {schema.get('openapi')}")
    print(f"  paths: {len(schema.get('paths', {}))}")


if __name__ == "__main__":
    main()
