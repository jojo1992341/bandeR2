# API publique RythmoAI — intégrations ERP & plateformes de droits (§25.4)

L'API publique permet à un système tiers (ERP de production, plateforme de
gestion de droits) de créer des projets, d'enregistrer des médias, de
déclencher le pipeline RythmoAI, de générer des exports et de recevoir des
notifications webhook à la complétion.

Le schéma OpenAPI 3.1 est généré automatiquement par FastAPI et disponible sur
:

- Swagger UI : `/docs`
- Redoc : `/redoc`
- Spécification brute : `/openapi.json`

## Authentification

Les intégrations utilisent une clé API dédiée, distincte des JWT utilisateur.

```
X-API-Key: ryth_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

La clé est aussi acceptée dans `Authorization: Bearer <api-key>`.

Elle est :

- liée à un studio (isolation tenant) ;
- stockée uniquement sous forme de SHA-256 ;
- associée à des scopes (`project:read`, `project:write`, `export:write`, `webhook:write`) ;
- révocable et optionnellement expirable.

### Création d'une clé

Les administrateurs studio créent les clés via :

```http
POST /api/v1/studios/{studio_id}/api-keys
Authorization: Bearer <jwt_admin>
Content-Type: application/json

{
  "name": "ERP production",
  "scopes": ["project:read", "project:write", "export:write", "webhook:write"]
}
```

La réponse contient `api_key` en clair une seule fois.

## Scénario d'intégration minimal

```bash
# 1. Créer un projet
curl -X POST https://rythmoai.example.com/api/v1/public/projects \
  -H "X-API-Key: $RYTHMOAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"Épisode 101","source_lang":"fr","target_lang":"fr"}'

# 2. Enregistrer le média importé
curl -X POST https://rythmoai.example.com/api/v1/public/projects/$PROJECT_ID/media \
  -H "X-API-Key: $RYTHMOAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"storage_path":"projects/.../video.mp4","duration_seconds":1320}'

# 3. Déclencher le traitement et un export SRT automatique
curl -X POST https://rythmoai.example.com/api/v1/public/projects/$PROJECT_ID/process \
  -H "X-API-Key: $RYTHMOAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"auto_export":true,"export_format":"srt","source_separation":true}'
```

Réponse `202 Accepted` :

```json
{
  "job_id": "2d3b...",
  "project_id": "...",
  "media_id": "...",
  "status": "pending",
  "progress_percent": 0,
  "current_step": "queued"
}
```

Le statut peut être interrogé via `GET /api/v1/public/jobs/{job_id}`.

## Webhooks

### Endpoints

```http
POST /api/v1/public/webhooks
X-API-Key: ...

{
  "url": "https://erp.example.com/webhooks/rythmoai",
  "events": ["pipeline.completed", "pipeline.failed", "export.completed"],
  "description": "ERP de production"
}
```

L'URL est validée pour prévenir le SSRF : schéma `http(s)` obligatoire, pas
d'identifiants dans l'URL, pas d'adresses de métadonnées cloud (`169.254.169.254`).

### Vérification de signature

Chaque livraison contient :

```
X-RythmoAI-Event: pipeline.completed
X-RythmoAI-Delivery: <uuid>
X-RythmoAI-Timestamp: 1723000000
X-RythmoAI-Signature: sha256=<hex>
```

La signature est calculée côté serveur comme :

```
HMAC_SHA256(secret, f"{timestamp}." + raw_body)
```

Le récepteur doit :

1. vérifier que `|now - timestamp| < 300s` (anti-rejeu) ;
2. recalculer le HMAC avec le secret renvoyé à la création de l'endpoint ;
3. comparer avec `hmac.compare_digest`.

### Exemple de payload `pipeline.completed`

```json
{
  "id": "uuid-livraison",
  "event": "pipeline.completed",
  "created": "2026-08-08T10:15:30+00:00",
  "data": {
    "project_id": "uuid",
    "media_id": "uuid",
    "job_id": "uuid",
    "status": "completed",
    "progress_percent": 100,
    "rythmo_status": {"task": "generate_rythmo_band", "status": "ok"},
    "auto_export": {
      "export_id": "uuid",
      "format": "srt",
      "status": "completed",
      "download_url": "/api/v1/public/exports/uuid/download"
    }
  }
}
```

Les exports terminés déclenchent aussi `export.completed`. Les échecs
déclenchent `pipeline.failed` avec `data.error`.

## Référence des endpoints publics

| Méthode | Chemin | Scope | Description |
| --- | --- | --- | --- |
| POST | `/api/v1/public/projects` | `project:write` | Créer un projet |
| GET | `/api/v1/public/projects/{project_id}` | `project:read` | Consulter un projet |
| POST | `/api/v1/public/projects/{project_id}/media` | `project:write` | Enregistrer un média |
| POST | `/api/v1/public/projects/{project_id}/process` | `project:write` | Déclencher le pipeline |
| GET | `/api/v1/public/jobs/{job_id}` | `project:read` | Statut d'un job |
| POST | `/api/v1/public/projects/{project_id}/exports` | `export:write` | Déclencher un export |
| GET | `/api/v1/public/projects/{project_id}/exports` | `project:read`, `export:write` | Lister les exports |
| GET | `/api/v1/public/exports/{export_id}` | `project:read` | Consulter un export |
| GET | `/api/v1/public/exports/{export_id}/download` | `project:read` | Télécharger le fichier |
| GET/POST | `/api/v1/public/webhooks` | `webhook:write` | Lister/créer des webhooks |
| DELETE | `/api/v1/public/webhooks/{endpoint_id}` | `webhook:write` | Révoquer un webhook |
| GET | `/api/v1/public/webhooks/{endpoint_id}/deliveries` | `webhook:write`, `project:read` | Journal des livraisons |

## Codes d'erreur

- `401` : clé API manquante/invalide/inactive/expirée ;
- `403` : scope manquant ;
- `404` : ressource absente ou appartenant à un autre studio (protection IDOR) ;
- `409` : export pas encore prêt ;
- `422` : URL webhook ou paramètre invalide.
