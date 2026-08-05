"""Application settings and configuration data structures.

All settings are represented as immutable, frozen dataclasses so that
configuration cannot be mutated after the application has been
bootstrapped. Values are plain Python types to keep this module free of
third-party dependencies.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Connection settings for the primary relational data store.

    Attributes:
        dsn: Data source name / connection string for the database.
        pool_size: Maximum number of pooled connections.
    """

    dsn: str = "sqlite+aiosqlite:///./vaos.db"
    pool_size: int = 5


@dataclass(frozen=True, slots=True)
class VectorStoreSettings:
    """Connection settings for the vector storage backend.

    Attributes:
        provider: Identifier of the vector store implementation to use.
        dimensions: Dimensionality of stored embedding vectors.
        endpoint: Network endpoint of the vector store, if remote.
    """

    provider: str = "none"
    dimensions: int = 768
    endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class GraphStoreSettings:
    """Connection settings for the graph storage backend.

    Attributes:
        provider: Identifier of the graph store implementation to use.
        endpoint: Network endpoint of the graph store, if remote.
    """

    provider: str = "none"
    endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class MemorySettings:
    """Configuration for the AI memory subsystem.

    Attributes:
        provider: Identifier of the memory store implementation to use.
        ttl_seconds: Default time-to-live applied to memory entries.
    """

    provider: str = "none"
    ttl_seconds: int = 3600


@dataclass(frozen=True, slots=True)
class APISettings:
    """Configuration for the HTTP API server.

    Attributes:
        host: Network interface the API server binds to.
        port: TCP port the API server listens on.
        title: Human-readable title exposed in the API schema.
    """

    host: str = "0.0.0.0"
    port: int = 8000
    title: str = "VAOS API"


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    """Configuration for the application logging subsystem.

    Attributes:
        level: Minimum log level that will be emitted.
        json_format: Whether log records are emitted as JSON.
    """

    level: str = "INFO"
    json_format: bool = False


@dataclass(frozen=True, slots=True)
class Settings:
    """Root application settings aggregating every subsystem's configuration.

    Attributes:
        environment: Deployment environment name (e.g. development, production).
        debug: Whether the application is running in debug mode.
        database: Relational database configuration.
        vector_store: Vector store configuration.
        graph_store: Graph store configuration.
        memory: AI memory subsystem configuration.
        api: HTTP API server configuration.
        logging: Logging subsystem configuration.
    """

    environment: str = "development"
    debug: bool = False
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    vector_store: VectorStoreSettings = field(default_factory=VectorStoreSettings)
    graph_store: GraphStoreSettings = field(default_factory=GraphStoreSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    api: APISettings = field(default_factory=APISettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
