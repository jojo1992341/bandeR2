"""
Port de Base de Données (§6.2 CDC)

Interface stable pour l'accès à la base de données. Les adaptateurs
(PostgreSQL asyncpg, SQLite, mémoire pour tests) doivent implémenter
cette interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession


class DatabasePort(ABC):
    """
    Interface pour l'accès à la base de données.
    
    Définit les opérations de base pour les sessions DB.
    """
    
    @abstractmethod
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Context manager pour obtenir une session DB.
        
        Yields:
            AsyncSession SQLAlchemy.
        """
        ...
    
    @abstractmethod
    async def execute(self, statement: Any) -> Any:
        """
        Exécute une statement SQL.
        
        Args:
            statement: Statement SQLAlchemy.
            
        Returns:
            Résultat de l'exécution.
        """
        ...
    
    @abstractmethod
    async def get_one(self, statement: Any) -> Optional[Any]:
        """
        Récupère une seule ligne.
        
        Args:
            statement: Statement SQLAlchemy.
            
        Returns:
            Première ligne ou None.
        """
        ...
    
    @abstractmethod
    async def get_all(self, statement: Any) -> list[Any]:
        """
        Récupère toutes les lignes.
        
        Args:
            statement: Statement SQLAlchemy.
            
        Returns:
            Liste des lignes.
        """
        ...
    
    @abstractmethod
    async def add(self, entity: Any) -> Any:
        """
        Ajoute une entité.
        
        Args:
            entity: Entité à ajouter.
            
        Returns:
            Entité avec ID généré.
        """
        ...
    
    @abstractmethod
    async def add_all(self, entities: list[Any]) -> list[Any]:
        """
        Ajoute plusieurs entités.
        
        Args:
            entities: Liste d'entités.
            
        Returns:
            Liste des entités avec IDs générés.
        """
        ...
    
    @abstractmethod
    async def commit(self) -> None:
        """Commite la transaction en cours."""
        ...
    
    @abstractmethod
    async def rollback(self) -> None:
        """Annule la transaction en cours."""
        ...
    
    @abstractmethod
    async def refresh(self, entity: Any) -> None:
        """
        Rafraîchit une entité depuis la base.
        
        Args:
            entity: Entité à rafraîchir.
        """
        ...
    
    @abstractmethod
    async def delete(self, entity: Any) -> None:
        """
        Supprime une entité.
        
        Args:
            entity: Entité à supprimer.
        """
        ...
    
    @abstractmethod
    async def health_check(self) -> dict:
        """
        Vérifie la santé de la connexion DB.
        
        Returns:
            Dictionnaire avec le statut.
        """
        ...
