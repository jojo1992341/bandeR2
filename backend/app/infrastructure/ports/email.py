"""
Port d'Email (§6.2 CDC)

Interface stable pour l'envoi d'emails. Les adaptateurs (SMTP, API email,
mémoire pour tests) doivent implémenter cette interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class EmailPort(ABC):
    """
    Interface pour l'envoi d'emails.
    
    Permet l'envoi d'emails transactionnels et marketing via différents
    backends (SMTP, SendGrid, SES, etc.).
    """
    
    @abstractmethod
    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        attachments: Optional[list[dict]] = None,
    ) -> dict:
        """
        Envoie un email.
        
        Args:
            to: Adresse email du destinataire.
            subject: Sujet de l'email.
            body: Corps de l'email (texte brut).
            html_body: Corps de l'email (HTML, optionnel).
            from_address: Adresse expéditeur (défaut: config).
            reply_to: Adresse de réponse (optionnel).
            cc: Liste des destinataires en copie.
            bcc: Liste des destinataires en copie cachée.
            attachments: Liste d'attachments (dict avec 'filename', 'content', 'mime_type').
            
        Returns:
            Dictionnaire avec 'success' (bool), 'message_id' (str|None), 'error' (str|None).
        """
        ...
    
    @abstractmethod
    def send_template(
        self,
        to: str,
        template_name: str,
        context: dict,
        from_address: Optional[str] = None,
        subject_override: Optional[str] = None,
    ) -> dict:
        """
        Envoie un email depuis un template.
        
        Args:
            to: Adresse email du destinataire.
            template_name: Nom du template.
            context: Variables de contexte pour le template.
            from_address: Adresse expéditeur (défaut: config).
            subject_override: Sujet alternatif.
            
        Returns:
            Dictionnaire avec 'success', 'message_id', 'error'.
        """
        ...
    
    @abstractmethod
    def send_bulk_email(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        batch_size: int = 100,
    ) -> dict:
        """
        Envoie un email à plusieurs destinataires (en lot).
        
        Args:
            recipients: Liste des adresses email.
            subject: Sujet de l'email.
            body: Corps de l'email (texte brut).
            html_body: Corps de l'email (HTML, optionnel).
            batch_size: Nombre d'emails par lot.
            
        Returns:
            Dictionnaire avec 'success', 'sent_count', 'failed_count', 'errors'.
        """
        ...
    
    @abstractmethod
    def health_check(self) -> dict:
        """
        Vérifie la santé du service d'email.
        
        Returns:
            Dictionnaire avec le statut.
        """
        ...
