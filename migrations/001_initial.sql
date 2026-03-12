-- up
CREATE TABLE notes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,

    -- content
    content       TEXT,
    media_type    TEXT NOT NULL DEFAULT 'text',
    file_path     TEXT,
    thumbnail     TEXT,
    transcript    TEXT,

    -- time
    created_at    TEXT NOT NULL,
    display_date  TEXT NOT NULL,
    imported_at   TEXT NOT NULL,

    -- source
    source        TEXT NOT NULL DEFAULT 'telegram',
    source_id     TEXT,

    -- metadata
    tags          TEXT DEFAULT '',
    duration      REAL,
    file_size     INTEGER,

    -- forward info
    is_forwarded  INTEGER DEFAULT 0,
    forward_from  TEXT,
    forward_date  TEXT,

    -- status
    is_deleted    INTEGER DEFAULT 0,
    transcribe_status TEXT DEFAULT 'pending'
);

CREATE TABLE attachments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id    INTEGER NOT NULL REFERENCES notes(id),
    file_path  TEXT NOT NULL,
    media_type TEXT NOT NULL,
    thumbnail  TEXT,
    file_size  INTEGER,
    duration   REAL,
    sort_order INTEGER DEFAULT 0
);

CREATE INDEX idx_notes_created_at ON notes(created_at DESC);
CREATE INDEX idx_notes_source ON notes(source);
CREATE INDEX idx_notes_media_type ON notes(media_type);
CREATE INDEX idx_notes_display_date ON notes(display_date DESC);
CREATE INDEX idx_notes_is_deleted ON notes(is_deleted);
CREATE INDEX idx_attachments_note_id ON attachments(note_id);

CREATE VIRTUAL TABLE notes_fts USING fts5(
    content,
    transcript,
    tags,
    content='notes',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, content, transcript, tags)
    VALUES (new.id, new.content, new.transcript, new.tags);
END;

CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, content, transcript, tags)
    VALUES ('delete', old.id, old.content, old.transcript, old.tags);
END;

CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, content, transcript, tags)
    VALUES ('delete', old.id, old.content, old.transcript, old.tags);
    INSERT INTO notes_fts(rowid, content, transcript, tags)
    VALUES (new.id, new.content, new.transcript, new.tags);
END;

-- down
-- DROP TABLE IF EXISTS notes_fts;
-- DROP TABLE IF EXISTS attachments;
-- DROP TABLE IF EXISTS notes;
