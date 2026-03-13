-- up

-- AI summary fields on notes
ALTER TABLE notes ADD COLUMN ai_title TEXT;
ALTER TABLE notes ADD COLUMN ai_summary TEXT;
ALTER TABLE notes ADD COLUMN ai_tags TEXT;           -- JSON array string
ALTER TABLE notes ADD COLUMN ai_mood TEXT;
ALTER TABLE notes ADD COLUMN ai_model TEXT;           -- which model generated the summary
ALTER TABLE notes ADD COLUMN ai_generated_at TEXT;    -- ISO timestamp of generation
ALTER TABLE notes ADD COLUMN summarize_status TEXT DEFAULT 'pending';
  -- pending | processing | done | skipped | failed

-- Review log for daily review feature (Phase 4)
CREATE TABLE IF NOT EXISTS review_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    FOREIGN KEY (note_id) REFERENCES notes(id)
);

-- FTS: rebuild with ai_title and ai_summary included
-- Drop old triggers first
DROP TRIGGER IF EXISTS notes_ai;
DROP TRIGGER IF EXISTS notes_ad;
DROP TRIGGER IF EXISTS notes_au;

-- Drop old FTS table and recreate with AI fields
DROP TABLE IF EXISTS notes_fts;

CREATE VIRTUAL TABLE notes_fts USING fts5(
    content,
    transcript,
    tags,
    ai_title,
    ai_summary,
    content='notes',
    content_rowid='id'
);

-- Rebuild FTS index from existing data
INSERT INTO notes_fts(rowid, content, transcript, tags, ai_title, ai_summary)
    SELECT id, content, transcript, tags, ai_title, ai_summary FROM notes;

-- New triggers with AI fields
CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, content, transcript, tags, ai_title, ai_summary)
    VALUES (new.id, new.content, new.transcript, new.tags, new.ai_title, new.ai_summary);
END;

CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, content, transcript, tags, ai_title, ai_summary)
    VALUES ('delete', old.id, old.content, old.transcript, old.tags, old.ai_title, old.ai_summary);
END;

CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, content, transcript, tags, ai_title, ai_summary)
    VALUES ('delete', old.id, old.content, old.transcript, old.tags, old.ai_title, old.ai_summary);
    INSERT INTO notes_fts(rowid, content, transcript, tags, ai_title, ai_summary)
    VALUES (new.id, new.content, new.transcript, new.tags, new.ai_title, new.ai_summary);
END;

-- Set summarize_status for existing notes:
-- Text notes with content >= 30 chars → skipped (don't auto-backfill)
-- Audio/video with transcript → skipped
-- Everything else → skipped
UPDATE notes SET summarize_status = 'skipped' WHERE summarize_status = 'pending';

-- down
-- ALTER TABLE notes DROP COLUMN ai_title;
-- etc.
