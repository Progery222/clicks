import secrets

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def random_slug(length: int = 7) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
