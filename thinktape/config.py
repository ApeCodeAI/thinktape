"""Config loading."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TelegramConfig:
    api_id: int
    api_hash: str
    bot_token: str
    allowed_users: list[int]


@dataclass
class TranscribeConfig:
    engine: str = "whisper"
    whisper_model: str = "small"
    whisper_device: str = "cpu"


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class LLMConfig:
    enabled: bool = False
    base_url: str = "https://api.moonshot.cn/v1"
    model: str = "kimi-k2.5"
    api_key_env: str = "MOONSHOT_API_KEY"
    timeout: int = 30
    min_content_length: int = 30


@dataclass
class Config:
    data_dir: Path
    timezone: str = "Asia/Shanghai"
    telegram: TelegramConfig | None = None
    transcribe: TranscribeConfig = field(default_factory=TranscribeConfig)
    web: WebConfig = field(default_factory=WebConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @property
    def items_dir(self) -> Path:
        return self.data_dir / "items"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "thinktape.db"

    @property
    def bot_session_path(self) -> Path:
        # Pyrofork wants a session name (no extension); using existing session file name.
        return self.data_dir / "thinktape_bot"


def _resolve_data_dir() -> Path:
    env = os.environ.get("THINKTAPE_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path("~/thinktape-data").expanduser().resolve()


def load_config(data_dir: Path | None = None) -> Config:
    """Load configuration from <data_dir>/config.toml."""
    data_dir = data_dir or _resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    config_path = data_dir / "config.toml"
    if not config_path.exists():
        # Allow running without config for tests / dry runs.
        return Config(data_dir=data_dir)

    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    general = raw.get("general", {})
    # config.toml may specify data_dir, but the file's location wins.
    tz = general.get("timezone", "Asia/Shanghai")

    tg_raw = raw.get("telegram")
    telegram = None
    if tg_raw and tg_raw.get("api_id") and tg_raw.get("api_hash") and tg_raw.get("bot_token"):
        telegram = TelegramConfig(
            api_id=int(tg_raw["api_id"]),
            api_hash=str(tg_raw["api_hash"]),
            bot_token=str(tg_raw["bot_token"]),
            allowed_users=[int(x) for x in tg_raw.get("allowed_users", [])],
        )

    transcribe = TranscribeConfig(**{k: v for k, v in raw.get("transcribe", {}).items()
                                     if k in {"engine", "whisper_model", "whisper_device"}})
    web = WebConfig(**{k: v for k, v in raw.get("web", {}).items() if k in {"host", "port"}})
    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        enabled=bool(llm_raw.get("enabled", False)),
        base_url=str(llm_raw.get("base_url", "https://api.moonshot.cn/v1")),
        model=str(llm_raw.get("model", "kimi-k2.5")),
        api_key_env=str(llm_raw.get("api_key_env", "MOONSHOT_API_KEY")),
        timeout=int(llm_raw.get("timeout", 30)),
        min_content_length=int(llm_raw.get("min_content_length", 30)),
    )

    return Config(
        data_dir=data_dir,
        timezone=tz,
        telegram=telegram,
        transcribe=transcribe,
        web=web,
        llm=llm,
    )
