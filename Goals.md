# RythmoAI — Plan de Loop Engineering (`/goal`) pour Claude Code, du Socle à la V3+

> Basé sur : *CDC_RythmoAI.docx* — Cahier des charges fonctionnel, technique et industriel v1.0 (05/08/2026)
> Méthode : *Loop Engineering* Claude Code — boucles goal-based (`/goal`), cf. [claude.com/blog/getting-started-with-loops](https://claude.com/blog/getting-started-with-loops)

## 0. Comment utiliser ce document

Chaque bloc `G-x.y` est une **boucle goal-based** à coller telle quelle, **une par une, dans l'ordre**, dans une session Claude Code ouverte à la racine du repo `rythmoai/`. `/goal` est une commande interactive : Claude travaille, tente de s'arrêter, un modèle évaluateur (Haiku par défaut) vérifie la condition écrite, et le renvoie au travail jusqu'à condition remplie ou plafond de tentatives atteint (`stop after N tries`).

Règles suivies pour construire ce plan (cf. billet officiel) :
- **Critères déterministes** partout où c'est possible (tests qui passent, seuils chiffrés du CDC : WER < 8 %, écart de synchro < 80 ms, pipeline 20 min < 10 min, couverture 80 %, SLO §17.1…), car une fausse fin coûte cher en `/goal`.
- Chaque goal est **dimensionné pour être vérifiable en quelques tentatives** (4 à 12) — jamais "construire tout le module" en un seul goal géant.
- Les goals s'appuient sur des **skills de vérification** (`SKILL.md`) créées en amont (G-0.4) : Claude n'a pas à *croire* que ça marche, il doit le *démontrer*.
- Entre deux phases majeures, insérer une revue avec `/code-review` (ou le skill Code Review) avant de lancer la phase suivante — un agent de revue avec un contexte neuf est moins biaisé.
- Modèle recommandé : Sonnet 5 par défaut pour l'exécution ; passez sur Opus pour les goals à fort enjeu architecture/sécurité (marqués ⚠️). Surveillez la conso avec `/usage` et `/goal` sans argument.
- La syntaxe exacte de `/goal`, `/loop`, `/schedule` évolue vite : vérifiez toujours `code.claude.com/docs/en/goal` avant une session longue.

---

## 1. Vue d'ensemble — séquençage vs roadmap CDC (§20.1)

| Phase | Horizon CDC | Contenu | Goals |
|---|---|---|---|
| Phase 0 — Cadrage & Socle | M0 → M1 | Repo, CLAUDE.md, skills, Docker, CI, DB, auth | G-0.1 → G-0.6 |
| Phase 1 — MVP | M1 → M4 | Import, pipeline IA v1, éditeur, export SRT/VTT/PDF, users/studios | G-1.1 → G-1.16 |
| Phase 2 — V1 | M4 → M7 | Respirations, émotions, profils typo, EBU-STL/Cavena, collaboration | G-2.1 → G-2.11 |
| Phase 3 — V1.5 | M7 → M10 | Synchro labiale, dashboard avancé, recherche full-text, feedback loop | G-3.1 → G-3.7 |
| Phase 4 — V2 | M10 → M15 | SSO Enterprise, CRDT, séparation de sources, API publique, mobile | G-4.1 → G-4.7 |
| Phase 5 — V3+ | M15+ | Assistance adaptation IA, marketplace profils, découpage avancé, doublage assisté IA (exploratoire) | G-5.1 → G-5.6 |

---

## 2. Prérequis avant la première boucle

### 2.1 `CLAUDE.md` (racine du repo)
À rédiger avant G-0.1, doit fixer ce que le CDC impose et qu'aucun goal ne doit pouvoir réinterpréter :
- Stack imposée : **frontend HTML5/CSS3/JS natif (ES2022+, pas de framework lourd)** ; **backend Python 3.13+/FastAPI** (§7.1, §6.1) — un goal qui introduit React/Vue/Angular doit échouer sa propre vérification.
- Arborescence Clean Architecture backend (§6.2) et modules ES frontend (§7.2) à respecter strictement.
- Commandes de test/lint de référence (`pytest`, `ruff`, `black`, `Web Test Runner`/`Vitest`, `Playwright`) que chaque skill de vérification doit invoquer.
- Rappel MoSCoW (§21) : un goal ne doit pas implémenter un `Could have` avant que les `Must have` de son epic soient verts.

### 2.2 Skills de vérification à créer (G-0.4 les détaille)
`verify-api-contract`, `verify-pipeline-ia`, `verify-frontend-editor`, `verify-export-format`, `verify-security-baseline`, `verify-performance-slo`.

### 2.3 Isolation
Pour paralléliser des goals indépendants (ex. frontend éditeur + export PDF), utilisez des `git worktree` séparés plutôt que la même session, pour éviter les collisions de fichiers.

---

## 3. Phase 0 — Cadrage & Socle technique (M0 → M1)

**G-0.1 — Initialisation du repo et de l'architecture backend**
```
/goal initialiser le repo rythmoai/ avec l'arborescence backend en Clean Architecture décrite au §6.2 du CDC (api/, core/, domain/, services/, repositories/, tasks/, ai/, infrastructure/, models/, schemas/, alembic/, tests/{unit,integration,e2e}) : le projet FastAPI démarre (`uvicorn app.main:app`), répond 200 sur /health, et `pytest` s'exécute sans erreur de collecte même sans test encore écrit. Stop after 5 tries.
```
Réf. CDC : §6.2, §6.1.

**G-0.2 — Socle Docker Compose de développement**
```
/goal faire démarrer via `docker compose up` les services décrits au §18.3 (nginx, api, worker-cpu, worker-gpu profil GPU optionnel, beat, postgres, redis, minio, flower) : `docker compose ps` montre tous les services "healthy", l'API est joignable via nginx sur le port configuré, MinIO est accessible et Flower affiche les workers Celery connectés. Stop after 6 tries.
```
Dépend de : G-0.1.

**G-0.3 — Pipeline CI de base**
```
/goal mettre en place le pipeline CI GitHub Actions décrit au §19.2 (lint ruff/black, bandit, pip-audit, pytest avec couverture) : une pull request de test déclenche le workflow, tous les jobs passent au vert sur une branche propre, et le job échoue intentionnellement si je casse le lint pour vérifier le garde-fou. Stop after 6 tries.
```
Dépend de : G-0.1.

**G-0.4 — Rédaction des skills de vérification**
```
/goal créer les fichiers SKILL.md suivants dans .claude/skills/ : verify-api-contract (démarre l'API, teste les codes HTTP et le schéma OpenAPI d'un endpoint donné), verify-pipeline-ia (exécute le pipeline Celery sur un extrait audio de test et vérifie sortie JSON + métriques), verify-frontend-editor (Playwright : ouvre l'éditeur, interagit avec la timeline, vérifie zéro erreur console), verify-export-format (valide un fichier exporté contre son schéma/format cible), verify-security-baseline (bandit + pip-audit + vérif headers de sécurité Nginx), verify-performance-slo (vérifie les seuils du §17.1). Chaque skill doit être utilisable seul et documenter ses étapes de vérification comme un relecteur humain le ferait, sans se contenter d'un edit réussi. Stop after 8 tries.
```
Dépend de : G-0.1 → G-0.3. ⚠️ Recommandé sous Opus (conçoit les critères de vérification pour tout le reste du projet).

**G-0.5 — Modèle de données initial et migrations**
```
/goal implémenter en SQLAlchemy 2.0 async + Alembic les entités du §9.2 (Studio, User, StudioMembership, Project, MediaAsset, TranscriptSegment, Word, Speaker, SilenceEvent, EmotionTag, RythmoBand, Replica, ReplicaHistory, TypographicProfile, ExportJob, Comment, AuditLog, Subscription) avec les relations du §9.3, les index du §9.5 (B-Tree sur FK/order_index, GIN sur JSONB, composite rythmo_band_id+start_ms) et l'isolation multi-tenant par studio_id + RLS PostgreSQL (§9.6) : `alembic upgrade head` s'exécute sans erreur sur une base vide, et un test d'intégration confirme qu'une requête sans filtre studio_id explicite ne retourne aucune ligne d'un autre tenant. Stop after 10 tries.
```
Dépend de : G-0.2. Skill : verify-api-contract (adapté aux repositories).

**G-0.6 — Authentification JWT et squelette RBAC**
```
/goal implémenter l'authentification décrite au §15.2 (OAuth2/OIDC, JWT access 15 min + refresh 7 jours avec rotation, hashage Argon2id) et le RBAC du §15.3 (rôles Owner/Admin, Chef de projet, Directeur artistique, Adaptateur, Calligraphe, Invité lecture seule) via des dépendances FastAPI `require_role(...)` : les tests d'intégration couvrent login/refresh/logout, un token expiré est rejeté en 401, un rôle insuffisant sur un endpoint protégé retourne 403, et un utilisateur ne peut pas accéder aux ressources d'un studio dont il n'est pas membre (anti-IDOR, 404 attendu). Stop after 10 tries.
```
Dépend de : G-0.5. ⚠️ Opus recommandé (sécurité).

---

## 4. Phase 1 — MVP (M1 → M4)

### 4.1 Import & extraction média (Epic §21.1)

**G-1.1 — Import vidéo par upload résumable**
```
/goal implémenter POST /projects/{id}/media/upload-url (URL pré-signée stockage objet, §11.1) et le drag & drop côté frontend natif avec barre de progression et reprise d'upload interrompu (US-001, US-002, US-006) : un test e2e Playwright importe un fichier de test de 50 Mo, coupe la connexion à 50 % puis relance, et le fichier arrive intact (checksum identique) dans le bucket, sans jamais transiter par le serveur applicatif. Stop after 8 tries.
```
Dépend de : G-0.6.

**G-1.2 — Validation et extraction audio**
```
/goal implémenter la tâche Celery extract_audio (§11.2, §6.4) : validation par ffprobe (pas seulement extension, US-004) des formats MP4/MOV/MXF/AVI/MKV, extraction WAV 16 kHz mono normalisé EBU R128, génération du proxy vidéo 720p et de la sprite sheet de vignettes. Sur 3 fichiers de test (1 valide, 1 corrompu, 1 format non supporté), le job échoue proprement avec message explicite pour les 2 derniers et produit les 3 artefacts attendus pour le premier, avec retry automatique 3 tentatives / backoff exponentiel (§6.4). Stop after 8 tries.
```
Dépend de : G-1.1.

### 4.2 Pipeline IA v1 (Epic §21.2)

**G-1.3 — Transcription Whisper Large v3**
```
/goal intégrer faster-whisper (Whisper Large v3 self-hosted GPU, quantifié int8/float16 §8.4) comme tâche Celery `transcribe` (US-010) : sur le corpus de test FR fourni, le pipeline produit un JSON texte horodaté par segment + langue détectée + score de confiance, avec fallback CPU automatique si aucun GPU n'est disponible, et un WER mesuré < 15 % (seuil MVP intermédiaire vers la cible 8 % du §1.3). Stop after 8 tries.
```
Dépend de : G-1.2. Skill : verify-pipeline-ia.

**G-1.4 — Alignement mot-à-mot WhisperX**
```
/goal intégrer WhisperX pour l'alignement forcé (§8.2.2) avec fallback Montreal Forced Aligner : chaque mot du corpus de test obtient un timestamp start_ms/end_ms individuel persisté en table Word, et l'écart moyen mesuré entre bande et audio de référence est < 150 ms (seuil MVP intermédiaire vers la cible 80 ms du §1.3). Stop after 8 tries.
```
Dépend de : G-1.3.

**G-1.5 — Diarisation et gestion des locuteurs**
```
/goal intégrer pyannote.audio (speaker-diarization-3.1+, §8.2.3) et les endpoints de renommage/fusion de locuteurs (US-011, US-012) : sur un extrait de test à 3 locuteurs, la diarisation associe correctement au moins 90 % des mots au bon Speaker, et un test d'intégration confirme que fusionner deux locuteurs mal détectés réattribue toutes leurs répliques sans perte de données. Stop after 8 tries.
```
Dépend de : G-1.4.

**G-1.6 — Orchestration Celery bout-en-bout + suivi temps réel**
```
/goal orchestrer la chaîne Celery complète du §13.1 (extract_audio → normalize_audio → transcribe → group(align_words, diarize) → generate_rythmo_band → notify_completion) avec files dédiées §13.2 et exposer l'avancement via WebSocket avec repli polling REST 3 s (§6.3, §13.3) : un test e2e lance le pipeline sur une vidéo de 5 min, observe au moins 3 mises à jour d'étape distinctes en WebSocket, et le job complet se termine sans intervention manuelle en moins de 3 minutes. Stop after 10 tries.
```
Dépend de : G-1.5.

**G-1.7 — Score de confiance par réplique**
```
/goal calculer le score de confiance agrégé par réplique (moyenne pondérée transcription/alignement/diarisation, §12.4, US-016) et l'exposer dans l'API : un test unitaire vérifie que le score est recalculé et persisté à chaque régénération, et qu'une réplique avec chevauchement de locuteurs simulé obtient un score significativement plus bas (delta > 0.2) qu'une réplique propre. Stop after 6 tries.
```
Dépend de : G-1.6.

### 4.3 Génération et édition de la bande rythmo (Epic §21.3)

**G-1.8 — Moteur de génération automatique de la bande rythmo**
```
/goal implémenter le moteur de règles métier de génération de bande rythmo (§8.3, US-020) : segmentation en répliques cohérentes par locuteur/silence/limite syntaxique, calcul de durée disponible, application de codes typographiques par défaut, insertion des marqueurs disponibles. Sur le corpus de test, POST /projects/{id}/rythmo/generate retourne 202 puis produit une RythmoBand avec des Replica ordonnées (order_index strictement croissant), sans chevauchement non autorisé, en moins de 10 secondes de traitement pur règles métier (hors pipeline IA amont, cf. cible §13.4). Stop after 10 tries.
```
Dépend de : G-1.7.

**G-1.9 — Éditeur frontend : timeline, waveform, lecteur synchronisé**
```
/goal construire l'écran éditeur (§14.2.3) en JS natif/Web Components avec Video.js (lecteur), WaveSurfer.js (waveform avec régions colorées par locuteur) et rendu Canvas 2D virtualisé pour la piste bande rythmo (§7.4) : un test Playwright charge un projet de test, vérifie que la lecture vidéo et le déplacement du playhead restent synchronisés (écart < 100 ms, cible §17.1), et que seuls les éléments visibles du viewport sont dessinés sur une bande simulée de 2 h. Stop after 10 tries.
```
Dépend de : G-1.8. Skill : verify-frontend-editor.

**G-1.10 — Édition des répliques (déplacer, scinder, fusionner)**
```
/goal implémenter les interactions d'édition de répliques (US-021, US-022) : glisser pour déplacer, poignées pour redimensionner, POST /replicas/{id}/split, POST /replicas/merge, avec validation métier start_ms < end_ms et pas de chevauchement non autorisé (§10.3). Un test Playwright scinde une réplique en deux au point de lecture et vérifie les deux nouvelles répliques dans le DOM et en base ; un test API vérifie qu'une tentative de chevauchement invalide retourne 422. Stop after 8 tries.
```
Dépend de : G-1.9.

**G-1.11 — Codes typographiques, undo/redo, sauvegarde automatique**
```
/goal implémenter l'application des codes typographiques de base (crochets, italique, majuscules — §2.4), la pile undo/redo (Command Pattern, US-024) et l'auto-save différée toutes les 3 s d'inactivité avec indicateur de statut idle/saving/saved/error (§7.3, US-025) : un test Playwright édite une réplique, annule (Ctrl+Z), rétablit (Ctrl+Y), attend 3 s d'inactivité et vérifie via l'API que l'état persisté correspond à l'état affiché, sans perte lors d'une coupure réseau simulée (cache IndexedDB, §7.4). Stop after 8 tries.
```
Dépend de : G-1.10.

### 4.4 Export MVP (Epic §21.5, sous-ensemble Must)

**G-1.12 — Export SRT/VTT**
```
/goal implémenter POST /projects/{id}/exports pour les formats SRT et VTT étendus (US-042) : le fichier généré est syntaxiquement valide (parsé sans erreur par un parser SRT/VTT de référence), les timecodes correspondent aux start_ms/end_ms des répliques à la milliseconde près, et le job d'export se termine en moins de 15 s pour une bande de 20 min (cible §17.1). Stop after 6 tries.
```
Dépend de : G-1.11.

**G-1.13 — Export PDF calligraphié**
```
/goal implémenter l'export PDF calligraphié (US-040, format détaillé en A.2) avec timecodes de référence et codes typographiques mis en page : un test vérifie que le PDF généré s'ouvre sans erreur, contient le nombre de répliques attendu et le filigrane dynamique (nom d'utilisateur, date, heure) pour les rôles à risque (invité/client, §15.4). Stop after 8 tries.
```
Dépend de : G-1.11.

### 4.5 Gestion utilisateurs, studios, projets (§16, sous-ensemble MVP)

**G-1.14 — Cycle de vie projet, studios, utilisateurs**
```
/goal implémenter la gestion des projets avec le cycle de vie du §16.1 (Créé → En traitement → Prêt pour édition → En édition → En relecture → Validé → Exporté/Livré → Archivé), l'invitation d'utilisateurs par email (US-030, US-050) et la gestion multi-studio (§16.3) : un test e2e crée un studio, invite un collaborateur avec un rôle donné, crée un projet, et vérifie que chaque transition de statut est possible uniquement dans l'ordre autorisé (une transition invalide retourne 409). Stop after 8 tries.
```
Dépend de : G-1.6, G-0.6.

**G-1.15 — Durcissement sécurité et performance MVP**
```
/goal appliquer la baseline sécurité du §15 (TLS 1.3 + HSTS, chiffrement AES-256 au repos, URLs signées ≤ 10 min, en-têtes CSP/X-Frame-Options/Referrer-Policy, whitelist + vérification de signature binaire des uploads) et vérifier les SLO de performance du §17.1 (chargement éditeur < 2,5 s P75, latence API CRUD < 200 ms P95) : le skill verify-security-baseline passe sans finding critique/haut, et un test de charge k6 basique confirme les seuils de latence sur les endpoints CRUD principaux. Stop after 10 tries.
```
Dépend de : G-1.1 → G-1.14. ⚠️ Opus recommandé. Skills : verify-security-baseline, verify-performance-slo.

**G-1.16 — Recette MVP (jalon M4)**
```
/goal valider le MVP de bout en bout : un test e2e Playwright complet exécute le parcours import → pipeline IA → génération bande → édition manuelle → export SRT/VTT/PDF sur un projet de test sans intervention manuelle en dehors des étapes d'édition volontaires, tous les tests unitaires/intégration/e2e passent en CI avec une couverture ≥ 80 % sur domain/ et services/ (§19.2), et aucune régression de sécurité n'est détectée par verify-security-baseline. Stop after 10 tries.
```
Dépend de : G-1.1 → G-1.15. **Jalon** : correspond à M4 du §20.2 — checkpoint de revue humaine + `/code-review` avant de passer en Phase 2.

---

## 5. Phase 2 — V1 (M4 → M7)

**G-2.1 — Détection des respirations, pauses, hésitations**
```
/goal intégrer Silero-VAD + le module heuristique de classification des silences (§8.2.4, US-013) : respiration audible, pause syntaxique (> 300 ms fin de proposition), hésitation (< 200 ms même locuteur), coupe technique. Sur le corpus de test annoté, la classification atteint ≥ 80 % d'accord avec les annotations de référence, et les marqueurs de respiration apparaissent comme points d'appui visuels dans l'éditeur (test Playwright). Stop after 8 tries.
```
Dépend de : G-1.16.

**G-2.2 — Indicateur de débit d'élocution**
```
/goal calculer le débit d'élocution (syllabes/seconde) par réplique et le comparer à des seuils configurables par langue (5–7 syll/s en FR, §12.3, US-014) : un test unitaire vérifie le calcul sur des répliques de référence à débit connu (tolérance ±10 %), et l'éditeur affiche un signal visuel quand le seuil est dépassé. Stop after 6 tries.
```
Dépend de : G-2.1.

**G-2.3 — Détection d'émotions et d'intentions**
```
/goal intégrer la double analyse acoustique (wav2vec2 fine-tuné) et textuelle (NLP FR) du §8.2.5 (US-015) : chaque réplique du corpus de test reçoit une étiquette émotionnelle et une intention, affichées comme suggestion non bloquante (jamais d'application automatique du texte, seulement des codes typographiques suggérés) — un test vérifie qu'aucune modification du champ `text` ne se produit automatiquement lors de la détection. Stop after 8 tries.
```
Dépend de : G-2.1.

**G-2.4 — Profils typographiques personnalisables**
```
/goal implémenter les profils typographiques par studio (§2.4, §8.3, US-023, US-051) avec CRUD complet (GET/PATCH /studios/{id}/typographic-profiles) : un studio peut définir plusieurs profils (un par diffuseur/client), la génération de bande applique le profil sélectionné, et un test vérifie que deux profils différents produisent des codes typographiques différents sur le même texte source. Stop after 8 tries.
```
Dépend de : G-1.16.

**G-2.5 — Export EBU-STL étendu**
```
/goal implémenter l'export EBU-STL étendu (US-041, format détaillé en A.2) avec répliques horodatées, styles et métadonnées locuteur : le fichier généré est validé par un validateur EBU-STL de référence, et un aller-retour import/export ne perd aucune métadonnée testée. Stop after 8 tries.
```
Dépend de : G-1.16.

**G-2.6 — Export format Cavena/.rythmo**
```
/goal implémenter l'export au format Cavena/.rythmo reconstitué (US-041, A.2) en collaboration avec la structure propriétaire documentée en amont avec le(s) studio(s) pilote(s) (§24.1 — risque de non-conformité) : un test de compatibilité vérifie que le fichier généré est accepté par l'outil de lecture cible fourni en fixture de test, sans erreur de parsing. Stop after 10 tries.
```
Dépend de : G-2.5.

**G-2.7 — Collaboration multi-utilisateurs et verrouillage optimiste**
```
/goal implémenter la consultation simultanée multi-utilisateurs et le verrouillage optimiste par réplique avec notification WebSocket (US-033, §16.4) : un test simule deux utilisateurs éditant le même projet, le second reçoit une notification "X édite cette réplique" en < 1 s quand le premier commence l'édition, et ne peut pas écraser silencieusement la modification en cours. Stop after 8 tries.
```
Dépend de : G-1.16.

**G-2.8 — Commentaires collaboratifs**
```
/goal implémenter les commentaires attachés à une réplique ou un projet (US-031) : GET/POST /replicas/{id}/comments, DELETE /comments/{id}, avec fil de commentaires affiché dans le panneau latéral contextuel (§14.2.4). Un test e2e poste un commentaire, le voit apparaître en temps réel pour un second utilisateur connecté au même projet, et vérifie la suppression. Stop after 6 tries.
```
Dépend de : G-2.7.

**G-2.9 — Validation formelle et verrouillage de la bande rythmo**
```
/goal implémenter la validation formelle par le directeur artistique (US-032) qui verrouille la bande rythmo en écriture (statut "Validé" du §16.1) sauf déverrouillage explicite par un rôle autorisé : un test vérifie qu'une tentative d'édition sur une bande validée et verrouillée retourne 409, et qu'un déverrouillage explicite par un Chef de projet la rend à nouveau éditable avec entrée d'audit correspondante. Stop after 6 tries.
```
Dépend de : G-2.7.

**G-2.10 — MFA et durcissement sécurité V1**
```
/goal implémenter le MFA TOTP obligatoire pour les comptes administrateurs de studio et optionnel pour les autres rôles (US-052, §15.2), ainsi que la détection de mots de passe compromis (Have I Been Pwned range API) : un test vérifie qu'un admin ne peut pas se connecter sans code TOTP valide une fois le MFA activé, et qu'un mot de passe présent dans la liste de fuites de test est rejeté à l'inscription. Stop after 8 tries.
```
Dépend de : G-1.15.

**G-2.11 — Ouverture commerciale V1 (jalon M7)**
```
/goal valider la V1 : tous les tests e2e couvrant respirations/émotions/profils typographiques/exports EBU-STL+Cavena/collaboration/commentaires/validation passent en CI, les SLO du §17.1 restent tenus sous charge simulée (k6, scénario import + édition concurrente multi-utilisateurs, §17.5), et verify-security-baseline confirme l'absence de régression suite au MFA. Stop after 10 tries.
```
Dépend de : G-2.1 → G-2.10. **Jalon** M7 (§20.2) — revue `/code-review` avant Phase 3.

---

## 6. Phase 3 — V1.5 (M7 → M10)

**G-3.1 — Détection faciale et ouverture labiale**
```
/goal intégrer Mediapipe FaceMesh pour mesurer l'ouverture buccale image par image sur les plans avec visage détecté (§8.2.6, §11.4) : sur un extrait de test avec gros plan, le module produit une courbe d'activité labiale normalisée et un test vérifie sa corrélation (coefficient > 0.6) avec l'énergie du signal vocal sur les mêmes segments. Stop after 10 tries.
```
Dépend de : G-2.11.

**G-3.2 — Fiabilisation du calage par corrélation labiale/audio**
```
/goal utiliser la courbe d'ouverture labiale de G-3.1 pour fiabiliser le calage des crochets d'entrée/sortie sur les gros plans (§8.2.6) : un test compare l'écart moyen bande/audio avec et sans le module de synchronisation labiale activé sur le corpus de test à visages détectés, et confirme une amélioration mesurable (réduction de l'écart moyen). Stop after 8 tries.
```
Dépend de : G-3.1.

**G-3.3 — Feature flag et activation progressive**
```
/goal exposer la synchronisation labiale derrière un feature flag activable par projet à l'import (§14.2.2, §19.3), désactivé par défaut : un test vérifie que le pipeline s'exécute normalement sans le module si le flag est désactivé (pas de régression de temps de traitement), et que l'activer sur un projet n'affecte pas les projets existants. Stop after 6 tries.
```
Dépend de : G-3.2.

**G-3.4 — Dashboard studio avancé**
```
/goal enrichir le dashboard (§14.2.1, §16.3) avec les indicateurs studio (temps moyen de traitement, volume traité dans le mois, quota d'usage restant, minutes IA consommées) : un test vérifie que les chiffres affichés correspondent aux données réellement consommées par les jobs Celery du mois de test simulé. Stop after 6 tries.
```
Dépend de : G-2.11.

**G-3.5 — Recherche full-text**
```
/goal implémenter la recherche full-text dans les transcriptions de l'ensemble des projets d'un studio (§16.1, PostgreSQL full-text search) : un test recherche un terme présent dans une seule transcription parmi plusieurs projets de test et vérifie que seul le projet pertinent est retourné, en moins de 200 ms (cible §17.1 latence API). Stop after 8 tries.
```
Dépend de : G-2.11.

**G-3.6 — Feedback loop d'amélioration continue**
```
/goal journaliser de façon anonymisée chaque correction manuelle significative (recalage de mot, correction de locuteur, changement de code typographique) pour constituer un corpus d'entraînement (§8.5) : un test vérifie que la journalisation ne s'active que pour les studios ayant donné leur consentement contractuel explicite, et qu'aucune donnée nominative n'apparaît dans le corpus généré. Stop after 8 tries.
```
Dépend de : G-2.11. ⚠️ Opus recommandé (RGPD, §15.6).

**G-3.7 — Jalon V1.5 (M10, objectif 20 studios actifs)**
```
/goal valider la V1.5 : tests e2e de la synchronisation labiale (flag on/off), du dashboard avancé, de la recherche full-text et du feedback loop passent en CI, et verify-performance-slo confirme que l'ajout de la détection faciale ne dégrade pas la cible de pipeline (vidéo 20 min < 10 min GPU, §17.1/§13.4) quand le flag est désactivé. Stop after 10 tries.
```
Dépend de : G-3.1 → G-3.6. **Jalon** M10 (§20.2).

---

## 7. Phase 4 — V2 (M10 → M15)

**G-4.1 — SSO Enterprise (SAML 2.0 / OIDC)**
```
/goal implémenter le SSO Enterprise (US-054, §15.2) support SAML 2.0/OIDC pour un fournisseur d'identité de test (ex. Azure AD ou Okta sandbox) : un test d'intégration authentifie un utilisateur via le flux SSO simulé et vérifie que son rôle studio est correctement mappé depuis les claims du fournisseur. Stop after 10 tries.
```
Dépend de : G-2.11. ⚠️ Opus recommandé.

**G-4.2 — Sous-groupes et équipes (plan Enterprise)**
```
/goal implémenter les sous-groupes/équipes au sein d'un grand studio avec droits d'accès dédiés (§16.3, ex. « Pôle jeunesse », « Pôle films ») : un test vérifie qu'un membre d'un sous-groupe ne voit que les projets de son périmètre sauf s'il a un rôle transverse. Stop after 8 tries.
```
Dépend de : G-4.1.

**G-4.3 — Édition collaborative temps réel avancée (CRDT)**
```
/goal remplacer le verrouillage optimiste par réplique par une édition collaborative temps réel caractère par caractère de type CRDT (§16.4) sur le champ texte des répliques : un test simule deux utilisateurs éditant simultanément la même réplique à des positions différentes et vérifie une convergence cohérente sans perte de frappe des deux côtés. Stop after 12 tries.
```
Dépend de : G-2.7. ⚠️ Opus recommandé (concurrence distribuée).

**G-4.4 — Séparation de sources audio**
```
/goal intégrer un modèle de séparation de sources (dialogue/musique/effets, §12.1) pour les fichiers fournis en mixage complet : un test compare le WER de transcription avant/après séparation sur un extrait de test à musique de fond forte, et confirme une amélioration mesurable, avec option désactivable si elle dégrade la précision sur certains contenus. Stop after 10 tries.
```
Dépend de : G-2.11.

**G-4.5 — API publique et webhooks**
```
/goal ouvrir une API publique documentée (§25.4) avec génération de SDK client à partir de l'OpenAPI 3.1 existant, et des webhooks (notification de fin de traitement, déclenchement d'export automatique) : un test vérifie qu'un webhook configuré reçoit bien un POST signé à la complétion d'un pipeline de test, avec retry en cas d'échec de livraison. Stop after 8 tries.
```
Dépend de : G-2.11.

**G-4.6 — Application mobile de consultation**
```
/goal livrer une application mobile de consultation en lecture seule (§25.6, périmètre explicitement exclu du MVP au §1.4) pour les rôles de supervision (DA, chef de projet) : consultation de projet, validation, commentaires — sans aucune fonction d'édition fine de la bande. Un test vérifie qu'aucun endpoint d'écriture sur les répliques n'est accessible depuis le client mobile (RBAC dédié). Stop after 10 tries.
```
Dépend de : G-4.5.

**G-4.7 — Jalon V2 (M15, objectif 50 studios actifs)**
```
/goal valider la V2 : tests e2e SSO, sous-groupes, édition CRDT, séparation de sources, API publique + webhooks et application mobile passent en CI ; le SLA de disponibilité ≥ 99,5 % mensuel (§1.3, §17.1) est vérifiable via le monitoring uptime configuré ; verify-security-baseline confirme l'absence de régression sur l'ensemble du périmètre V2. Stop after 12 tries.
```
Dépend de : G-4.1 → G-4.6. **Jalon** M15 (§20.2, §1.3). Checkpoint majeur avant la Phase 5 — au-delà de M15, le CDC devient volontairement exploratoire (§20.1) : revue humaine et cadrage produit dédié recommandés avant de lancer les goals V3+.

---

## 8. Phase 5 — V3+ (M15+, périmètre exploratoire §20.1, §25)

**G-5.1 — Assistance IA à l'adaptation/traduction**
```
/goal construire un prototype d'assistance à l'adaptation (§25.1) qui propose des reformulations respectant le calibrage syllabique disponible, en complément et non en remplacement du travail de l'adaptateur : un test vérifie que la suggestion n'est jamais appliquée automatiquement au texte (toujours une proposition acceptable/rejetable explicitement), et qu'au moins 70 % des suggestions générées sur un corpus de test respectent la fenêtre de calibrage syllabique cible. Stop after 12 tries.
```
Dépend de : G-4.7.

**G-5.2 — Marketplace de profils typographiques**
```
/goal implémenter la bibliothèque communautaire de profils typographiques et règles de segmentation partagées entre studios en opt-in (§25.3) : un test vérifie qu'un studio ne peut publier un profil qu'après consentement explicite, et qu'un autre studio peut importer un profil publié sans pouvoir modifier l'original (fork, pas d'édition partagée). Stop after 8 tries.
```
Dépend de : G-4.7.

**G-5.3 — IA de suggestion de découpage de répliques avancée**
```
/goal améliorer le moteur de génération (au-delà des règles heuristiques de G-1.8) avec un modèle de suggestion de découpage tenant compte du rythme théâtral et de la respiration dramatique (§25.5) : sur un jeu de test annoté par des professionnels, le taux d'acceptation sans retouche des répliques suggérées par ce module dépasse celui du moteur heuristique de base d'au moins 10 points. Stop after 12 tries.
```
Dépend de : G-5.1.

**G-5.4 — Module de doublage assisté par IA (exploratoire, garde-fous stricts)**
```
/goal construire un POC cadré et documenté de module de doublage assisté par IA identifié comme exploratoire par le CDC (§20.1) : le périmètre doit rester strictement de la préparation/assistance (aucune génération de voix de synthèse commerciale, cf. hors périmètre explicite §1.4), livré derrière un feature flag désactivé par défaut, avec un document listant les limites de fiabilité mesurées sur le corpus de test. Stop after 10 tries.
```
Dépend de : G-5.3. ⚠️ Opus recommandé, revue humaine obligatoire avant toute activation — ce module touche au périmètre explicitement exclu par le commanditaire (§1.4) et nécessite validation produit, pas seulement technique.

**G-5.5 — Réentraînement de modèles propriétaires sur corpus doublage FR**
```
/goal mettre en place le pipeline de fine-tuning des modèles heuristiques (prosodie, émotion) sur le corpus constitué par le feedback loop (G-3.6), avec consentement contractuel studio et sans réentraînement des modèles de fondation tiers (§8.5, §25.5) : un test compare la précision du modèle fine-tuné vs. le modèle générique sur un jeu de validation held-out, et confirme une amélioration mesurable sans dégradation sur les cas hors-corpus. Stop after 12 tries.
```
Dépend de : G-3.6, G-4.7.

**G-5.6 — Extension internationale des profils typographiques**
```
/goal étendre les profils typographiques et l'interface multilingue aux conventions de doublage italiennes, espagnoles et allemandes (§25.2) en s'appuyant sur le pipeline de transcription déjà multilingue : un test vérifie qu'un profil typographique par pays applique des codes différents au même texte source, et que l'interface change correctement de langue sans casser les raccourcis clavier existants (§14.4). Stop after 10 tries.
```
Dépend de : G-5.2.

---

## 9. Après la V3+ : passer en mode routine (`/schedule`)

Une fois V3+ livrée, la plupart du travail devient récurrent plutôt que "nouveau développement" — c'est le terrain des **boucles proactives**, pas de `/goal` ponctuel :

```
/schedule every hour: vérifier #rythmoai-feedback pour les rapports de bug remontés par les studios pilotes. /goal : ne pas s'arrêter tant que chaque rapport trouvé cette exécution n'est pas trié, traité et répondu. Pour corriger un bug, explorer 3 solutions en worktrees parallèles et faire réviser par un juge de façon contradictoire.
```

Autres candidats à `/schedule`/`/loop` post-V3+ : montée de version des dépendances (pip-audit/npm audit hebdomadaire), triage des tickets de studio, revue nocturne des PR fusionnées, suivi des SLO de production.

---

## 10. Tableau récapitulatif de correspondance

| Goal | Chapitre(s) CDC | Epic / US |
|---|---|---|
| G-0.1–G-0.6 | §6, §9, §15.2-15.3, §18.3, §19.2 | Socle technique |
| G-1.1–G-1.16 | §8, §11–14, §16, §17.1, §21.1-21.3, §21.5-21.6 | MVP (M0→M4) |
| G-2.1–G-2.11 | §2.4, §8.2.4-8.2.5, §12.3, §15.2, §16.4, §21.2-21.6 | V1 (M4→M7) |
| G-3.1–G-3.7 | §8.2.6, §11.4, §14.2.1, §16.1, §16.3, §8.5 | V1.5 (M7→M10) |
| G-4.1–G-4.7 | §12.1, §15.2, §16.3-16.4, §25.4, §25.6 | V2 (M10→M15) |
| G-5.1–G-5.6 | §25.1-25.3, §25.5 | V3+ (M15+) |

*Document généré à partir de CDC_RythmoAI.docx (v1.0, 05/08/2026). La syntaxe exacte des commandes Claude Code peut évoluer — vérifiez `code.claude.com/docs/en/goal` avant un run long.*
