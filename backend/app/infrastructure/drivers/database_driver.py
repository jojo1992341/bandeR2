"""
Driver de Base de Données (§6.2 CDC)

Fabrique pour obtenir les sessions DB appropriées selon l'environnement.
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_async_session_factory
from app.infrastructure.ports.database import DatabasePort


class DatabaseDriver(DatabasePort):
    """
    Driver de base de données utilisant SQLAlchemy async.
    
    Implémente DatabasePort.
    """
    
    def __init__(self, for_test: bool = False):
        """
        Initialise le driver DB.
        
        Args:
            for_test: Si True, utilise la session de test.
        """
        self._for_test = for_test
        self._session_factory = None
    
    @property
    def session_factory(self) -> async_sessionmaker:
        """Retourne la fabrique de sessions."""
        if self._session_factory is None:
            self._session_factory = get_async_session_factory(for_test=self._for_test)
        return self._session_factory
    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager pour obtenir une session DB."""
        async with self.session_factory() as session:
            yield session
    
    async def execute(self, statement: Any) -> Any:
        """Exécute une statement SQL."""
        async with self.session_factory() as session:
            result = await session.execute(statement)
            await session.commit()
            return result
    
    async def get_one(self, statement: Any) -> Optional[Any]:
        """Récupère une seule ligne."""
        async with self.session_factory() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()
    
    async def get_all(self, statement: Any) -> list[Any]:
        """Récupère toutes les lignes."""
        async with self.session_factory() as session:
            result = await session.execute(statement)
            return list(result.scalars().all())
    
    async def add(self, entity: Any) -> Any:
        """Ajoute une entité."""
        async with self.session_factory() as session:
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return entity
    
    async def add_all(self, entities: list[Any]) -> list[Any]:
        """Ajoute plusieurs entités."""
        async with self.session_factory() as session:
            session.add_all(entities)
            await session.commit()
            for entity in entities:
                await session.refresh(entity)
            return entities
    
    async def commit(self) -> None:
        """Commite la transaction."""
        async with self.session_factory() as session:
            await session.commit()
    
    async def rollback(self) -> None:
        """Annule la transaction."""
        async with self.session_factory() as session:
            await session.rollback()
    
    async def refresh(self, entity: Any) -> None:
        """Rafraîchit une entité."""
        async with self.session_factory() as session:
            await session.refresh(entity)
    
    async def delete(self, entity: Any) -> None:
        """Supprime une entité."""
        async with self.session_factory() as session:
            await session.delete(entity)
            await session.commit()
    
    async def health_check(self) -> dict:
        """Vérifie la santé de la connexion DB."""
        try:
            async with self.session_factory() as session:
                result = await session.execute("SELECT 1")
                await result.fetchone()
            return {
                "status": "healthy",
                "database": "postgresql" if not self._for_test else "sqlite",
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


def get_database_driver(for_test: bool = False) -> DatabaseDriver:
    """
    Retourne le driver de base de données.
    
    Args:
        for_test: Si True, utilise la session de test.
        
    Returns:
        DatabaseDriver configuré.
    """
    return DatabaseDriver(for_test=for_test)


def get_production_database() -> DatabaseDriver:
    """Retourne le driver DB pour la production."""
    return DatabaseDriver(for_test=False)


def get_test_database() -> DatabaseDriver:
    """Retourne le driver DB pour les tests."""
    return DatabaseDriver(for_test=True)
