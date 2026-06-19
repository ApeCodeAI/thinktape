"""AI summarization + auto-tagging using an OpenAI-compatible LLM.

Calls a chat-completions endpoint (Moonshot Kimi by default) to generate
a one-line Chinese summary plus 1-3 suggested tags for an item.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

from .config import LLMConfig
from .core import BrainDump

log = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "你是一个个人 dump 库的 AI 助理。"
    "用户随手记录想法、收藏链接、笔记，你为每条记录生成：\n"
    "1. summary: 一句话中文摘要（不超过 40 字，直接陈述要点，不要『总结』『摘要』等套话）。\n"
    "2. tags: 1-3 个简洁中文/英文标签（单词或短语，无 #），用于以后检索。\n"
    "只返回严格的 JSON：{\"summary\": \"...\", \"tags\": [\"...\", \"...\"]}，"
    "不要 markdown 代码块，不要解释。"
)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of model output, tolerating code fences."""
    text = text.strip()
    # Strip ```json ... ``` fences if present
    fence = re.match(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    # Find the first {...} block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON found in model output: {text[:200]!r}")
    return json.loads(text[start:end + 1])


class Summarizer:
    """Single-call LLM helper for summary + tags."""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def _api_key(self) -> str:
        key = os.environ.get(self.cfg.api_key_env)
        if not key:
            raise RuntimeError(
                f"LLM API key missing: env {self.cfg.api_key_env} not set"
            )
        return key

    async def summarize_and_tag(self, content: str) -> dict[str, Any]:
        content = (content or "").strip()
        if not content:
            return {"summary": None, "tags": []}
        if len(content) < self.cfg.min_content_length:
            return {"summary": None, "tags": []}

        api_key = self._api_key()
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content[:4000]},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=self.cfg.timeout) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"LLM HTTP {r.status_code}: {r.text[:300]}"
                )
            data = r.json()

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"unexpected LLM response: {data}") from e

        try:
            parsed = _extract_json(text)
        except Exception as e:
            raise RuntimeError(f"failed to parse LLM JSON: {e}: {text!r}") from e

        summary = parsed.get("summary")
        if isinstance(summary, str):
            summary = summary.strip() or None
        else:
            summary = None
        tags_raw = parsed.get("tags") or []
        tags: list[str] = []
        if isinstance(tags_raw, list):
            for t in tags_raw:
                if not isinstance(t, str):
                    continue
                t = t.strip().lstrip("#").strip()
                if t and t not in tags:
                    tags.append(t)
                if len(tags) >= 3:
                    break
        return {"summary": summary, "tags": tags}


class SummaryWorker:
    """Background worker that summarizes items without a summary."""

    def __init__(self, brain: BrainDump, cfg: LLMConfig):
        self.brain = brain
        self.cfg = cfg
        self.summarizer = Summarizer(cfg)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def enqueue(self, item_id: str) -> None:
        self.queue.put_nowait(item_id)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="summary-worker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        log.info("summary worker started (model=%s)", self.cfg.model)
        while True:
            try:
                item_id = await self.queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._process(item_id)
            except Exception:
                log.exception("summary failed for %s", item_id)

    async def _process(self, item_id: str) -> None:
        item = await self.brain.get(item_id)
        if item is None:
            return
        # Don't re-summarize if it's still being transcribed.
        if item.content.startswith("[转写"):
            return
        if item.summary and item.summary.strip():
            return
        if len(item.content.strip()) < self.cfg.min_content_length:
            return
        try:
            result = await self.summarizer.summarize_and_tag(item.content)
        except Exception as e:
            log.warning("summarize failed for %s: %s", item_id, e)
            return
        if not result.get("summary") and not result.get("tags"):
            return
        # Merge tags rather than overwrite — user-supplied tags win.
        merged = list(dict.fromkeys(item.tags + result.get("tags", [])))
        await self.brain.update(
            item_id,
            summary=result.get("summary"),
            tags=merged,
        )
        log.info("summarized %s: %s", item_id, result.get("summary"))

    async def backfill_pending(self) -> int:
        """Queue all active items without a summary."""
        n = 0
        items = await self.brain.list(status="active", limit=1000)
        for item in items:
            if item.summary and item.summary.strip():
                continue
            if not item.content.strip():
                continue
            if item.content.startswith("[转写"):
                continue
            if len(item.content.strip()) < self.cfg.min_content_length:
                continue
            self.enqueue(item.id)
            n += 1
        return n
