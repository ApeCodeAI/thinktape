"""Configuration loading from config.toml."""

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_logger = logging.getLogger("braindump.config")

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class GeneralConfig:
    data_dir: Path = field(default_factory=lambda: Path.home() / "braindump-data")
    timezone: str = "Asia/Shanghai"
    day_boundary_hour: int = 4


@dataclass
class TelegramConfig:
    api_id: int = 0
    api_hash: str = ""
    bot_token: str = ""
    allowed_users: list[int] = field(default_factory=list)


@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    secret_key: str = ""


@dataclass
class TranscribeConfig:
    engine: str = "funasr"
    funasr_model: str = "paraformer-zh"
    whisper_model: str = "medium"
    whisper_device: str = "cpu"
    api_provider: str = "siliconflow"
    api_key: str = ""


@dataclass
class LLMConfig:
    enabled: bool = False
    base_url: str = "https://api.moonshot.cn/v1"
    model: str = "kimi-k2.5"
    api_key_env: str = "MOONSHOT_API_KEY"
    timeout: int = 30
    min_content_length: int = 30


@dataclass
class ReviewConfig:
    enabled: bool = False
    count: int = 3
    schedule: str = "09:00"
    min_age_days: int = 7
    min_content_length: int = 20
    chat_id: int = 0


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    web: WebConfig = field(default_factory=WebConfig)
    transcribe: TranscribeConfig = field(default_factory=TranscribeConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)

    @property
    def data_dir(self) -> Path:
        return self.general.data_dir

    @property
    def db_path(self) -> Path:
        return self.data_dir / "braindump.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / "trash"

    @property
    def import_dir(self) -> Path:
        return self.data_dir / "import"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backup"

    def get_llm_api_key(self) -> str:
        """Read LLM API key from the environment variable specified in config."""
        return os.environ.get(self.llm.api_key_env, "")

    def ensure_dirs(self):
        """Create all required directories."""
        for d in [
            self.data_dir,
            self.media_dir / "video",
            self.media_dir / "audio",
            self.media_dir / "image",
            self.media_dir / "text",
            self.transcripts_dir,
            self.trash_dir,
            self.import_dir,
            self.backup_dir,
            self.data_dir / "migrations",
        ]:
            d.mkdir(parents=True, exist_ok=True)


def _apply_dict(obj, data: dict):
    for key, val in data.items():
        if hasattr(obj, key):
            current = getattr(obj, key)
            if isinstance(current, Path):
                setattr(obj, key, Path(os.path.expanduser(str(val))))
            elif isinstance(current, list):
                setattr(obj, key, list(val))
            else:
                setattr(obj, key, type(current)(val) if not isinstance(val, type(current)) else val)


def load_config(config_path: Path | None = None) -> Config:
    """Load config from TOML file. Falls back to defaults if file doesn't exist."""
    cfg = Config()

    if config_path is None:
        # Check env var, then default location
        env_dir = os.environ.get("BRAINDUMP_DATA_DIR")
        if env_dir:
            cfg.general.data_dir = Path(os.path.expanduser(env_dir))
        config_path = cfg.data_dir / "config.toml"

    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        if "general" in data:
            _apply_dict(cfg.general, data["general"])
        if "telegram" in data:
            _apply_dict(cfg.telegram, data["telegram"])
        if "web" in data:
            _apply_dict(cfg.web, data["web"])
        if "transcribe" in data:
            _apply_dict(cfg.transcribe, data["transcribe"])
        if "llm" in data:
            _apply_dict(cfg.llm, data["llm"])
        if "review" in data:
            _apply_dict(cfg.review, data["review"])

    return cfg


# Global config singleton
_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
        _config.ensure_dirs()
    return _config


def validate_llm_config(cfg: Config) -> None:
    """Check LLM config at startup. If enabled but no API key, warn and disable."""
    if not cfg.llm.enabled:
        return
    api_key = cfg.get_llm_api_key()
    if not api_key:
        _logger.warning(
            "LLM enabled but %s is empty — auto-disabling LLM summarization",
            cfg.llm.api_key_env,
        )
        cfg.llm.enabled = False


def get_timezone() -> ZoneInfo:
    """Return the timezone configured in config.toml (general.timezone)."""
    return ZoneInfo(get_config().general.timezone)
