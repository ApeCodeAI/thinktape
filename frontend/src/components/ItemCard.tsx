import { Check, MoreHorizontal, Pencil, Tag, Trash2, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { api, type Item } from "@/lib/api";
import { cn, formatTimestamp } from "@/lib/utils";
import { AudioPlayer } from "./AudioPlayer";
import { Backlinks } from "./Backlinks";
import { BookmarkCard } from "./BookmarkCard";
import { ImageGrid } from "./ImageGrid";
import { Markdown } from "./Markdown";

interface Props {
  item: Item;
  onUpdate: (i: Item) => void;
  onDelete: (id: string) => void;
  onTagClick: (tag: string) => void;
  onConceptClick?: (name: string) => void;
  onItemLinkClick?: (id: string) => void;
}

const TYPE_LABEL: Record<string, { label: string; mark: string }> = {
  thought: { label: "想法", mark: "✦" },
  bookmark: { label: "收藏", mark: "❖" },
  note: { label: "笔记", mark: "§" },
};

export function ItemCard({
  item,
  onUpdate,
  onDelete,
  onTagClick,
  onConceptClick,
  onItemLinkClick,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [editingTags, setEditingTags] = useState(false);
  const [tagInput, setTagInput] = useState(item.tags.join(", "));
  const menuRef = useRef<HTMLDivElement>(null);
  const typeMeta = TYPE_LABEL[item.type] ?? TYPE_LABEL.thought;

  // ---- content editing ----
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.content);
  const [saving, setSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // sync draft if parent item changes (e.g. transcription arrives)
    if (!editing) setDraft(item.content);
  }, [item.content, editing]);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  // auto-resize textarea to fit content
  useLayoutEffect(() => {
    if (!editing) return;
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
  }, [draft, editing]);

  // focus + cursor to end on entering edit mode
  useEffect(() => {
    if (!editing) return;
    const ta = textareaRef.current;
    if (!ta) return;
    ta.focus();
    const end = ta.value.length;
    ta.setSelectionRange(end, end);
  }, [editing]);

  const handleDelete = async () => {
    if (!confirm("确定删除这条记录？")) return;
    try {
      await api.delete(item.id);
      onDelete(item.id);
    } catch (e) {
      alert(`删除失败: ${e}`);
    }
  };

  const saveTags = async () => {
    const tags = tagInput
      .split(/[,，\s]+/)
      .map((t) => t.replace(/^#/, "").trim())
      .filter(Boolean);
    try {
      const updated = await api.patch(item.id, { tags });
      onUpdate(updated);
      setEditingTags(false);
    } catch (e) {
      alert(`保存标签失败: ${e}`);
    }
  };

  const transcribing = item.content.startsWith("[转写");
  const showBookmark = item.type === "bookmark" && item.bookmark_url;
  const bodyContent = showBookmark
    ? item.content.replace(item.bookmark_url ?? "", "").trim()
    : item.content;

  const enterEdit = () => {
    if (transcribing) return; // wait for transcription to finish
    setDraft(item.content);
    setEditing(true);
  };

  const exitEdit = () => {
    setEditing(false);
    setDraft(item.content);
  };

  const saveDraft = async (next: string) => {
    if (saving) return;
    const trimmed = next.trim();
    if (trimmed === item.content.trim()) {
      setEditing(false);
      return;
    }
    if (!trimmed) {
      // refuse to save empty — treat as cancel
      exitEdit();
      return;
    }
    setSaving(true);
    try {
      const updated = await api.patch(item.id, { content: next });
      onUpdate(updated);
      setEditing(false);
    } catch (e) {
      alert(`保存失败: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const onBodyDoubleClick = (e: React.MouseEvent) => {
    if (editing) return;
    const target = e.target as HTMLElement;
    // Don't hijack double-click on interactive children
    const tag = target.tagName?.toUpperCase();
    if (tag === "A" || tag === "BUTTON" || tag === "IMG" || tag === "INPUT") return;
    if (target.closest("a, button, input, audio, video")) return;
    enterEdit();
  };

  return (
    <article
      className={cn(
        "group bg-surface rounded-2xl border border-border-soft px-6 py-5",
        "transition-shadow duration-200",
        editing
          ? "shadow-[0_20px_52px_rgba(32,25,20,0.12)] border-border ring-1 ring-accent/20"
          : "hover:shadow-[0_20px_52px_rgba(32,25,20,0.08)]",
      )}
    >
      {/* Header */}
      <header className="flex items-center justify-between gap-2 mb-3.5 text-[12px]">
        <div className="flex items-center gap-2.5 text-muted">
          <span className="text-meta font-serif text-[14px] leading-none">
            {typeMeta.mark}
          </span>
          <time className="font-serif italic tracking-wide">
            {formatTimestamp(item.created_at)}
          </time>
          <span className="text-border">·</span>
          <span>{typeMeta.label}</span>
          {editing && (
            <>
              <span className="text-border">·</span>
              <span className="text-meta font-serif italic warm-pulse">编辑中</span>
            </>
          )}
        </div>
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="w-7 h-7 grid place-items-center rounded-md hover:bg-border-soft/70 text-muted hover:text-fg"
            aria-label="更多操作"
          >
            <MoreHorizontal size={16} />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-8 w-36 bg-surface border border-border-soft rounded-xl shadow-[0_20px_52px_rgba(32,25,20,0.12)] py-1.5 z-20">
              <MenuItem
                icon={<Pencil size={13} />}
                onClick={() => {
                  setMenuOpen(false);
                  enterEdit();
                }}
                disabled={transcribing}
              >
                编辑内容
              </MenuItem>
              <MenuItem
                icon={<Tag size={13} />}
                onClick={() => {
                  setMenuOpen(false);
                  setEditingTags(true);
                }}
              >
                编辑标签
              </MenuItem>
              <div className="my-1 h-px bg-border-soft mx-2" />
              <MenuItem
                icon={<Trash2 size={13} />}
                danger
                onClick={() => {
                  setMenuOpen(false);
                  handleDelete();
                }}
              >
                删除
              </MenuItem>
            </div>
          )}
        </div>
      </header>

      {/* Body */}
      <div className="space-y-3.5">
        {showBookmark && !editing && <BookmarkCard url={item.bookmark_url!} />}

        {editing ? (
          <div className="space-y-3">
            <textarea
              ref={textareaRef}
              className="edit-textarea"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  saveDraft(draft);
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  exitEdit();
                }
              }}
              onBlur={() => {
                // small delay to allow save/cancel button clicks
                setTimeout(() => {
                  if (textareaRef.current && document.activeElement === textareaRef.current) return;
                  if (saving) return;
                  if (!editing) return;
                  saveDraft(draft);
                }, 80);
              }}
              placeholder="写点什么…"
            />
            <div className="flex items-center justify-between gap-2 pt-1 border-t border-border-soft">
              <span className="text-[11px] text-muted font-serif italic">
                ⌘/Ctrl + Enter 保存 · Esc 取消
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  onMouseDown={(e) => {
                    e.preventDefault();
                    exitEdit();
                  }}
                  className="px-2.5 py-1 rounded-md text-[12px] text-muted hover:text-fg hover:bg-border-soft/60"
                  aria-label="取消"
                >
                  <span className="inline-flex items-center gap-1">
                    <X size={12} /> 取消
                  </span>
                </button>
                <button
                  onMouseDown={(e) => {
                    e.preventDefault();
                    saveDraft(draft);
                  }}
                  disabled={saving}
                  className="px-2.5 py-1 rounded-md text-[12px] bg-accent text-white hover:bg-[#86492a] disabled:opacity-60"
                  aria-label="保存"
                >
                  <span className="inline-flex items-center gap-1">
                    <Check size={12} /> {saving ? "保存中…" : "保存"}
                  </span>
                </button>
              </div>
            </div>
          </div>
        ) : (
          bodyContent && (
            <div
              onDoubleClick={onBodyDoubleClick}
              className={cn(
                "prose-card cursor-text select-text",
                transcribing && "text-muted italic",
              )}
              title="双击编辑"
            >
              <Markdown
                onWikilinkClick={(target, kind) => {
                  if (kind === "item") {
                    onItemLinkClick?.(target);
                  } else {
                    onConceptClick?.(target);
                  }
                }}
              >
                {bodyContent}
              </Markdown>
            </div>
          )
        )}

        {!editing && item.has_images && item.images.length > 0 && (
          <ImageGrid itemId={item.id} images={item.images} imageUrl={api.imageUrl} />
        )}

        {!editing && item.has_audio && <AudioPlayer src={api.audioUrl(item.id)} />}

        {!editing && item.has_video && (
          <video
            src={api.videoUrl(item.id)}
            controls
            preload="metadata"
            className="w-full rounded-lg max-h-[400px] bg-black"
          />
        )}
      </div>

      {/* Links + backlinks */}
      {!editing && !transcribing && (
        <Backlinks
          itemId={item.id}
          onItemClick={(id) => onItemLinkClick?.(id)}
          onConceptClick={(name) => onConceptClick?.(name)}
        />
      )}

      {/* Tags */}
      {(item.tags.length > 0 || editingTags) && (
        <footer className="mt-4 pt-3 border-t border-border-soft flex items-center gap-2 flex-wrap">
          {editingTags ? (
            <>
              <input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                placeholder="逗号分隔，如: 想法, 阅读"
                className="flex-1 min-w-[180px] text-[13px] px-0 py-1 bg-transparent border-b border-border focus:border-accent outline-none text-fg placeholder:text-muted"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveTags();
                  if (e.key === "Escape") {
                    setEditingTags(false);
                    setTagInput(item.tags.join(", "));
                  }
                }}
              />
              <button
                onClick={saveTags}
                className="w-7 h-7 rounded-md bg-accent text-white grid place-items-center hover:bg-[#86492a]"
                aria-label="保存"
              >
                <Check size={14} />
              </button>
            </>
          ) : (
            item.tags.map((t) => (
              <button
                key={t}
                onClick={() => onTagClick(t)}
                className="text-[12px] px-2.5 py-0.5 rounded-full bg-accent-soft text-meta border border-accent/10 hover:bg-accent hover:text-white hover:border-accent"
              >
                #{t}
              </button>
            ))
          )}
        </footer>
      )}
    </article>
  );
}

function MenuItem({
  children,
  icon,
  onClick,
  danger = false,
  disabled = false,
}: {
  children: React.ReactNode;
  icon: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "w-full px-3 py-1.5 text-left text-[13px] flex items-center gap-2",
        disabled && "opacity-40 cursor-not-allowed",
        !disabled && (danger
          ? "text-[color:var(--color-danger)] hover:bg-[rgba(179,58,58,0.06)]"
          : "text-fg-2 hover:bg-border-soft/60 hover:text-fg"),
      )}
    >
      {icon}
      <span>{children}</span>
    </button>
  );
}
