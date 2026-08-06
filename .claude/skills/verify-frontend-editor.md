# verify-frontend-editor

**Objectif** : Test Playwright sur l'éditeur (timeline, waveform, synchronisation).

## Étapes
1. Lance le serveur frontend statique
2. Ouvre l'éditeur avec Playwright
3. Vérifie absence d'erreurs console
4. Teste la synchronisation playhead < 100ms
5. Vérifie le rendu Canvas virtualisé
