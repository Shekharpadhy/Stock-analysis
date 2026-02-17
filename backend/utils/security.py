import secrets, hashlib, hmac

def generate_secret(n: int = 32) -> str:
    return secrets.token_hex(n)

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())

def mask_secret(secret: str, visible: int = 4) -> str:
    return secret[:visible] + "*" * (len(secret) - visible)
