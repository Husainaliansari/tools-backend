"""API consistency guards.

These tests pin the platform-wide contracts so a future tool cannot drift:
every tool endpoint has the same shape, every slug matches the ToolSlug
registry, and every task/service pair agrees on its Celery task name.
"""

from __future__ import annotations

import pytest

from app.constants import ToolSlug
from app.services.tool_base import BaseToolService


def _all_tool_services() -> list[type[BaseToolService]]:
    import app.services.tools as tools_pkg

    return [
        obj
        for name in tools_pkg.__all__
        if isinstance(obj := getattr(tools_pkg, name), type)
        and issubclass(obj, BaseToolService)
    ]


class TestToolRegistry:
    def test_every_service_slug_is_a_registered_tool_slug(self):
        slugs = {service.slug for service in _all_tool_services()}
        assert all(isinstance(slug, ToolSlug) for slug in slugs)

    def test_task_names_follow_convention_and_are_registered(self):
        from app.workers.celery_app import celery_app

        for service in _all_tool_services():
            assert service.task_name == f"tools.{service.slug.value}", service
            assert (
                service.task_name in celery_app.tasks
            ), f"Celery task missing for {service.task_name}"

    def test_input_constraints_are_sane(self):
        for service in _all_tool_services():
            assert 1 <= service.min_input_files <= service.max_input_files
            assert service.allowed_input_extensions, service


@pytest.mark.usefixtures("database")
class TestOpenApiUniformity:
    async def test_every_tool_endpoint_has_identical_shape(self, client):
        spec = (await client.get("/openapi.json")).json()
        tool_paths = {
            path: item
            for path, item in spec["paths"].items()
            if path.startswith("/api/v1/tools/")
        }
        service_slugs = {s.slug.value for s in _all_tool_services()}
        endpoint_slugs = {p.rsplit("/", 1)[-1] for p in tool_paths}
        assert endpoint_slugs == service_slugs

        for path, item in tool_paths.items():
            assert set(item.keys()) == {"post"}, f"{path} must be POST-only"
            post = item["post"]
            assert "202" in post["responses"], f"{path} must return 202"
            body_schema = post["requestBody"]["content"]["application/json"]["schema"][
                "$ref"
            ]
            assert body_schema.endswith("JobCreateRequest"), path
