"""Shared fixtures."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from thinktape.config import Config, WebConfig
from thinktape.core import ThinkTape


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def config(data_dir: Path) -> Config:
    return Config(data_dir=data_dir, web=WebConfig(host="127.0.0.1", port=0))


@pytest_asyncio.fixture
async def brain(config: Config) -> ThinkTape:
    b = ThinkTape(config)
    await b.connect()
    try:
        yield b
    finally:
        await b.close()
