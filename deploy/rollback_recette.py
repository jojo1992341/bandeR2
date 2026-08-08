#!/usr/bin/env python3
"""
Déclencheur direct du rollback rapide en recette (§19.3).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_recette import rollback_recette


def main():
    try:
        res = rollback_recette()
        print("=== RythmoAI Recette Rollback Successful (§19.3) ===")
        for k, v in res.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"[ERROR] Rollback failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
