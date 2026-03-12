# braindump

个人表达的原材料库。通过 Telegram 统一输入文字、图片、视频、语音，自动转写音视频为文字，Web UI 浏览回顾。

## Quick Start

```bash
uv sync
cp config.example.toml ~/braindump-data/config.toml
# Edit config.toml with your Telegram credentials
uv run python -m braindump serve
```
