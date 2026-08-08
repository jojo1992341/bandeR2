import hashlib


def verify_password(plain: str, hashed: str) -> bool:
    # Stub : remplacement par hash sécurisé (bcrypt via passlib en production)
    return hashlib.sha256(plain.encode()).hexdigest() == hashed


def get_password_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()
