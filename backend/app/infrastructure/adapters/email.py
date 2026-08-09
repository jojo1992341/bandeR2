"""
Adaptateur d'Email SMTP (§6.2 CDC)

Implémente EmailPort en utilisant smtplib.
"""

from __future__ import annotations

from typing import Optional

from app.infrastructure.ports.email import EmailPort


class SmtpEmailAdapter(EmailPort):
    """
    Adaptateur Email utilisant SMTP.
    
    Implémente EmailPort pour l'envoi d'emails via SMTP.
    """
    
    def __init__(self, settings=None, smtp_client=None):
        """
        Initialise l'adaptateur SMTP.
        
        Args:
            settings: Configuration (défaut: get_settings()).
            smtp_client: Client SMTP pré-construit (pour les tests).
        """
        self._settings = settings
        self._smtp_client = smtp_client
        self._default_from = getattr(settings, "EMAIL_FROM", "noreply@rythmoai.local") if settings else "noreply@rythmoai.local"
    
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
        Envoie un email via SMTP.
        
        Note: Cette implémentation est un squelette. En production,
        il faudrait utiliser smtplib avec une configuration complète.
        """
        # Pour l'instant, simulation réussite (à implémenter avec smtplib)
        return {
            "success": True,
            "message_id": f"<{abs(hash(f'{to}{subject}'))}@rythmoai.local>",
            "error": None,
        }
    
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
        
        Note: Cette implémentation nécessite un moteur de template
        (Jinja2 par exemple).
        """
        # Simulation: render du template
        body = f"Template: {template_name}\nContext: {context}"
        subject = subject_override or f"[{template_name}] Notification"
        
        return self.send_email(
            to=to,
            subject=subject,
            body=body,
            from_address=from_address,
        )
    
    def send_bulk_email(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        batch_size: int = 100,
    ) -> dict:
        """
        Envoie un email en lot.
        
        Note: Cette implémentation est un squelette.
        """
        sent_count = 0
        failed_count = 0
        errors = []
        
        for i in range(0, len(recipients), batch_size):
            batch = recipients[i:i + batch_size]
            for recipient in batch:
                try:
                    result = self.send_email(
                        to=recipient,
                        subject=subject,
                        body=body,
                        html_body=html_body,
                    )
                    if result["success"]:
                        sent_count += 1
                    else:
                        failed_count += 1
                        errors.append({"recipient": recipient, "error": result["error"]})
                except Exception as e:
                    failed_count += 1
                    errors.append({"recipient": recipient, "error": str(e)})
        
        return {
            "success": failed_count == 0,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "errors": errors,
        }
    
    def health_check(self) -> dict:
        """Vérifie la santé du service d'email."""
        # Simulation: toujours healthy en mode test
        return {
            "status": "healthy",
            "email_type": "smtp",
            "default_from": self._default_from,
        }


class MemoryEmailAdapter(EmailPort):
    """
    Adaptateur d'Email en mémoire (pour les tests).
    
    Stocke les emails envoyés dans une liste pour inspection.
    """
    
    def __init__(self):
        """Initialise l'adaptateur mémoire."""
        self.sent_emails: list[dict] = []
    
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
        """Simule l'envoi d'un email."""
        email = {
            "to": to,
            "subject": subject,
            "body": body,
            "html_body": html_body,
            "from_address": from_address,
            "reply_to": reply_to,
            "cc": cc,
            "bcc": bcc,
            "attachments": attachments,
            "message_id": f"<{abs(hash(f'{to}{subject}'))}@test.local>",
            "timestamp": "2024-01-01T00:00:00Z",
        }
        
        self.sent_emails.append(email)
        
        return {
            "success": True,
            "message_id": email["message_id"],
            "error": None,
        }
    
    def send_template(
        self,
        to: str,
        template_name: str,
        context: dict,
        from_address: Optional[str] = None,
        subject_override: Optional[str] = None,
    ) -> dict:
        """Simule l'envoi d'un email depuis un template."""
        body = f"Template: {template_name}\nContext: {context}"
        subject = subject_override or f"[{template_name}] Notification"
        
        return self.send_email(
            to=to,
            subject=subject,
            body=body,
            from_address=from_address,
        )
    
    def send_bulk_email(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        batch_size: int = 100,
    ) -> dict:
        """Simule l'envoi en lot."""
        sent_count = 0
        failed_count = 0
        errors = []
        
        for recipient in recipients:
            try:
                result = self.send_email(
                    to=recipient,
                    subject=subject,
                    body=body,
                    html_body=html_body,
                )
                if result["success"]:
                    sent_count += 1
                else:
                    failed_count += 1
                    errors.append({"recipient": recipient, "error": result["error"]})
            except Exception as e:
                failed_count += 1
                errors.append({"recipient": recipient, "error": str(e)})
        
        return {
            "success": failed_count == 0,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "errors": errors,
        }
    
    def health_check(self) -> dict:
        """Vérifie la santé de l'adaptateur mémoire."""
        return {
            "status": "healthy",
            "email_type": "memory",
            "sent_count": len(self.sent_emails),
        }
    
    def get_sent_emails(self) -> list[dict]:
        """Retourne les emails envoyés (pour les tests)."""
        return self.sent_emails.copy()
    
    def clear(self) -> None:
        """Efface les emails enregistrés."""
        self.sent_emails.clear()
