# verify-pipeline-ia

**Objectif** : Exécute le pipeline Celery IA sur un extrait audio et vérifie la sortie JSON + métriques.

## Étapes
1. Vérifie que Celery est configuré
2. Lance une tâche `transcribe` ou `extract_audio` sur un fichier test
3. Vérifie que le résultat contient `segments`, `words`, `speakers`
4. Vérifie WER si applicable
5. Vérifie les durées (start_ms / end_ms cohérents)
