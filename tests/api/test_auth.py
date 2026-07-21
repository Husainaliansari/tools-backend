"""E2E tests for authentication (/api/auth)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("database")


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def _register(
    client: AsyncClient, email: str, password: str = "s3cret-pw"
) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"name": "Test User", "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestRegisterLogin:
    async def test_register_returns_user_and_tokens(self, client: AsyncClient):
        email = _email()
        data = await _register(client, email)
        assert data["user"]["email"] == email
        assert data["user"]["plan"] == "free"
        assert data["tokens"]["token_type"] == "Bearer"
        assert data["tokens"]["access_token"] != data["tokens"]["refresh_token"]

    async def test_duplicate_email_conflicts(self, client: AsyncClient):
        email = _email()
        await _register(client, email)
        response = await client.post(
            "/api/auth/register",
            json={"name": "Again", "email": email, "password": "s3cret-pw"},
        )
        assert response.status_code == 409

    async def test_login_roundtrip(self, client: AsyncClient):
        email = _email()
        await _register(client, email, password="correct-horse-1")
        response = await client.post(
            "/api/auth/login", json={"email": email, "password": "correct-horse-1"}
        )
        assert response.status_code == 200
        assert response.json()["data"]["user"]["email"] == email

    async def test_wrong_password_rejected(self, client: AsyncClient):
        email = _email()
        await _register(client, email)
        response = await client.post(
            "/api/auth/login", json={"email": email, "password": "wrong-password"}
        )
        assert response.status_code == 401

    async def test_short_password_rejected(self, client: AsyncClient):
        response = await client.post(
            "/api/auth/register",
            json={"name": "X", "email": _email(), "password": "short"},
        )
        assert response.status_code == 422


class TestSessions:
    async def test_me_with_token(self, client: AsyncClient):
        email = _email()
        data = await _register(client, email)
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {data['tokens']['access_token']}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["email"] == email

    async def test_me_without_token_unauthorized(self, client: AsyncClient):
        response = await client.get("/api/auth/me")
        assert response.status_code == 401

    async def test_garbage_token_unauthorized(self, client: AsyncClient):
        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401

    async def test_refresh_issues_new_tokens(self, client: AsyncClient):
        data = await _register(client, _email())
        response = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": data["tokens"]["refresh_token"]},
        )
        assert response.status_code == 200
        assert response.json()["data"]["access_token"]

    async def test_access_token_rejected_as_refresh(self, client: AsyncClient):
        data = await _register(client, _email())
        response = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": data["tokens"]["access_token"]},
        )
        assert response.status_code == 401
