"""
ProjectLifecycle §14.2 / §16.1 — Machine à états du cycle de vie d'un projet/bande rythmo.

Statuts (§16.1) :
  - Cree            : Projet initialisé, en attente d'upload du média
  - En_traitement   : Pipeline IA en cours d'exécution
  - Pret_pour_edition : Bande rythmo générée, disponible dans l'éditeur
  - En_edition      : Modifications manuelles en cours
  - En_relecture    : Soumis à validation du directeur artistique
  - Valide          : Bande rythmo approuvée, verrouillée en écriture sauf déverrouillage explicite
  - Exporte_Livre   : Export(s) générés et mis à disposition
  - Archive         : Projet clos, lecture seule

Règles :
  - Seules les transitions autorisées sont possibles (403 sinon)
  - Le statut Valide verrouille la bande en écriture (PATCH réplique → 403)
  - Le statut Archive est lecture seule (toute modification → 403)
  - Le déverrouillage explicite depuis Valide → retour à En_relecture
  - Le statut legacy "draft" est traité comme Pret_pour_edition (backward compatible)
"""

from enum import Enum
from typing import Optional


class ProjectStatus(str, Enum):
    """§16.1 — Statuts du cycle de vie d'un projet."""
    CREE = "Cree"
    EN_TRAITEMENT = "En_traitement"
    PRET_POUR_EDITION = "Pret_pour_edition"
    EN_EDITION = "En_edition"
    EN_RELECTURE = "En_relecture"
    VALIDE = "Valide"
    EXPORTE_LIVRE = "Exporte_Livre"
    ARCHIVE = "Archive"

    @property
    def label(self) -> str:
        """Libellé affiché dans l'UI."""
        labels = {
            "Cree": "Créé",
            "En_traitement": "En traitement",
            "Pret_pour_edition": "Prêt pour édition",
            "En_edition": "En édition",
            "En_relecture": "En relecture",
            "Valide": "Validé",
            "Exporte_Livre": "Exporté / Livré",
            "Archive": "Archivé",
        }
        return labels.get(self.value, self.value)

    @property
    def is_editable(self) -> bool:
        """La bande rythmo peut-elle être modifiée dans ce statut ?"""
        return self in (
            ProjectStatus.PRET_POUR_EDITION,
            ProjectStatus.EN_EDITION,
            ProjectStatus.EN_RELECTURE,
        )

    @property
    def is_readonly(self) -> bool:
        """Le projet est-il en lecture seule ?"""
        return self in (ProjectStatus.ARCHIVE,)


# Legacy status compatibility: old statuses mapped to new lifecycle
_LEGACY_STATUS_MAP = {
    "draft": ProjectStatus.PRET_POUR_EDITION,
    "Prêt pour édition": ProjectStatus.PRET_POUR_EDITION,
    "processing": ProjectStatus.EN_TRAITEMENT,
}


def _resolve_status(status_value: str) -> ProjectStatus:
    """Resolve a status string to ProjectStatus, handling legacy values."""
    if status_value in _LEGACY_STATUS_MAP:
        return _LEGACY_STATUS_MAP[status_value]
    return ProjectStatus(status_value)


# ── Graphe des transitions autorisées §16.1 ──────────────────

TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.CREE: {
        ProjectStatus.EN_TRAITEMENT,
    },
    ProjectStatus.EN_TRAITEMENT: {
        ProjectStatus.PRET_POUR_EDITION,
        ProjectStatus.CREE,  # retry/reset si échec pipeline
    },
    ProjectStatus.PRET_POUR_EDITION: {
        ProjectStatus.EN_EDITION,
        ProjectStatus.ARCHIVE,
    },
    ProjectStatus.EN_EDITION: {
        ProjectStatus.EN_RELECTURE,
        ProjectStatus.PRET_POUR_EDITION,  # retour si plus personne n'édite
    },
    ProjectStatus.EN_RELECTURE: {
        ProjectStatus.VALIDE,
        ProjectStatus.EN_EDITION,  # retour si corrections nécessaires
        ProjectStatus.PRET_POUR_EDITION,
    },
    ProjectStatus.VALIDE: {
        ProjectStatus.EXPORTE_LIVRE,
        ProjectStatus.EN_RELECTURE,  # déverrouillage explicite (retour en relecture)
        ProjectStatus.ARCHIVE,
    },
    ProjectStatus.EXPORTE_LIVRE: {
        ProjectStatus.ARCHIVE,
        ProjectStatus.VALIDE,  # retour si problème de livraison
    },
    ProjectStatus.ARCHIVE: {
        ProjectStatus.EXPORTE_LIVRE,  # désarchivage exceptionnel
    },
}


class TransitionResult:
    """Résultat d'une tentative de transition."""
    def __init__(self, success: bool, from_status, to_status: Optional[ProjectStatus], reason: str = ""):
        self.success = success
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason


def is_transition_allowed(from_status: str, to_status: str) -> bool:
    """
    Vérifie si la transition de `from_status` à `to_status` est autorisée.
    Accepte les valeurs string (stockées en DB) ou enum.
    """
    try:
        src = _resolve_status(from_status)
    except ValueError:
        return False
    try:
        dst = ProjectStatus(to_status)
    except ValueError:
        return False
    return dst in TRANSITIONS.get(src, set())


def attempt_transition(from_status: str, to_status: str) -> TransitionResult:
    """
    Tente une transition et retourne le résultat détaillé.
    """
    try:
        src = _resolve_status(from_status)
    except ValueError:
        # Unknown/legacy source — allow transition to any known status (backward compat)
        try:
            dst = ProjectStatus(to_status)
            return TransitionResult(True, from_status, dst, f"Transition (legacy source) → {dst.label}")
        except ValueError:
            return TransitionResult(False, from_status, None, f"Statut cible inconnu : {to_status}")
    try:
        dst = ProjectStatus(to_status)
    except ValueError:
        return TransitionResult(False, src, None, f"Statut cible inconnu : {to_status}")

    if dst in TRANSITIONS.get(src, set()):
        return TransitionResult(True, src, dst, f"Transition {src.label} → {dst.label} autorisée")
    else:
        allowed = TRANSITIONS.get(src, set())
        allowed_labels = ", ".join(sorted(s.label for s in allowed)) if allowed else "aucune"
        return TransitionResult(
            False, src, dst,
            f"Transition {src.label} → {dst.label} interdite. Transitions autorisées depuis {src.label} : {allowed_labels}",
        )


def can_edit_replica(project_status: str) -> bool:
    """
    §16.1 — Vérifie si une réplique peut être modifiée selon le statut du projet.
    En statut Valide ou Archive, l'édition est interdite sauf déverrouillage explicite.
    Les statuts legacy ("draft") sont considérés comme éditables.
    """
    try:
        status = _resolve_status(project_status)
    except ValueError:
        # Unknown status → allow by default (backward compatibility)
        return True
    return status.is_editable


def get_allowed_transitions(from_status: str) -> list[str]:
    """Retourne la liste des statuts cibles autorisés depuis un statut donné."""
    try:
        src = _resolve_status(from_status)
    except ValueError:
        return []
    return sorted(s.value for s in TRANSITIONS.get(src, set()))


def get_all_statuses() -> list[dict]:
    """Retourne tous les statuts avec leurs métadonnées."""
    return [
        {
            "value": s.value,
            "label": s.label,
            "is_editable": s.is_editable,
            "is_readonly": s.is_readonly,
        }
        for s in ProjectStatus
    ]
