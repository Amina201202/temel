"""Muellim girisi: sifre hash-i, tokenler (Redis-de), giris cehdlerinin limiti."""
import hashlib
import os
import secrets
import time

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import Teacher

TOKEN_TTL = 7 * 24 * 3600   # 7 gun
MAX_FAILS = 5               # 5 sehv sifreden sonra 15 deqiqe blok
FAIL_WINDOW = 15 * 60


class MemoryStore:
    """Redis olmayanda (testlerde) sade evezedici."""

    def __init__(self):
        self.data = {}

    def _alive(self, key):
        item = self.data.get(key)
        if item and item[1] and item[1] < time.time():
            self.data.pop(key, None)
            return None
        return item

    def get(self, key):
        item = self._alive(key)
        return item[0] if item else None

    def setex(self, key, ttl, value):
        self.data[key] = (str(value), time.time() + ttl)

    def delete(self, key):
        self.data.pop(key, None)

    def incr(self, key):
        item = self._alive(key)
        value = int(item[0]) + 1 if item else 1
        self.data[key] = (str(value), item[1] if item else None)
        return value

    def expire(self, key, ttl):
        if key in self.data:
            self.data[key] = (self.data[key][0], time.time() + ttl)


_store = None


def store():
    global _store
    if _store is None:
        url = os.getenv("REDIS_URL")
        if url:
            import redis
            _store = redis.Redis.from_url(url, decode_responses=True)
        else:
            _store = MemoryStore()
    return _store


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return secrets.compare_digest(digest.hex(), digest_hex)


def generate_password() -> str:
    # oxunasi olsun deye qarisiq herfleri cixardiriq (0/O, 1/l)
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def issue_token(teacher_id: int) -> str:
    token = secrets.token_urlsafe(32)
    store().setex(f"teacher_token:{token}", TOKEN_TTL, teacher_id)
    return token


def revoke_token(token: str):
    store().delete(f"teacher_token:{token}")


def login_blocked(username: str) -> bool:
    value = store().get(f"login_fail:{username.lower()}")
    return value is not None and int(value) >= MAX_FAILS


def register_fail(username: str):
    key = f"login_fail:{username.lower()}"
    if store().incr(key) == 1:
        store().expire(key, FAIL_WINDOW)


def clear_fails(username: str):
    store().delete(f"login_fail:{username.lower()}")


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Giriş lazımdır")
    return authorization.removeprefix("Bearer ").strip()


def current_teacher(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> Teacher:
    token = bearer(authorization)
    teacher_id = store().get(f"teacher_token:{token}")
    teacher = db.get(Teacher, int(teacher_id)) if teacher_id else None
    if teacher is None:
        raise HTTPException(401, "Giriş vaxtı bitib, yenidən daxil ol")
    return teacher


def require_admin(x_admin_key: str | None = Header(None)):
    expected = os.getenv("ADMIN_PASSWORD")
    if not expected:
        raise HTTPException(503, "ADMIN_PASSWORD .env-də təyin olunmayıb")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(403, "Admin açarı səhvdir")
