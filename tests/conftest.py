"""Shared fixtures."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from braindump.config import Config, WebConfig
from braindump.core import BrainDump


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def config(data_dir: Path) -> Config:
    return Config(data_dir=data_dir, web=WebConfig(host="127.0.0.1", port=0))


@pytest_asyncio.fixture
async def brain(config: Config) -> BrainDump:
    b = BrainDump(config)
    await b.connect()
    try:
        yield b
    finally:
        await b.close()
