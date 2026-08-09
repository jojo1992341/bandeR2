#!/usr/bin/env python3
"""
Script pour lister les tâches Celery enregistrées (§6.4, §18.3 CDC)

Ce script est l'équivalent de:
    celery -A app.celery_app inspect registered

Utilisation:
    python scripts/list_tasks.py
"""

from __future__ import annotations

import json
import sys

# Ajouter le dossier backend au path
sys.path.insert(0, "/home/user/bandeR2/backend")

from app.celery_app import celery_app


def list_tasks() -> dict:
    """
    Liste toutes les tâches enregistrées.
    
    Returns:
        dict: Dictionnaire des tâches par nom.
    """
    tasks = {}
    
    for task_name, task in celery_app.tasks.items():
        if task_name.startswith("celery."):
            continue
        
        tasks[task_name] = {
            "name": str(task.name),
            "queue": str(getattr(task, "queue", "celery")),
            "max_retries": int(getattr(task, "max_retries", 3)),
            "bind": bool(getattr(task, "bind", False)),
        }
    
    return tasks


def print_tasks(tasks: dict) -> None:
    """Affiche les tâches de manière lisible."""
    print("\n" + "=" * 70)
    print("TÂCHES CELERY ENREGISTRÉES - RythmoAI Backend")
    print("=" * 70)
    print(f"\nTotal: {len(tasks)} tâches\n")
    
    # Tâches de santé
    health_tasks = [t for t in tasks if "health" in t or "ping" in t or t == "app.tasks.add"]
    if health_tasks:
        print("🏥 TÂCHES DE SANTÉ:")
        for task_name in sorted(health_tasks):
            print(f"   {task_name}")
        print()
    
    # Tâches pipeline
    pipeline_tasks = [t for t in tasks if "pipeline" in t]
    if pipeline_tasks:
        print("🔄 TÂCHES PIPELINE:")
        for task_name in sorted(pipeline_tasks):
            print(f"   {task_name}")
        print()
    
    # Tâches export
    export_tasks = [t for t in tasks if "export" in t]
    if export_tasks:
        print("📤 TÂCHES D'EXPORT:")
        for task_name in sorted(export_tasks):
            print(f"   {task_name}")
        print()
    
    # Tâches IA
    ia_tasks = [t for t in tasks if any(x in t for x in ["transcription", "diarize", "emotion", "lip_sync", "prosody", "generate_rythmo", "separate_sources", "forced_alignment", "normalize_audio", "extract_audio", "diarization"])]
    if ia_tasks:
        print("🤖 TÂCHES IA/TRAITEMENT:")
        for task_name in sorted(ia_tasks):
            print(f"   {task_name}")
        print()
    
    # Tâches diverses
    other_tasks = [t for t in tasks if t not in health_tasks + pipeline_tasks + export_tasks + ia_tasks]
    if other_tasks:
        print("📦 AUTRES TÂCHES:")
        for task_name in sorted(other_tasks):
            print(f"   {task_name}")
        print()


def main() -> int:
    """Fonction principale."""
    print("\n🔍 Inspection des tâches Celery (équivalent: celery -A app.celery_app inspect registered)")
    
    tasks = list_tasks()
    print_tasks(tasks)
    
    # Afficher le résultat au format JSON (pour compatibilité avec celery inspect)
    print("=" * 70)
    print("RÉSULTAT JSON (format celery inspect):")
    print("=" * 70)
    print(json.dumps({"registered": tasks}, indent=2))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
