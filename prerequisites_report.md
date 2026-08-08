# Rapport de vérification des prérequis §18.2 — CDC RythmoAI v2

> **Généré le** 2026-08-07T14:35:09+00:00  
> **Machine** Linux e2b.local 6.1.158+ #1 SMP PREEMPT_DYNAMIC Fri Jul 17 14:31:34 UTC 2026 x86_64 GNU/Linux  
> **OS détecté** Debian GNU/Linux 13 (trixie) — **écart de développement** : cible de production = Windows 10/11 ou Windows Server 2019+ (§18.5).  
> **Contrainte §18.1** : Pas de Docker / Kubernetes / conteneurs. Toute installation reste processus/service Windows natif sur la cible.  
> **Script réutilisable** : `/home/user/install.ps1` (origine G-05 / §18.4) — logiques d'installation silencieuse via `winget` + liens manuels.  

## Résumé par prérequis (§18.2)

| # | Prérequis (§18.2) | Présence | Version détectée | Action effectuée | Notes / Lien manuel si nécessaire |
|---|---|---|---|---|---|
| 1 | Windows 10/11 ou Windows Server 2019+ | NON APPLICABLE (machine Linux) | N/A | Écart documenté — cible Windows 10/11 ou Server 2019+ (§18.2, §18.5) | Développement local sur Debian 13 (Trixie). Pour production : OS Windows natif requis ; aucune conteneurisation (§18.1). Lien : https://www.microsoft.com/windows |
| 2 | Python 3.13+ (installateur officiel Windows) | OK | 3.13.14 | Déjà présent — chemin vérifié : /usr/local/bin/python3 | Version détectée 3.13.14 (cible 3.13+). Installation silencieuse Windows : winget install --id Python.Python.3.13 --silent --accept-package-agreements --accept-source-agreements | Manuel : https://www.python.org/downloads/windows/ |
| 3 | Node.js 20 LTS+ | OK | 20.20.2 | Déjà présent — chemin vérifié : /usr/bin/node | Version détectée 20.20.2 (cible 20 LTS+). Installation silencieuse Windows : winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements | Manuel : https://nodejs.org/en/download/ |
| 4 | PostgreSQL 16+ (installateur EDB Windows) | OK (équivalent Linux) | 17.10 | Équivalent Linux installé — PostgreSQL 17.10 (service actif : active (exited)) | Client/serveur : /usr/lib/postgresql/17/bin/psql / /usr/lib/postgresql/17/bin/postgres. Pour Windows cible (EDB) : https://www.enterprisedb.com/downloads/postgres-postgresql-downloads — winget : PostgreSQL.PostgreSQL.16 — Version cible 16+. |
| 5 | Memurai (Redis Windows) dernière version stable | OK (équivalent Linux — Redis 8.0.2) | v=8.0.2 | Équivalent Linux installé — service actif : active (running) — binaire : /usr/bin/redis-server | Memurai est le port Windows officiel de Redis (§18.2). Pour Windows : https://www.memurai.com/download/ — winget : Memurai.MemuraiDeveloper — Version cible : dernière stable (actuellement 4.x / 8.x compatible). |
| 6 | FFmpeg (build Windows essentials/full) | OK (équivalent Linux — FFmpeg 7.1.5) | 7.1.5-0+deb13u1 Copyright (c) 2000-2026 the FFmpeg developers | Équivalent Linux installé — binaire : /usr/bin/ffmpeg | Pour Windows : build Essentials (Gyan) https://www.gyan.dev/ffmpeg/builds/ — winget : Gyan.FFmpeg.Essentials — Version cible : dernière stable (actuellement 7.1.5+). |
| 7 | Pilotes NVIDIA + CUDA 12+ / cuDNN (si GPU) | Non détecté | N/A | Conditionnel — aucun GPU détecté (§18.2 : 'si GPU disponible') | Fichier /proc/driver/nvidia/version absent ; nvidia-smi non trouvé. Si GPU présent : pilotes https://www.nvidia.com/Download/index.aspx — CUDA Toolkit https://developer.nvidia.com/cuda-downloads — cuDNN https://developer.nvidia.com/cudnn. Version cible CUDA 12+. |
| 8 | NSSM (dernière version) | MANQUANT (Windows uniquement) | N/A | À installer manuellement sur Windows — winget : NSSM.NSSM | Manuel : https://nssm.cc/download | Sur Linux, équivalent natif : systemctl / systemd (postgresql, redis-server, nginx déjà enregistrés). Aucune conteneurisation (§18.1). Version cible : dernière stable (actuellement 2.24-101-g897c7ad+). |
| 9 | Nginx pour Windows (build stable officiel) | OK (équivalent Linux — Nginx 1.26.3) | 1.26.3 | Équivalent Linux installé — service actif : active (running) — chemin vérifié : /usr/sbin/nginx (dans /usr/sbin) | PATH vérifié : /usr/sbin ajouté. Pour Windows : build stable officiel https://nginx.org/en/download.html — winget : nginxinc.nginx — Version cible : 1.26.x+ (stable). |

## Vérification du PATH — binaire par binaire

| Binaire | Chemin détecté | Dans PATH ? |
|---|---|---|
| python3 | /usr/local/bin/python3 | OUI |
| node | /usr/bin/node | OUI |
| psql | /usr/lib/postgresql/17/bin/psql | OUI |
| redis-server | /usr/bin/redis-server | OUI |
| ffmpeg | /usr/bin/ffmpeg | OUI |
| nginx | /usr/sbin/nginx | OUI |

> **Note** : Sur la machine de développement Linux, `/usr/sbin` et `/usr/lib/postgresql/17/bin` ont été ajoutés au PATH pour la vérification. Sur la cible Windows, l'installateur `winget` met automatiquement à jour la variable d'environnement `PATH` au niveau système ; une nouvelle session (ou redémarrage) est parfois nécessaire après installation silencieuse.

## Liens d'installation officiels et versions cibles attendues (§18.2)

| Prérequis | Lien officiel | Version cible attendue | Méthode silencieuse (winget) |
|---|---|---|---|
| Windows OS | https://www.microsoft.com/windows | Windows 10/11 ou Windows Server 2019+ | N/A (OS hôte) |
| Python 3.13+ | https://www.python.org/downloads/windows/ | 3.13+ | `winget install --id Python.Python.3.13 --silent --accept-package-agreements --accept-source-agreements` |
| Node.js 20 LTS+ | https://nodejs.org/en/download/ | 20 LTS (actuellement 20.20.2+) | `winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements` |
| PostgreSQL 16+ (EDB) | https://www.enterprisedb.com/downloads/postgres-postgresql-downloads | 16+ | `winget install --id PostgreSQL.PostgreSQL.16 --silent --accept-package-agreements --accept-source-agreements` |
| Memurai (Redis Windows) | https://www.memurai.com/download/ | Dernière stable (4.x / 8.x compat.) | `winget install --id Memurai.MemuraiDeveloper --silent --accept-package-agreements --accept-source-agreements` |
| FFmpeg | https://www.gyan.dev/ffmpeg/builds/ | Essentiels/Full (7.x+) | `winget install --id Gyan.FFmpeg.Essentials --silent --accept-package-agreements --accept-source-agreements` |
| NVIDIA + CUDA 12+ / cuDNN | https://www.nvidia.com/Download/index.aspx — https://developer.nvidia.com/cuda-downloads — https://developer.nvidia.com/cudnn | CUDA 12+ (si GPU) | N/A (pilotes matériels) |
| NSSM | https://nssm.cc/download | Dernière stable | `winget install --id NSSM.NSSM --silent --accept-package-agreements --accept-source-agreements` |
| Nginx Windows | https://nginx.org/en/download.html | Build stable officiel 1.26.x+ | `winget install --id nginxinc.nginx --silent --accept-package-agreements --accept-source-agreements` |

---

## Conclusion et condition d'achèvement

- **Tous les prérequis du §18.2 sont couverts** : soit **OK** avec version détectée (équivalents Linux installés et services actifs), soit **explicitement documentés** comme nécessitant une action manuelle sur la cible Windows (lien + version + méthode winget silencieuse).
- **Aucun prérequis n'est dans un état inconnu** ; le rapport attribue un statut explicite à chacun des 9 éléments listés au §18.2.
- **Pas de conteneurisation** (§18.1) : PostgreSQL, Redis (Memurai), Nginx et FFmpeg fonctionnent comme processus/services natifs Linux (équivalents de développement) ; sur Windows, ils seront installés nativement via `winget` ou installateurs officiels et enregistrés comme services Windows (NSSM pour API/workers/Nginx si nécessaire, selon §18.3).
- **Écart de développement** (§18.5) clairement signalé : la machine de développement est Linux (Debian 13) ; la cible de livraison reste Windows. Les équivalents installés permettent de valider la portabilité du code (Python 3.13, Node 20, PostgreSQL 17, Redis 8, FFmpeg 7, Nginx 1.26) sans altérer la cible de production.
- **Script réutilisable fourni** : `/home/user/install.ps1` (origine G-05 / §18.4) — contient la logique de vérification, l'appel `winget` silencieux, la vérification PATH et la génération du rapport. Il doit être exécuté sur la machine cible Windows pour finaliser l'installation des éléments encore manquants (NSSM, Memurai, EDB PostgreSQL, pilotes NVIDIA si GPU).
