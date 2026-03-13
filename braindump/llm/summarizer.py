"""LLM-based note summarization worker."""

import asyncio
import json
import logging
import re
from datetime import datetime

from openai import AsyncOpenAI

from braindump.config import get_config, get_timezone
from braindump.database import get_db

logger = logging.getLogger("braindump.llm")

# ── Prompt templates ────────────────────────────────────────────

SYSTEM_PROMPT = (
    "你是一个个人笔记助手。用户通过语音、视频或文字记录了个人想法。\n"
    "请分析内容并生成结构化摘要，以 JSON 格式返回。"
)

USER_PROMPT_TEMPLATE = """\
内容类型：{media_type}（{duration}秒）
原文：
{content}

请返回 JSON：
{{
  "title": "简短标题（15字以内）",
  "summary": "核心内容概括（50-100字）",
  "tags": ["标签1", "标签2"],
  "mood": "2-4字情绪标签，如：思考、灵感、吐槽、日常、工作、学习"
}}

注意：
- 保持用户原始的语气和观点，不要美化或改写
- tags 提取内容主题关键词，2-5 个，不要太泛（不要用"笔记"、"想法"这种）
- 原文可能来自语音识别，包含错别字或断句问题，请根据上下文理解原意
- 如果内容太短或没有实质信息，title 用原文前几个字，summary 简短概括即可
- 使用中文回复（除非原文是英文）"""


# ── JSON parsing ────────────────────────────────────────────────

def parse_llm_json(text: str) -> dict:
    """Parse JSON from LLM response, stripping markdown code fences if present."""
    text = text.strip()
    # Remove ```json ... ``` wrapping
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return json.loads(text)


# ── LLM client ──────────────────────────────────────────────────

async def call_llm(content: str, media_type: str, duration: float | None) -> dict:
    """Call LLM API and return parsed summary dict."""
    cfg = get_config()
    api_key = cfg.get_llm_api_key()

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=cfg.llm.base_url,
        timeout=cfg.llm.timeout,
    )

    user_msg = USER_PROMPT_TEMPLATE.format(
        media_type=media_type,
        duration=int(duration) if duration else 0,
        content=content,
    )

    response = await client.chat.completions.create(
        model=cfg.llm.model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or ""
    result = parse_llm_json(raw)

    # Validate required fields
    for key in ("title", "summary", "tags", "mood"):
        if key not in result:
            raise ValueError(f"LLM response missing '{key}' field")

    # Enforce title length (truncate if needed)
    if len(result["title"]) > 15:
        result["title"] = result["title"][:15]

    # Ensure tags is a list
    if isinstance(result["tags"], str):
        result["tags"] = [result["tags"]]

    return result


# ── SummaryWorker ───────────────────────────────────────────────

class SummaryWorker:
    """Async worker that polls for notes needing summarization."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def enqueue(self, note_id: int):
        """Add a note to the summary queue."""
        await self.queue.put(note_id)

    async def run(self):
        """Main worker loop — poll DB for pending notes, call LLM."""
        cfg = get_config()
        if not cfg.llm.enabled:
            logger.info("LLM summarization is disabled, worker idle")
            # Still run the loop so the task doesn't exit (TaskGroup would cancel all)
            while True:
                await asyncio.sleep(60)

        self._running = True

        # Startup scan: reset stuck 'processing' notes
        await self._reset_stuck_notes()

        logger.info("Summary worker started (model: %s)", cfg.llm.model)

        # Re-enqueue pending notes from DB
        await self._enqueue_pending()

        while self._running:
            try:
                note_id = await asyncio.wait_for(self.queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                continue

            await self._process(note_id)

    async def _reset_stuck_notes(self):
        """Reset notes stuck in 'processing' state (from previous crash)."""
        db = await get_db()
        try:
            cursor = await db.execute(
                "UPDATE notes SET summarize_status = 'pending' WHERE summarize_status = 'processing'"
            )
            await db.commit()
            if cursor.rowcount > 0:
                logger.info(
                    "Reset %d stuck summarization(s) from 'processing' to 'pending'",
                    cursor.rowcount,
                )
        finally:
            await db.close()

    async def _enqueue_pending(self):
        """Enqueue any notes with pending summarization status."""
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id FROM notes WHERE summarize_status = 'pending'"
            )
            rows = await cursor.fetchall()
            for row in rows:
                await self.queue.put(row[0])
            if rows:
                logger.info("Enqueued %d pending summarization(s)", len(rows))
        finally:
            await db.close()

    async def _process(self, note_id: int):
        """Summarize a single note."""
        cfg = get_config()

        # Fetch note
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id, content, transcript, media_type, duration, file_path FROM notes WHERE id = ?",
                (note_id,),
            )
            row = await cursor.fetchone()
        finally:
            await db.close()

        if not row:
            logger.warning("Note #%d not found, skipping summary", note_id)
            return

        note = dict(row)

        # Determine the text to summarize
        text = note.get("transcript") or note.get("content") or ""
        if len(text) < cfg.llm.min_content_length:
            logger.info("Note #%d too short (%d chars), marking skipped", note_id, len(text))
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE notes SET summarize_status = 'skipped' WHERE id = ?",
                    (note_id,),
                )
                await db.commit()
            finally:
                await db.close()
            return

        # Mark as processing
        db = await get_db()
        try:
            await db.execute(
                "UPDATE notes SET summarize_status = 'processing' WHERE id = ?",
                (note_id,),
            )
            await db.commit()
        finally:
            await db.close()

        try:
            result = await call_llm(text, note["media_type"], note.get("duration"))

            now = datetime.now(get_timezone()).isoformat()
            tags_json = json.dumps(result["tags"], ensure_ascii=False)

            db = await get_db()
            try:
                await db.execute(
                    """UPDATE notes SET
                        ai_title = ?, ai_summary = ?, ai_tags = ?, ai_mood = ?,
                        ai_model = ?, ai_generated_at = ?, summarize_status = 'done'
                    WHERE id = ?""",
                    (
                        result["title"], result["summary"], tags_json, result["mood"],
                        cfg.llm.model, now, note_id,
                    ),
                )
                await db.commit()
            finally:
                await db.close()

            # Update .md frontmatter if this is a text note with a file
            file_path = note.get("file_path") or ""
            if file_path.endswith(".md"):
                try:
                    from braindump.frontmatter import (
                        build_summary_frontmatter,
                        write_frontmatter_to_file,
                    )
                    from pathlib import Path

                    abs_path = cfg.data_dir / file_path
                    fm_updates = build_summary_frontmatter(
                        ai_title=result["title"],
                        ai_tags_json=tags_json,
                        ai_mood=result["mood"],
                        ai_summary=result["summary"],
                    )
                    write_frontmatter_to_file(abs_path, fm_updates)
                except Exception as fm_err:
                    logger.warning(
                        "Failed to update frontmatter for note #%d: %s",
                        note_id, fm_err,
                    )

            logger.info(
                "Summarized note #%d: %s", note_id, result["title"]
            )

        except Exception as e:
            logger.error("Summary failed for note #%d: %s", note_id, e, exc_info=True)
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE notes SET summarize_status = 'failed' WHERE id = ?",
                    (note_id,),
                )
                await db.commit()
            finally:
                await db.close()

    def stop(self):
        self._running = False

    def queue_size(self) -> int:
        """Return current queue size for health checks."""
        return self.queue.qsize()
