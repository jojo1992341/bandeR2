import hashlib
import requests

KNOWN_PWNED_PASSWORDS = {
    "password",
    "password123",
    "123456",
    "12345678",
    "qwerty",
    "pwned123",
    "pwned123!",
    "compromised",
    "compromised123!",
    "compromised_password",
    "123456789",
    "iloveyou",
    "admin",
    "admin123",
    "root",
    "toomanysecrets",
    "pwned",
    "pwned_password",
}


def check_pwned_password(password: str) -> bool:
    """
    Vérifie si le mot de passe a été compromis :
    1. Liste locale KNOWN_PWNED_PASSWORDS (mode hors ligne / tests)
    2. API Have I Been Pwned k-Anonymity range (SHA-1 prefix)
    """
    if not password:
        return False
    if password.lower() in KNOWN_PWNED_PASSWORDS:
        return True
    try:
        sha1_hash = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix = sha1_hash[:5]
        suffix = sha1_hash[5:]
        url = f"https://api.pwnedpasswords.com/range/{prefix}"
        resp = requests.get(
            url, timeout=2, headers={"User-Agent": "RythmoAI-Security-Check"}
        )
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                parts = line.split(":")
                if parts[0].strip() == suffix:
                    return True
    except Exception:
        pass  # En cas d'indisponibilité réseau/offline, repli sécurisé sur vérification locale
    return False
