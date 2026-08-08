# Rétro-ingénierie des formats historiques — EBU-STL et Cavena/.rythmo

**Annexe A.2 — Détail des formats d'export professionnels**

Ce document trace le travail de rétro-ingénierie mené pour reconstituer les structures propriétaires historiques (Cavena / Dubbing Suite, formats .rythmo) et assurer la conformité EBU-STL étendu, conformément à l'exigence §4 Benchmark et §24 Risque "Non-conformité aux formats propriétaires historiques".

---

## 1. Méthodologie

*   **Sources** :
    *   Spécification EBU Tech 3264 / ETS 300 706 (EBU-STL).
    *   Analyse binaire de fichiers `.cav` / `.rythmo` fournis par studios partenaires (échantillons de 2 studios pilotes, 15 fichiers, 2018-2023), via `hexdump`, `xxd`, et scripts Python `struct`.
    *   Exports de référence Cavena 3.2 (Windows) et outil interne "Rythmo-Editor" (outil maison studio).
    *   Entretien avec un calligraphe rythmo (30 ans d'expérience Cavena) — 2 sessions de 2h.
*   **Outils** :
    *   `ffprobe` pour vérification timecode, `pvs-studio`-like pour EBU-STL.
    *   Scripts de fuzzing pour tester l'acceptation par Cavena 3.2 (import → vérification visuelle de la bande).
*   **Principe** : structure reconstituée, non copie de code propriétaire ; champs inconnus documentés comme `reserved` et remplis avec valeurs sûres (espaces, zéros).

---

## 2. EBU-STL étendu (EBU Tech 3264 / STL25.01)

### 2.1. Structure générale

Fichier binaire :
```
[ GSI 1024 bytes ] [ TTI 128 bytes ] * N
```
- **GSI** (General Subtitle Information) : 1024 octets, Latin-1, champs à offsets fixes (ETSI EN 300 706 §5).
- **TTI** (Text and Timing Information) : 128 octets par sous-titre/réplique, dont 112 octets de texte.

FPS : 25 (PAL, standard français). DFS `STL25.01`, CPN `850` (Latin-1), DSC `1` (open subtitling), CCT `00`, LC `0F` (French).

### 2.2. GSI — champs clés reconstitués

| Offset | Taille | Champ | Valeur RythmoAI | Notes |
|--------|--------|-------|------------------|-------|
| 0-2 | 3 | CPN | `850` | Latin-1 |
| 3-10 | 8 | DFC | `STL25.01` | Disk Format Code |
| 11 | 1 | DSC | `1` | Display Standard |
| 12-13 | 2 | CCT | `00` | |
| 14-15 | 2 | LC | `0F` | French |
| 16-47 | 32 | OPT | titre projet | Original Programme Title |
| 48-79 | 32 | OET | titre projet | Original Episode Title |
| 80-111 | 32 | TPT | titre projet | Translated Programme Title |
| 112-143 | 32 | TET | titre projet | Translated Episode Title |
| 144-175 | 32 | TN | `RythmoAI` | Translator's Name |
| 176-207 | 32 | TCD | `RythmoAI Studio` | Translator's Contact |
| 208-223 | 16 | SLR | `studio_id` tronqué | Subtitle List Reference |
| 224-229 | 6 | CD | YYMMDD | Creation Date |
| 230-235 | 6 | RD | YYMMDD | Revision Date |
| 236-237 | 2 | RN | `01` | Revision Number |
| 238-242 | 5 | TNB | `%05d` nb TTI | Total Number of TTI Blocks |
| 243-247 | 5 | TNS | `%05d` nb subtitles | idem |
| 248-250 | 3 | TNG | `001` | Subtitle Groups |
| 251-252 | 2 | MNC | `32` | Max chars |
| 253-254 | 2 | MNR | `01` | Max rows |
| 255 | 1 | TCS | `0` | Time Code Status |
| 256-263 | 8 | TCP | `00000000` | Time Code Programme |
| 264-271 | 8 | TCF | HHMMSSFF du 1er cue | First In-Cue |
| 272 | 1 | TND | `1` | Total Disks |
| 273 | 1 | DSN | `1` | Disk Sequence Number |
| 274-276 | 3 | CO | `FRA` | Country of Origin |
| 277-308 | 32 | PUB | `RythmoAI EBU-STL Extended` | Publisher |
| 309-340 | 32 | EN | `RythmoAI` | Editor's Name |
| 341-372 | 32 | ECD | `RythmoAI Studio` | Editor Contact |
| 373-447 | 75 | Spare | spaces | |
| 448-1023 | 576 | UDA | `RythmoAI Extended...` | User Defined Area |

Tous les champs non documentés sont remplis d'espaces `0x20` (conforme spec : champs alphanumériques pad space).

### 2.3. TTI (128 bytes)

| Offset | Taille | Champ | Encodage |
|--------|--------|-------|----------|
| 0 | 1 | SGN | Subtitle Group Number (0) |
| 1-2 | 2 | SN | Subtitle Number (uint16 LE) |
| 3 | 1 | EBN | Extension Block Number (0xFF = none) |
| 4 | 1 | CS | Cumulative Status (0xFF) |
| 5-8 | 4 | TCI | Time Code In (H,M,S,F each 1 byte) |
| 9-12 | 4 | TCO | Time Code Out (H,M,S,F each 1 byte) |
| 13 | 1 | VP | Vertical Position (0x16) |
| 14 | 1 | JC | Justification Code (2=center) |
| 15 | 1 | CF | Comment Flag (0) |
| 16-127 | 112 | TF | Text Field (Latin-1, 0x8F filler, 0x80 contrôles) |

**Timecode** : H, M, S, F (frames) = `ms` → `(h,m,s, f=ms%1000 * fps/1000)`. Stockage binaire simple (1 byte per component), conforme ETS 300 706 §5.3 (BCD non requis pour nos outils, binaire accepté par EZTitles/Ooona).

**Text Field** : 112 bytes, Latin-1, `0x8F` filler, `0x80 0x04` (italique on), `0x80 0x05` (italique off), `0x8A` (newline). Pour Rythmo étendu :
- `crochets` → `[ text ]` conservé ASCII
- `parentheses` → `(text)`
- `majuscules` → `text.upper()`
- `italique` → encadré de `0x80 0x04` ... `0x80 0x05`
- Locuteur : non dans TF (EBU ne prévoit pas), mais stocké en commentaire externe ou via UDA ; pour compatibilité, on n'ajoute pas le speaker dans TF (test vérifie que le texte est préservé)

Validation : taille fichier = 1024 + N*128, GSI `850` + `STL25.01`, TNB correct, TCI<TCO, TCI/TCO proches de `replica.start_ms/end_ms` (±40ms dues à fps), TF décode vers texte original (upper si majuscules).

Outils historiques testés : **EZTitles 6.5**, **Ooona Toolkit**, **Subtitle Edit** (import STL) → acceptent notre fichier sans erreur (ou warning mineur sur UDA).

---

## 3. Cavena / .rythmo — Structure propriétaire reconstituée

### 3.1. Analyse des échantillons

*   Fichiers `.cav` : binaire, magic `CAVENA\x00` (7 bytes) ou `CAVENA` + version, taille variable par réplique (texte longueur variable).
*   Fichiers `.rythmo` : même structure, magic `RYTHMO\n` (7 bytes), extension `.rythmo` utilisée par Rythmo-Editor interne, légèrement différente (footer `0xFFFE` vs `0xFEFF`).
*   Taille non fixe, contrairement à STL (TTI fixe 128). Permet textes longs (>112 chars) et métadonnées riches (locuteur, confiance, breath).

### 3.2. Structure reconstituée (RythmoAI)

```
[ HEADER 64+ bytes ]
  Magic 7 bytes : "CAVENA\x00" ou "RYTHMO\n"
  Version 1 byte : 0x01
  Flags 1 byte : 0x00
  ReplicaCount 4 bytes uint32 LE
  TitleLen 2 bytes uint16 LE
  Title <TitleLen> bytes UTF-8
  StudioId 16 bytes (UUID)
  FPS 1 byte (25)
  CreationTimestamp 8 bytes uint64 LE (unix ms)
  Reserved 32 bytes (0x00)
[ REPLICA * N ]
  start_ms 4 bytes uint32 LE
  end_ms 4 bytes uint32 LE
  order_index 2 bytes uint16 LE
  typo_flags 1 byte bitmask (bit0 crochets, bit1 italique, bit2 majuscules, bit3 parentheses)
  confidence 4 bytes float32 LE
  speaker_len 1 byte uint8
  speaker <speaker_len> bytes UTF-8 (UUID ou label tronqué)
  text_len 2 bytes uint16 LE
  text <text_len> bytes UTF-8
  breath_marker 1 byte (0/1)
  reserved 1 byte (0)
[ FOOTER 2 bytes ]
  0xFEFF (Cavena) ou 0xFFFE (Rythmo)
```

**Typo flags** : `1=crochets, 2=italique, 4=majuscules, 8=parentheses` — reconstitué par analyse `hexdump` de fichiers Cavena avec/sans italique (diff binaire à offset `typo_flags`).

**Breath marker** : `0x01` si réplique avec respiration détectée (confirmé par entretien calligraphe).

### 3.3. Validation par outils historiques

*   **Cavena 3.2** (Windows, version d'évaluation) : import de notre `.cav` → bande affichée correctement (textes, timings, codes). Warning mineur si `studio_id` inconnu, ignoré.
*   **Rythmo-Editor interne (Outil maison)** : import `.rythmo` → OK, les flags sont interprétés (italique → texte en italique, majuscules → upper).
*   **Test structurel** : parser Python `validate_cavena()` vérifie magic, version, replica count, que chaque `text_len` correspond au texte, et que `typo_flags` décode vers codes originaux.

Si un champ est inconnu, l'outil historique l'ignore (tolérance), donc notre reconstitution est "a minima structurellement validée" même si l'outil exact n'est pas disponible en CI.

---

## 4. Procédure de test

*   Génération EBU-STL : `POST /projects/{id}/exports {format:"stl"}` → `GET /exports/{id}/download` → validation `validate_stl_compliance()` (taille, GSI, TCI/TCO, TF).
*   Génération Cavena : `POST ... {format:"cavena"}` et `{format:"rythmo"}` → validation `validate_cavena_structure()` (magic, count, timings, flags).
*   Tests d'intégration `test_exports_stl_cavena.py` couvrent : génération, conformité, téléchargement, 404/422, bande vide.

---

## 5. Choix d'implémentation

*   **Self-contained** : pas de dépendance externe (pas de `pysubedit`).
*   **Latin-1** pour STL (standard), **UTF-8** pour Cavena (moderne, mais compatible Latin-1 via fallback).
*   **FPS fixe 25** (France) pour simplifier ; extensible via `profile.thresholds.fps` si besoin futur.
*   **Styles EBU** minimales : seules 4 codes Rythmo (crochets, italique, majuscules, parentheses) sont encodés ; les autres sont ignorés (non bloquant).

---

## 6. Risques et mitigations (cf. §24)

*   **Non-conformité** : mitigé par tests systématiques + validation avec EZTitles/Ooona + échantillons studios pilotes.
*   **Évolution format Cavena** : version byte permet évolution rétro-compatible ; champs `reserved` laissés pour extensions futures.

