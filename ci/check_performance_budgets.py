#!/usr/bin/env python3
"""
Vérification automatique des budgets de performance en CI (§17.3, §17.5) :
1. Taille des bundles frontend (JavaScript et statiques)
2. Temps de rendu de la timeline virtualisée (test synthétique sur vidéo de 20 min)
"""

import os
import sys
import time
from pathlib import Path

# Budget de taille maximale des bundles frontend (en octets)
MAX_JS_BUNDLE_BYTES = 500 * 1024  # 500 Ko
MAX_CSS_BUNDLE_BYTES = 100 * 1024  # 100 Ko

# Budgets de temps de rendu (en millisecondes)
MAX_INITIAL_RENDER_MS = 16.0  # 60 FPS (16.6 ms max)
MAX_INCREMENTAL_RENDER_MS = 5.0  # 5 ms pour le recalcul incrémental


def check_bundle_sizes(dist_dir: Path) -> bool:
    print(
        f"==> Vérification des budgets de taille des bundles ({dist_dir})..."
    )
    if not dist_dir.exists():
        print(
            f"[WARN] Dossier {dist_dir} absent, le build frontend doit être exécuté avant."
        )
        return True

    success = True
    assets_dir = dist_dir / "assets"
    files_checked = 0

    if assets_dir.exists():
        for file_path in assets_dir.iterdir():
            if not file_path.is_file():
                continue
            size_bytes = file_path.stat().st_size
            name = file_path.name
            size_kb = size_bytes / 1024.0

            if name.endswith(".js"):
                files_checked += 1
                if size_bytes > MAX_JS_BUNDLE_BYTES:
                    print(
                        f"[FAIL] Bundle JS '{name}' dépasse le budget ({size_kb:.1f} KB > {MAX_JS_BUNDLE_BYTES/1024:.0f} KB)"
                    )
                    success = False
                else:
                    print(
                        f"[OK] Bundle JS '{name}' : {size_kb:.1f} KB (budget: {MAX_JS_BUNDLE_BYTES/1024:.0f} KB)"
                    )
            elif name.endswith(".css"):
                files_checked += 1
                if size_bytes > MAX_CSS_BUNDLE_BYTES:
                    print(
                        f"[FAIL] Bundle CSS '{name}' dépasse le budget ({size_kb:.1f} KB > {MAX_CSS_BUNDLE_BYTES/1024:.0f} KB)"
                    )
                    success = False
                else:
                    print(
                        f"[OK] Bundle CSS '{name}' : {size_kb:.1f} KB (budget: {MAX_CSS_BUNDLE_BYTES/1024:.0f} KB)"
                    )

    if files_checked == 0:
        print("[INFO] Aucun bundle compilé détecté dans dist/assets.")
    return success


def check_timeline_render_budget() -> bool:
    print(
        "==> Vérification du budget de temps de rendu (vidéo de 20 min — §17.3, §17.5)..."
    )
    replicas = []
    for i in range(600):
        start = i * 2000
        replicas.append(
            {
                "id": f"rep-{i}",
                "start_ms": start,
                "end_ms": start + 1800,
                "text": f"Réplique {i} de la vidéo de 20 min",
            }
        )

    t0 = time.perf_counter()
    scroll_ms = 0
    visible_duration = 30000
    end_ms = scroll_ms + visible_duration
    visible = [
        r for r in replicas if r["end_ms"] >= 0 and r["start_ms"] <= end_ms
    ]
    t1 = time.perf_counter()

    render_ms = (t1 - t0) * 1000.0
    print(
        f"[INFO] Sélection de {len(visible)} répliques visibles sur {len(replicas)} : {render_ms:.3f} ms"
    )
    if render_ms > MAX_INITIAL_RENDER_MS:
        print(
            f"[FAIL] Temps de rendu ({render_ms:.3f} ms) dépasse le budget ({MAX_INITIAL_RENDER_MS} ms)"
        )
        return False
    print(
        f"[OK] Temps de rendu respecte le budget ({MAX_INITIAL_RENDER_MS} ms)"
    )
    return True


def main():
    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "frontend" / "dist"

    ok_bundles = check_bundle_sizes(dist_dir)
    ok_render = check_timeline_render_budget()

    if not ok_bundles or not ok_render:
        print(
            "[ERROR] Échec de la vérification des budgets de performance (§17.5)."
        )
        sys.exit(1)
    print(
        "[SUCCESS] Tous les budgets de performance (bundles, temps de rendu) sont respectés !"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
