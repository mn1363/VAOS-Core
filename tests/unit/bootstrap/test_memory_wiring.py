"""Tests for default memory-store wiring in the application bootstrap."""

from pathlib import Path

import pytest
from src.bootstrap.wiring import build_application
from src.core.config import AppConfig
from src.pipeline.context import PipelineContext
from src.storage.filesystem.memory import FilesystemMemoryStore


@pytest.mark.asyncio
async def test_application_uses_and_closes_default_memory_store(tmp_path: Path) -> None:
    config = AppConfig(
        raw={
            "collectors": {"backend": "filesystem"},
            "storage": {
                "backend": "filesystem",
                "filesystem": {"root": str(tmp_path / "storage")},
            },
        }
    )
    pipeline = await build_application(config)
    stores = [
        resource
        for resource in pipeline.resources
        if isinstance(resource, FilesystemMemoryStore)
    ]

    assert len(stores) == 1
    await pipeline.run(PipelineContext(values={"source": str(tmp_path)}))
    assert stores[0]._closed is True
