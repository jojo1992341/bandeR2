# verify-security-baseline

**Objectif** : Vérifie la baseline sécurité (bandit, pip-audit, headers).

## Étapes
1. Exécute `bandit -r backend/app`
2. Exécute `pip-audit`
3. Vérifie headers CSP, HSTS, X-Frame-Options sur nginx
4. Vérifie absence de findings critiques
