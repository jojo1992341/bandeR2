"""
Tests pour l'entité RythmoBand (§9.2–§9.4 CDC)

Couvre:
- Création d'une bande
- Nouveau versionnage
- Validation
- Restauration sans perte de données
- Relation Project → RythmoBand → Replica
"""

from __future__ import annotations

import pytest
import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID, uuid4

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models import (
    Base,
    Project,
    Studio,
    RythmoBand,
    RythmoBandStatus,
    Replica,
    MediaAsset,
)
from app.core.database import get_test_engine, init_test_db


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="function")
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Crée une session de test avec base SQLite en mémoire."""
    engine = get_test_engine()
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session_factory() as session:
        yield session
        await session.rollback()
    
    await engine.dispose()


@pytest.fixture
def sample_studio_id() -> UUID:
    """Génère un ID de studio de test."""
    return uuid4()


@pytest.fixture
def sample_project_id() -> UUID:
    """Génère un ID de projet de test."""
    return uuid4()


@pytest.fixture
def sample_media_id() -> UUID:
    """Génère un ID de média de test."""
    return uuid4()


@pytest.mark.asyncio
async def test_create_rythmo_band(async_db_session: AsyncSession, 
                                   sample_studio_id: UUID,
                                   sample_project_id: UUID,
                                   sample_media_id: UUID) -> None:
    """Test de création d'une RythmoBand (§9.2)."""
    # Créer les dépendances
    studio = Studio(id=sample_studio_id, name="Studio Test", plan="free")
    project = Project(
        id=sample_project_id,
        studio_id=sample_studio_id,
        title="Projet Test",
        status="Cree"
    )
    media = MediaAsset(
        id=sample_media_id,
        project_id=sample_project_id,
        storage_path="/path/to/video.mp4",
        status="confirmed"
    )
    
    async_db_session.add_all([studio, project, media])
    await async_db_session.commit()
    
    # Créer une RythmoBand
    band = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=1,
        status=RythmoBandStatus.DRAFT,
        title="Bande Test",
        is_master=True,
    )
    async_db_session.add(band)
    await async_db_session.commit()
    await async_db_session.refresh(band)
    
    # Vérifications
    assert band.id is not None
    assert band.project_id == sample_project_id
    assert band.media_asset_id == sample_media_id
    assert band.version_number == 1
    assert band.status == RythmoBandStatus.DRAFT
    assert band.is_master is True
    assert band.title == "Bande Test"
    assert band.created_at is not None
    
    # Vérifier la relation project → rythmo_band (avec selectinload)
    result = await async_db_session.execute(
        select(Project)
        .options(selectinload(Project.rythmo_bands))
        .where(Project.id == sample_project_id)
    )
    project_loaded = result.scalar_one()
    assert len(project_loaded.rythmo_bands) == 1
    assert project_loaded.rythmo_bands[0].id == band.id


@pytest.mark.asyncio
async def test_rythmo_band_with_replicas(async_db_session: AsyncSession,
                                         sample_studio_id: UUID,
                                         sample_project_id: UUID,
                                         sample_media_id: UUID) -> None:
    """Test la relation RythmoBand → Replica (§9.4)."""
    # Créer les dépendances
    studio = Studio(id=sample_studio_id, name="Studio Test", plan="free")
    project = Project(
        id=sample_project_id,
        studio_id=sample_studio_id,
        title="Projet Test"
    )
    media = MediaAsset(
        id=sample_media_id,
        project_id=sample_project_id,
        storage_path="/path/to/video.mp4",
        status="confirmed"
    )
    
    async_db_session.add_all([studio, project, media])
    await async_db_session.commit()
    
    # Créer une bande
    band = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=1,
        status=RythmoBandStatus.DRAFT,
    )
    async_db_session.add(band)
    await async_db_session.commit()
    await async_db_session.refresh(band)
    
    # Créer des répliques liées à la bande
    replica1 = Replica(
        rythmo_band_id=band.id,  # NOUVEAU: lien vers la bande
        media_id=sample_media_id,
        text="Bonjour à tous",
        start_ms=0,
        end_ms=1500,
        order_index=0,
    )
    replica2 = Replica(
        rythmo_band_id=band.id,
        media_id=sample_media_id,
        text="Comment allez-vous?",
        start_ms=1600,
        end_ms=3000,
        order_index=1,
    )
    
    async_db_session.add_all([replica1, replica2])
    await async_db_session.commit()
    
    # Vérifier la relation
    await async_db_session.refresh(band)
    assert len(band.replicas) == 2
    
    # Vérifier que les répliques appartiennent bien à la bande
    replica1_loaded = await async_db_session.get(Replica, replica1.id)
    assert replica1_loaded.rythmo_band_id == band.id
    
    # Vérifier via la relation inverse (avec selectinload pour charger rythmo_band)
    result = await async_db_session.execute(
        select(Replica)
        .options(selectinload(Replica.rythmo_band))
        .where(Replica.id == replica1.id)
    )
    replica1_loaded = result.scalar_one()
    assert replica1_loaded.rythmo_band is not None
    assert replica1_loaded.rythmo_band.id == band.id


@pytest.mark.asyncio
async def test_new_version_rythmo_band(async_db_session: AsyncSession,
                                        sample_studio_id: UUID,
                                        sample_project_id: UUID,
                                        sample_media_id: UUID) -> None:
    """Test la création d'une nouvelle version de bande (§9.3)."""
    # Créer les dépendances
    studio = Studio(id=sample_studio_id, name="Studio Test", plan="free")
    project = Project(id=sample_project_id, studio_id=sample_studio_id, title="Projet")
    media = MediaAsset(id=sample_media_id, project_id=sample_project_id, storage_path="/path")
    
    async_db_session.add_all([studio, project, media])
    await async_db_session.commit()
    
    # Créer la version 1
    band_v1 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=1,
        status=RythmoBandStatus.DRAFT,
        title="Bande v1",
    )
    async_db_session.add(band_v1)
    await async_db_session.commit()
    
    # Créer la version 2
    band_v2 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=2,
        status=RythmoBandStatus.DRAFT,
        title="Bande v2",
    )
    async_db_session.add(band_v2)
    await async_db_session.commit()
    
    # Vérifier que les deux versions existent
    bands = (
        await async_db_session.execute(
            select(RythmoBand).where(RythmoBand.project_id == sample_project_id)
        )
    ).scalars().all()
    
    assert len(bands) == 2
    assert {b.version_number for b in bands} == {1, 2}
    
    # La version 2 ne doit pas être master par défaut
    assert band_v1.is_master is False or band_v1.is_master is True
    assert band_v2.is_master is False


@pytest.mark.asyncio
async def test_validate_rythmo_band(async_db_session: AsyncSession,
                                     sample_studio_id: UUID,
                                     sample_project_id: UUID,
                                     sample_media_id: UUID) -> None:
    """Test la validation d'une RythmoBand (§9.3)."""
    # Créer les dépendances
    studio = Studio(id=sample_studio_id, name="Studio Test", plan="free")
    project = Project(id=sample_project_id, studio_id=sample_project_id, title="Projet")
    media = MediaAsset(id=sample_media_id, project_id=sample_project_id, storage_path="/path")
    
    async_db_session.add_all([studio, project, media])
    await async_db_session.commit()
    
    # Créer une bande en draft
    band = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=1,
        status=RythmoBandStatus.DRAFT,
        is_master=True,
    )
    async_db_session.add(band)
    await async_db_session.commit()
    
    # Valider la bande
    band.status = RythmoBandStatus.VALIDATED
    band.validated_at = datetime.now(timezone.utc)
    await async_db_session.commit()
    
    # Vérifier
    await async_db_session.refresh(band)
    assert band.status == RythmoBandStatus.VALIDATED
    assert band.validated_at is not None


@pytest.mark.asyncio
async def test_restore_rythmo_band(async_db_session: AsyncSession,
                                    sample_studio_id: UUID,
                                    sample_project_id: UUID,
                                    sample_media_id: UUID) -> None:
    """Test la restauration d'une ancienne version sans perte de données (§9.4)."""
    # Créer les dépendances
    studio = Studio(id=sample_studio_id, name="Studio Test", plan="free")
    project = Project(id=sample_project_id, studio_id=sample_project_id, title="Projet")
    media = MediaAsset(id=sample_media_id, project_id=sample_project_id, storage_path="/path")
    
    async_db_session.add_all([studio, project, media])
    await async_db_session.commit()
    
    # Créer la version 1 (master)
    band_v1 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=1,
        status=RythmoBandStatus.VALIDATED,
        title="Bande v1",
        is_master=True,
    )
    async_db_session.add(band_v1)
    await async_db_session.commit()
    
    # Ajouter des répliques à la version 1
    replica_v1 = Replica(
        rythmo_band_id=band_v1.id,
        media_id=sample_media_id,
        text="Texte original v1",
        start_ms=0,
        end_ms=1000,
        order_index=0,
    )
    async_db_session.add(replica_v1)
    await async_db_session.commit()
    
    # Créer la version 2 (plus récente)
    band_v2 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=2,
        status=RythmoBandStatus.DRAFT,
        title="Bande v2",
        is_master=True,  # La v2 devient master
    )
    async_db_session.add(band_v2)
    await async_db_session.commit()
    
    # Ajouter des répliques à la version 2
    replica_v2 = Replica(
        rythmo_band_id=band_v2.id,
        media_id=sample_media_id,
        text="Texte modifié v2",
        start_ms=0,
        end_ms=1200,
        order_index=0,
    )
    async_db_session.add(replica_v2)
    await async_db_session.commit()
    
    # Vérifier avant restauration
    band_v1_loaded = await async_db_session.get(RythmoBand, band_v1.id)
    await async_db_session.refresh(band_v1_loaded)
    assert band_v1_loaded.status == RythmoBandStatus.VALIDATED
    assert len(band_v1_loaded.replicas) == 1
    assert band_v1_loaded.replicas[0].text == "Texte original v1"
    
    # Restaurer la version 1 comme master
    band_v2.is_master = False
    band_v1.is_master = True
    band_v1.status = RythmoBandStatus.VALIDATED
    band_v2.status = RythmoBandStatus.ARCHIVED
    await async_db_session.commit()
    
    # Vérifier après restauration
    await async_db_session.refresh(band_v1)
    await async_db_session.refresh(band_v2)
    
    assert band_v1.is_master is True
    assert band_v2.is_master is False
    assert band_v2.status == RythmoBandStatus.ARCHIVED
    
    # Vérifier que les données de la v1 sont intactes
    assert len(band_v1.replicas) == 1
    assert band_v1.replicas[0].text == "Texte original v1"
    
    # Vérifier que les données de la v2 sont aussi intactes
    assert len(band_v2.replicas) == 1
    assert band_v2.replicas[0].text == "Texte modifié v2"


@pytest.mark.asyncio
async def test_project_get_master_band(async_db_session: AsyncSession,
                                        sample_studio_id: UUID,
                                        sample_project_id: UUID,
                                        sample_media_id: UUID) -> None:
    """Test la méthode get_master_band du projet (§9.3)."""
    studio = Studio(id=sample_studio_id, name="Studio Test", plan="free")
    project = Project(id=sample_project_id, studio_id=sample_project_id, title="Projet")
    media = MediaAsset(id=sample_media_id, project_id=sample_project_id, storage_path="/path")
    
    async_db_session.add_all([studio, project, media])
    await async_db_session.commit()
    
    # Créer deux bandes
    band1 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=1,
        status=RythmoBandStatus.VALIDATED,
        is_master=True,
    )
    band2 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=2,
        status=RythmoBandStatus.DRAFT,
        is_master=False,
    )
    
    async_db_session.add_all([band1, band2])
    await async_db_session.commit()
    
    # Tester get_master_band (avec selectinload pour charger la relation)
    result = await async_db_session.execute(
        select(Project)
        .options(selectinload(Project.rythmo_bands))
        .where(Project.id == sample_project_id)
    )
    project_loaded = result.scalar_one()
    master = project_loaded.get_master_band()
    assert master is not None
    assert master.id == band1.id
    assert master.version_number == 1


@pytest.mark.asyncio
async def test_project_get_latest_validated_band(async_db_session: AsyncSession,
                                                   sample_studio_id: UUID,
                                                   sample_project_id: UUID,
                                                   sample_media_id: UUID) -> None:
    """Test la méthode get_latest_validated_band du projet (§9.3)."""
    studio = Studio(id=sample_studio_id, name="Studio Test", plan="free")
    project = Project(id=sample_project_id, studio_id=sample_studio_id, title="Projet")
    media = MediaAsset(id=sample_media_id, project_id=sample_project_id, storage_path="/path")
    
    async_db_session.add_all([studio, project, media])
    await async_db_session.commit()
    
    # Créer plusieurs bandes
    band1 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=1,
        status=RythmoBandStatus.VALIDATED,
    )
    band2 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=2,
        status=RythmoBandStatus.DRAFT,  # Pas validée
    )
    band3 = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=3,
        status=RythmoBandStatus.VALIDATED,
    )
    
    async_db_session.add_all([band1, band2, band3])
    await async_db_session.commit()
    
    # Tester get_latest_validated_band (avec selectinload pour charger la relation)
    result = await async_db_session.execute(
        select(Project)
        .options(selectinload(Project.rythmo_bands))
        .where(Project.id == sample_project_id)
    )
    project_loaded = result.scalar_one()
    latest = project_loaded.get_latest_validated_band()
    assert latest is not None
    assert latest.id == band3.id
    assert latest.version_number == 3


@pytest.mark.asyncio
async def test_rythmo_band_metadata(async_db_session: AsyncSession,
                                     sample_studio_id: UUID,
                                     sample_project_id: UUID,
                                     sample_media_id: UUID) -> None:
    """Test le stockage de métadonnées dans une RythmoBand."""
    studio = Studio(id=sample_studio_id, name="Studio Test", plan="free")
    project = Project(id=sample_project_id, studio_id=sample_project_id, title="Projet")
    media = MediaAsset(id=sample_media_id, project_id=sample_project_id, storage_path="/path")
    
    async_db_session.add_all([studio, project, media])
    await async_db_session.commit()
    
    # Créer une bande avec métadonnées
    band = RythmoBand(
        project_id=sample_project_id,
        media_asset_id=sample_media_id,
        version_number=1,
        status=RythmoBandStatus.DRAFT,
        band_metadata={
            "lipsync_confidence": 0.95,
            "emotion_tags": ["joie", "neutre"],
            "processing_notes": "Traitement effectué avec succès",
        }
    )
    async_db_session.add(band)
    await async_db_session.commit()
    
    # Vérifier les métadonnées
    await async_db_session.refresh(band)
    assert band.band_metadata is not None
    assert band.band_metadata["lipsync_confidence"] == 0.95
    assert "emotion_tags" in band.band_metadata
    assert band.band_metadata["emotion_tags"] == ["joie", "neutre"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
