"""Daily / weekly review and random recall.

This module is intentionally framework-free: ReviewEngine returns plain dicts.
The CLI prints them; the bot/serve loop may schedule them for Telegram push.
"""
from __future__ import annotations

import asyncio
import logging
import random as _random
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable

from .config import Config
from .core import ThinkTape
from .models import Item

log = logging.getLogger(__name__)

_TZ_CST = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(_TZ_CST)


def _item_to_dict(item: Item) -> dict[str, Any]:
    d = item.model_dump(mode="json")
    d["images"] = list(item.images or [])
    return d


class ReviewEngine:
    """Computes today / weekly / random review snapshots from an active ThinkTape."""

    def __init__(self, brain: ThinkTape, config: Config | None = None):
        self.brain = brain
        self.config = config

    # ---------- daily ----------

    async def daily_digest(self, *, day: datetime | None = None, use_llm: bool = False) -> dict[str, Any]:
        day = day or _now()
        start = day.astimezone(_TZ_CST).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        items = await self._items_in_range(start, end)
        active_concepts = self._concept_counts(items)
        out: dict[str, Any] = {
            "date": start.strftime("%Y-%m-%d"),
            "range": [start.isoformat(), end.isoformat()],
            "count": len(items),
            "by_type": self._type_counts(items),
            "active_concepts": active_concepts,
            "items": [_item_to_dict(i) for i in items],
        }
        if use_llm and items:
            out["theme"] = await self._llm_theme(items, span="今天")
        return out

    # ---------- weekly ----------

    async def weekly_digest(self, *, end_day: datetime | None = None, use_llm: bool = False) -> dict[str, Any]:
        end_day = end_day or _now()
        end = end_day.astimezone(_TZ_CST).replace(hour=23, minute=59, second=59, microsecond=0)
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        items = await self._items_in_range(start, end)
        top = self._concept_counts(items)
        out: dict[str, Any] = {
            "range": [start.isoformat(), end.isoformat()],
            "count": len(items),
            "by_type": self._type_counts(items),
            "top_concepts": top,
            "items_per_day": self._items_per_day(items, start, end),
        }
        if use_llm and items:
            out["theme"] = await self._llm_theme(items, span="最近 7 天")
        return out

    # ---------- random recall ----------

    async def random_recall(self, *, count: int = 3, min_age_days: int = 7) -> dict[str, Any]:
        cutoff = _now() - timedelta(days=max(0, min_age_days))
        # Pull a generous pool then sample.
        pool = await self.brain.list(status="active", limit=500)
        eligible = [i for i in pool if i.created_at <= cutoff and (i.content or "").strip()]
        sample = _random.sample(eligible, min(count, len(eligible))) if eligible else []
        return {
            "count": len(sample),
            "min_age_days": min_age_days,
            "items": [_item_to_dict(i) for i in sample],
        }

    # ---------- helpers ----------

    async def _items_in_range(self, start: datetime, end: datetime) -> list[Item]:
        # The index lists newest-first, paginated. We over-fetch and filter.
        out: list[Item] = []
        offset = 0
        page_size = 200
        while True:
            page = await self.brain.list(status="active", limit=page_size, offset=offset)
            if not page:
                break
            for it in page:
                if start <= it.created_at < end:
                    out.append(it)
            # Stop when oldest in page is before start.
            if page[-1].created_at < start:
                break
            offset += page_size
            if offset > 5000:  # safety bound
                break
        return out

    def _type_counts(self, items: list[Item]) -> dict[str, int]:
        out: dict[str, int] = {}
        for it in items:
            out[it.type] = out.get(it.type, 0) + 1
        return out

    def _concept_counts(self, items: list[Item]) -> list[dict]:
        from .links import extract_links

        counts: dict[str, int] = {}
        for it in items:
            for link in extract_links(it.content):
                if link["type"] != "concept":
                    continue
                counts[link["target"]] = counts.get(link["target"], 0) + 1
        return [
            {"name": name, "count": c}
            for name, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    def _items_per_day(self, items: list[Item], start: datetime, end: datetime) -> list[dict]:
        days: dict[str, int] = {}
        cur = start
        while cur <= end:
            days[cur.strftime("%Y-%m-%d")] = 0
            cur = cur + timedelta(days=1)
        for it in items:
            key = it.created_at.astimezone(_TZ_CST).strftime("%Y-%m-%d")
            if key in days:
                days[key] += 1
        return [{"date": k, "count": v} for k, v in days.items()]

    async def _llm_theme(self, items: list[Item], *, span: str) -> str | None:
        if self.config is None or not getattr(self.config.llm, "enabled", False):
            return None
        try:
            import os
            import httpx
            api_key = os.environ.get(self.config.llm.api_key_env)
            if not api_key:
                return None
            sample = items[:30]
            corpus = "\n\n".join(
                f"- {it.created_at.astimezone(_TZ_CST).strftime('%m-%d %H:%M')} "
                f"{(it.content or '').strip()[:140]}"
                for it in sample
            )
            system = (
                "你是一个个人 dump 库的 AI 助理。"
                f"用户分享了 {span} 的所有记录。请总结 2-3 个主题，"
                "用一句话点出他主要在思考什么。直接陈述，不要套话。"
                "最多 60 字。"
            )
            payload = {
                "model": self.config.llm.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": corpus[:6000]},
                ],
                "temperature": 0.4,
            }
            async with httpx.AsyncClient(timeout=self.config.llm.timeout) as client:
                r = await client.post(
                    self.config.llm.base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                if r.status_code >= 400:
                    log.warning("review LLM HTTP %s: %s", r.status_code, r.text[:200])
                    return None
                data = r.json()
            return (data["choices"][0]["message"]["content"] or "").strip() or None
        except Exception:
            log.exception("review LLM failed")
            return None


class ReviewScheduler:
    """Optional background task that pushes daily/random review to Telegram.

    Wired only from `serve`. Disabled by default — driven by config.toml [review].
    """

    def __init__(
        self,
        brain: ThinkTape,
        config: Config,
        send: Callable,  # async (chat_id, text) -> None
        *,
        daily_at: str = "22:00",
        random_count: int = 3,
        recipients: list[int] | None = None,
    ):
        self.brain = brain
        self.config = config
        self.send = send
        self.daily_at = daily_at
        self.random_count = random_count
        self.recipients = recipients or []
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None and self.recipients:
            self._task = asyncio.create_task(self._run(), name="review-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        engine = ReviewEngine(self.brain, self.config)
        try:
            hh, mm = self.daily_at.split(":")
            target = time(int(hh), int(mm))
        except Exception:
            target = time(22, 0)
        while True:
            try:
                now = _now()
                fire_at = now.replace(hour=target.hour, minute=target.minute,
                                      second=0, microsecond=0)
                if fire_at <= now:
                    fire_at = fire_at + timedelta(days=1)
                await asyncio.sleep(max(1.0, (fire_at - now).total_seconds()))
                use_llm = bool(getattr(self.config.llm, "enabled", False))
                digest = await engine.daily_digest(use_llm=use_llm)
                recall = await engine.random_recall(count=self.random_count)
                text = self._format_push(digest, recall)
                for chat_id in self.recipients:
                    try:
                        await self.send(chat_id, text)
                    except Exception:
                        log.exception("review push failed: %s", chat_id)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("review scheduler tick failed")
                await asyncio.sleep(60)

    @staticmethod
    def _format_push(digest: dict, recall: dict) -> str:
        lines = [f"📅 今日回顾 ({digest.get('date')})",
                 f"  记录 {digest.get('count', 0)} 条"]
        if digest.get("theme"):
            lines.append(f"  主题: {digest['theme']}")
        if digest.get("active_concepts"):
            top = digest["active_concepts"][:3]
            lines.append("  概念: " + ", ".join(f"[[{c['name']}]]" for c in top))
        if recall.get("items"):
            lines.append("\n🎲 随机回顾:")
            for it in recall["items"]:
                body = (it.get("content") or "").strip().replace("\n", " ")[:80]
                lines.append(f"  · {body}")
        return "\n".join(lines)
