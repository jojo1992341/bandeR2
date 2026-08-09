"""
Port de Cache (§10.1, §6.2 CDC)

Interface stable pour le cache distribué (Redis). Les adaptateurs doivent
implémenter cette interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class CachePort(ABC):
    """
    Interface pour le cache distribué.
    
    Permet:
    - Get/set/delete de valeurs
    - Expiration automatique (TTL)
    - Opérations atomiques
    """
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """
        Récupère une valeur du cache.
        
        Args:
            key: Clé du cache.
            
        Returns:
            Valeur décodée ou None si absente/expirée.
        """
        ...
    
    @abstractmethod
    def set(
        self,
        key: str,
        value: Any,
        expire_seconds: Optional[int] = None
    ) -> bool:
        """
        Stocke une valeur dans le cache.
        
        Args:
            key: Clé du cache.
            value: Valeur à stocker (sera sérialisée en JSON).
            expire_seconds: TTL en secondes (optionnel).
            
        Returns:
            True si l'opération a réussi.
        """
        ...
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Supprime une clé du cache.
        
        Args:
            key: Clé à supprimer.
            
        Returns:
            True si la clé existait et a été supprimée.
        """
        ...
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Vérifie si une clé existe dans le cache.
        
        Args:
            key: Clé à vérifier.
            
        Returns:
            True si la clé existe et n'est pas expirée.
        """
        ...
    
    @abstractmethod
    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """
        Incrémente une valeur entière atomically.
        
        Args:
            key: Clé du compteur.
            amount: Valeur à ajouter (défaut: 1).
            
        Returns:
            Nouvelle valeur ou None si la clé n'existe pas.
        """
        ...
    
    @abstractmethod
    def decr(self, key: str, amount: int = 1) -> Optional[int]:
        """
        Décrémente une valeur entière atomically.
        
        Args:
            key: Clé du compteur.
            amount: Valeur à soustraire (défaut: 1).
            
        Returns:
            Nouvelle valeur ou None si la clé n'existe pas.
        """
        ...
    
    @abstractmethod
    def expire(self, key: str, seconds: int) -> bool:
        """
        Définit un TTL sur une clé existante.
        
        Args:
            key: Clé du cache.
            seconds: Nouveau TTL en secondes.
            
        Returns:
            True si l'opération a réussi.
        """
        ...
    
    @abstractmethod
    def ttl(self, key: str) -> Optional[int]:
        """
        Récupère le TTL restant d'une clé.
        
        Args:
            key: Clé du cache.
            
        Returns:
            TTL restant en secondes, -1 si sans expiration, None si clé absente.
        """
        ...
    
    @abstractmethod
    def delete_pattern(self, pattern: str) -> int:
        """
        Supprime toutes les clés correspondant à un pattern.
        
        Args:
            pattern: Pattern glob-style (ex: "session:*").
            
        Returns:
            Nombre de clés supprimées.
        """
        ...
    
    @abstractmethod
    def health_check(self) -> dict:
        """
        Vérifie la santé de la connexion cache.
        
        Returns:
            Dictionnaire avec le statut.
        """
        ...
