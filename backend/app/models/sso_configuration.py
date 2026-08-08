import uuid
from sqlalchemy import String, Boolean, DateTime, func, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from datetime import datetime
from typing import Optional

class SsoConfiguration(Base):
    """
    SSO Configuration §15.2 — SAML 2.0 / OIDC pour studios Enterprise
    Supporte Azure AD, Okta, Google Workspace
    Réservé au plan Enterprise (studio.plan == 'enterprise')
    """
    __tablename__ = "sso_configurations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    studio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("studios.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    
    # Provider : azure_ad, okta, google, generic
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")
    # Protocol : saml, oidc
    protocol: Mapped[str] = mapped_column(String(20), nullable=False, default="oidc")
    
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    
    # SAML 2.0 fields
    entity_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # SP Entity ID
    acs_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Assertion Consumer Service URL
    idp_entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # IdP Entity ID
    idp_sso_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # IdP SSO URL
    idp_x509_cert: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # IdP certificate for signature validation (PEM)
    idp_metadata_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sp_x509_cert: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # SP cert
    sp_private_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # SP private key
    name_id_format: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress")
    # Attribute mapping
    attribute_mapping: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=lambda: {"email": "email", "firstName": "givenName", "lastName": "surname"})
    
    # OIDC fields
    issuer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # OIDC Issuer (e.g., https://login.microsoftonline.com/{tenant}/v2.0)
    client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Should be encrypted in production
    authorization_endpoint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_endpoint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    jwks_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    userinfo_endpoint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scopes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="openid profile email")
    # OIDC attribute mapping
    oidc_attribute_mapping: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=lambda: {"email": "email", "sub": "sub", "name": "name"})
    
    # Common
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)  # Extra config
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    def is_saml(self) -> bool:
        return self.protocol.lower() == "saml"
    
    def is_oidc(self) -> bool:
        return self.protocol.lower() == "oidc"
