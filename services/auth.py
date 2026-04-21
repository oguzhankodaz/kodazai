from __future__ import annotations

import hashlib
import hmac
import os
from typing import TypedDict

from sqlalchemy import select

from database import SessionLocal
from db.models import AppUser

ROLE_ADMIN = "admin"
ROLE_USER = "user"
PBKDF2_NAME = "pbkdf2_sha256"


class AuthUser(TypedDict):
    id: int
    username: str
    role: str


def hash_password(password: str, *, iterations: int = 600_000) -> str:
    """Parola hash üretir: pbkdf2_sha256$iter$salt_hex$digest_hex"""
    if not password:
        raise ValueError("Parola boş olamaz.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return f"{PBKDF2_NAME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False

    # Geriye dönük/manuel kullanım için: "plain$sifre"
    if stored_hash.startswith("plain$"):
        return hmac.compare_digest(stored_hash[6:], password)

    parts = stored_hash.split("$")
    if len(parts) == 4 and parts[0] == PBKDF2_NAME:
        _, it_raw, salt_hex, digest_hex = parts
        try:
            iterations = int(it_raw)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
        except ValueError:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)

    # Eğer hash formatı verilmediyse düz metin karşılaştır.
    return hmac.compare_digest(stored_hash, password)


def get_active_user(username: str) -> AuthUser | None:
    with SessionLocal() as session:
        stmt = select(AppUser).where(AppUser.username == username.strip())
        row = session.execute(stmt).scalars().first()
        if not row or not row.is_active:
            return None
        role = (row.role or "").strip().lower()
        if role not in {ROLE_ADMIN, ROLE_USER}:
            return None
        return {"id": int(row.id), "username": row.username, "role": role}


def authenticate_user(username: str, password: str) -> AuthUser | None:
    with SessionLocal() as session:
        stmt = select(AppUser).where(AppUser.username == username.strip())
        row = session.execute(stmt).scalars().first()
        if not row or not row.is_active:
            return None
        if not verify_password(password, row.password_hash):
            return None
        role = (row.role or "").strip().lower()
        if role not in {ROLE_ADMIN, ROLE_USER}:
            return None
        return {"id": int(row.id), "username": row.username, "role": role}
