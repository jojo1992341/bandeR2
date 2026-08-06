# verify-api-contract

**Objectif** : Vérifie qu'un endpoint FastAPI répond correctement avec le bon code HTTP et respecte le schéma OpenAPI.

## Usage
```bash
python -m verify_api_contract <endpoint> [--method GET|POST] [--expected-status 200]
```

## Étapes de vérification
1. Démarre l'API si nécessaire (uvicorn)
2. Effectue la requête HTTP
3. Vérifie le code de statut attendu
4. Valide que la réponse respecte le schéma OpenAPI (si disponible)
5. Retourne un rapport structuré

## Exemple de sortie attendue
```
✅ Endpoint /health : 200 OK
✅ Schéma OpenAPI valide
✅ Response time < 200ms
```
