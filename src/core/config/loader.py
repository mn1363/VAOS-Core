"""Loading of application settings from environment variables."""

import os
from collections.abc import Mapping

from core.config.settings import (
    APISettings,
    DatabaseSettings,
    GraphStoreSettings,
    LoggingSettings,
    MemorySettings,
    Settings,
    VectorStoreSettings,
)


def _parse_bool(value: str) -> bool:
    """Parse a string environment variable value into a boolean.

    Args:
        value: Raw string value, typically sourced from the environment.

    Returns:
        True if the value represents an affirmative flag, False otherwise.
    """
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build a `Settings` instance from environment variables.

    Any variable that is not present falls back to the default defined on
    the corresponding settings dataclass.

    Args:
        env: Optional mapping to read variables from. Defaults to `os.environ`.

    Returns:
        A fully populated, immutable `Settings` instance.
    """
    source = env if env is not None else os.environ

    defaults_db = DatabaseSettings()
    defaults_vector = VectorStoreSettings()
    defaults_graph = GraphStoreSettings()
    defaults_memory = MemorySettings()
    defaults_api = APISettings()
    defaults_logging = LoggingSettings()

    return Settings(
        environment=source.get("VAOS_ENVIRONMENT", "development"),
        debug=_parse_bool(source.get("VAOS_DEBUG", "false")),
        database=DatabaseSettings(
            dsn=source.get("VAOS_DATABASE_DSN", defaults_db.dsn),
            pool_size=int(source.get("VAOS_DATABASE_POOL_SIZE", str(defaults_db.pool_size))),
        ),
        vector_store=VectorStoreSettings(
            provider=source.get("VAOS_VECTOR_PROVIDER", defaults_vector.provider),
            dimensions=int(source.get("VAOS_VECTOR_DIMENSIONS", str(defaults_vector.dimensions))),
            endpoint=source.get("VAOS_VECTOR_ENDPOINT", defaults_vector.endpoint),
        ),
        graph_store=GraphStoreSettings(
            provider=source.get("VAOS_GRAPH_PROVIDER", defaults_graph.provider),
            endpoint=source.get("VAOS_GRAPH_ENDPOINT", defaults_graph.endpoint),
        ),
        memory=MemorySettings(
            provider=source.get("VAOS_MEMORY_PROVIDER", defaults_memory.provider),
            ttl_seconds=int(source.get("VAOS_MEMORY_TTL_SECONDS", str(defaults_memory.ttl_seconds))),
        ),
        api=APISettings(
            host=source.get("VAOS_API_HOST", defaults_api.host),
            port=int(source.get("VAOS_API_PORT", str(defaults_api.port))),
            title=source.get("VAOS_API_TITLE", defaults_api.title),
        ),
        logging=LoggingSettings(
            level=source.get("VAOS_LOG_LEVEL", defaults_logging.level),
            json_format=_parse_bool(source.get("VAOS_LOG_JSON", "false")),
        ),
    )
