"""Capacity tests reuse the integration database fixtures."""

from tests.integration.conftest import admin_url, database_url, engine, template_url

__all__ = ["admin_url", "database_url", "engine", "template_url"]
