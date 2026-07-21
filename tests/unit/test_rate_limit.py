"""Unit tests for the upload rate limiter (fake Redis; fail-open)."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.dependencies import rate_limit as rl


class FakeRequest:
    class _Client:
        host = "203.0.113.9"

    client = _Client()


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None


class BrokenRedis:
    async def incr(self, key: str) -> int:
        raise ConnectionError("redis down")


@pytest.fixture()
def limit_three(monkeypatch):
    monkeypatch.setattr(get_settings(), "UPLOAD_RATE_LIMIT_PER_MINUTE", 3)


class TestUploadRateLimit:
    async def test_allows_up_to_limit_then_blocks(self, monkeypatch, limit_three):
        fake = FakeRedis()
        monkeypatch.setattr(rl, "get_redis", lambda: fake)

        for _ in range(3):
            await rl.upload_rate_limit(FakeRequest())
        with pytest.raises(rl.RateLimitedError):
            await rl.upload_rate_limit(FakeRequest())

    async def test_fails_open_when_redis_down(self, monkeypatch, limit_three):
        monkeypatch.setattr(rl, "get_redis", lambda: BrokenRedis())
        for _ in range(10):  # far beyond the limit — never raises
            await rl.upload_rate_limit(FakeRequest())

    async def test_disabled_when_limit_zero(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "UPLOAD_RATE_LIMIT_PER_MINUTE", 0)
        monkeypatch.setattr(
            rl, "get_redis", lambda: (_ for _ in ()).throw(AssertionError)
        )
        await rl.upload_rate_limit(FakeRequest())  # redis never touched
