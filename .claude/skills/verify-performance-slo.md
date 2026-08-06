# verify-performance-slo

**Objectif** : Vérifie les SLO de performance (§17.1).

## Seuils cibles
- Chargement éditeur < 2.5s P75
- Latence API CRUD < 200ms P95
- Pipeline 20min < 10min (GPU)
- Écart synchro < 80ms

## Outils
- k6 pour load testing
- Playwright pour métriques frontend
