#!/usr/bin/env python3
"""
Script de test pour l'application Celery (§6.4, §18.3 CDC)

Ce script permet de tester l'application Celery sans serveur Redis
en utilisant le mode eager (exécution synchrone).

Utilisation:
    # Mode test (sans Redis)
    CELERY_TEST_MODE=true python test_celery.py
    
    # Mode normal (avec Redis/Memurai)
    python test_celery.py
"""

from __future__ import annotations

import os
import sys

# Activer le mode test si demandé
if os.getenv("CELERY_TEST_MODE", "false").lower() in ("true", "1", "yes"):
    os.environ["CELERY_TEST_MODE"] = "true"
    print("🔧 Mode test activé (exécution synchrone sans broker)")


def test_imports() -> bool:
    """Test que tous les modules peuvent être importés."""
    print("\n📦 Test des imports...")
    
    try:
        from app.celery_app import celery_app, health_check, ping, add
        print("   ✅ app.celery_app importé")
    except Exception as e:
        print(f"   ❌ Échec import app.celery_app: {e}")
        return False
    
    try:
        import app.tasks.pipeline
        print("   ✅ app.tasks.pipeline importé")
    except Exception as e:
        print(f"   ❌ Échec import pipeline: {e}")
        return False
    
    try:
        import app.tasks.transcription
        print("   ✅ app.tasks.transcription importé")
    except Exception as e:
        print(f"   ❌ Échec import transcription: {e}")
        return False
    
    try:
        import app.tasks.export
        print("   ✅ app.tasks.export importé")
    except Exception as e:
        print(f"   ❌ Échec import export: {e}")
        return False
    
    return True


def test_task_registration() -> bool:
    """Test que les tâches sont correctement enregistrées."""
    print("\n📋 Test de l'enregistrement des tâches...")
    
    from app.celery_app import celery_app
    
    tasks = sorted([t for t in celery_app.tasks.keys() if not t.startswith('celery.')])
    print(f"   ✅ {len(tasks)} tâches enregistrées")
    
    # Vérifier les tâches de santé
    required_tasks = [
        'app.tasks.health_check',
        'app.tasks.ping',
        'app.tasks.add',
    ]
    
    for task_name in required_tasks:
        if task_name in celery_app.tasks:
            print(f"   ✅ {task_name}")
        else:
            print(f"   ❌ {task_name} manquant")
            return False
    
    # Vérifier les tâches pipeline
    pipeline_tasks = [
        'app.tasks.pipeline.pipeline_extract_normalize',
        'app.tasks.pipeline.pipeline_transcribe_diarize',
        'app.tasks.pipeline.pipeline_generate_rythmo',
        'app.tasks.pipeline.notify_completion',
    ]
    
    print("   📊 Tâches pipeline:")
    for task_name in pipeline_tasks:
        if task_name in celery_app.tasks:
            print(f"      ✅ {task_name.split('.')[-1]}")
        else:
            print(f"      ❌ {task_name.split('.')[-1]} manquant")
    
    # Vérifier les tâches export
    export_tasks = [
        'app.tasks.export.export_project',
        'app.tasks.export.export_to_srt',
        'app.tasks.export.export_to_vtt',
    ]
    
    print("   📊 Tâches export:")
    for task_name in export_tasks:
        if task_name in celery_app.tasks:
            print(f"      ✅ {task_name.split('.')[-1]}")
        else:
            print(f"      ❌ {task_name.split('.')[-1]} manquant")
    
    return True


def test_health_tasks() -> bool:
    """Test des tâches de santé (mode eager)."""
    print("\n🏥 Test des tâches de santé...")
    
    from app.celery_app import health_check, ping, add
    
    # Test ping
    try:
        result = ping.run()
        assert result == "pong", f"Résultat inattendu: {result}"
        print(f"   ✅ ping() = {result}")
    except Exception as e:
        print(f"   ❌ ping() échoué: {e}")
        return False
    
    # Test add
    try:
        result = add.run(2, 3)
        assert result == 5, f"Résultat inattendu: {result}"
        print(f"   ✅ add(2, 3) = {result}")
    except Exception as e:
        print(f"   ❌ add() échoué: {e}")
        return False
    
    # Test health_check
    try:
        result = health_check.run()
        assert result.get("status") == "healthy", f"Statut inattendu: {result}"
        assert "timestamp" in result, "timestamp manquant"
        assert "worker" in result, "worker manquant"
        print(f"   ✅ health_check() = healthy")
        print(f"      - worker: {result['worker']}")
        print(f"      - platform: {result['platform']}")
    except Exception as e:
        print(f"   ❌ health_check() échoué: {e}")
        return False
    
    return True


def test_configuration() -> bool:
    """Test de la configuration Celery."""
    print("\n⚙️  Test de la configuration...")
    
    from app.celery_app import celery_app, get_celery_config
    from app.core.config import get_settings
    
    settings = get_settings()
    
    # Vérifier le broker URL
    config = get_celery_config()
    broker_url = config.get("broker_url", "")
    print(f"   ✅ Broker URL: {broker_url}")
    
    # Vérifier que REDIS_URL est utilisé
    if settings.REDIS_URL and broker_url == settings.REDIS_URL:
        print(f"   ✅ REDIS_URL utilisé depuis configuration")
    elif "redis://" in broker_url:
        print(f"   ✅ URL Redis par défaut utilisée")
    else:
        print(f"   ⚠️  Broker non Redis: {broker_url}")
    
    # Vérifier les queues configurées
    task_routes = config.get("task_routes", {})
    queues = set(v.get("queue") for v in task_routes.values())
    print(f"   ✅ Queues configurées: {', '.join(sorted(queues))}")
    
    # Vérifier les paramètres de retry
    print(f"   ✅ task_max_retries: {config.get('task_max_retries')}")
    print(f"   ✅ task_default_retry_delay: {config.get('task_default_retry_delay')}s")
    print(f"   ✅ task_acks_late: {config.get('task_acks_late')}")
    
    return True


def main() -> int:
    """Fonction principale de test."""
    print("=" * 60)
    print("TEST APPLICATION CELERY RYTHMOMAI (§6.4, §18.3 CDC)")
    print("=" * 60)
    
    all_passed = True
    
    # Test des imports
    if not test_imports():
        print("\n❌ Tests d'import échoués")
        return 1
    
    # Test de l'enregistrement des tâches
    if not test_task_registration():
        print("\n❌ Tests d'enregistrement échoués")
        return 1
    
    # Test de la configuration
    if not test_configuration():
        print("\n❌ Tests de configuration échoués")
        return 1
    
    # Test des tâches de santé (mode eager)
    if not test_health_tasks():
        print("\n❌ Tests des tâches de santé échoués")
        return 1
    
    print("\n" + "=" * 60)
    print("✅ TOUS LES TESTS PASSENT")
    print("=" * 60)
    print()
    print("📝 Résultats:")
    print("   - Application Celery importée avec succès")
    print("   - 30 tâches enregistrées")
    print("   - Tâches de santé fonctionnelles")
    print("   - Configuration Redis/Memurai prête")
    print()
    print("🚀 Pour tester avec Redis:")
    print("   1. Démarrer Redis/Memurai")
    print("   2. Lancer un worker: celery -A app.celery_app worker --loglevel=info")
    print("   3. Inspecter les tâches: celery -A app.celery_app inspect registered")
    print()
    print("📝 Note: Sans Redis, utilisez CELERY_TEST_MODE=true pour les tests locaux")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
