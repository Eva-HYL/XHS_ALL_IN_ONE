from backend.app.core.security import decrypt_text, encrypt_text


def encrypt_secret(secret: str) -> str:
    if not secret:
        raise ValueError("app_secret is required")
    return encrypt_text(secret)


def decrypt_secret(value: str) -> str:
    return decrypt_text(value)
