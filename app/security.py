import hashlib
import hmac

_SALT = b"bio-links-admin-v1"


def verify_env_password(attempt: str, expected: str) -> bool:
    def derive(s: str) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", s.encode("utf-8"), _SALT, 150_000)

    return hmac.compare_digest(derive(attempt), derive(expected))
