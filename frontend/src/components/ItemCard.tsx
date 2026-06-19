import { Check, MoreHorizontal, Tag, Trash2 } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api, type Item } from "@/lib/api";
import { cn, formatTimestamp } from "@/lib/utils";
import { AudioPlayer } from "./AudioPlayer";
import { BookmarkCard } from "./BookmarkCard";
import { ImageGrid } from "./ImageGrid";

interface Props {
  item: Item;
  onUpdate: (i: Item) => void;
  onDelete: (id: string) => void;
  onTagClick: (tag: string) => void;
}

const TYPE_LABEL: Record<string, { label: string; icon: string }> = {
  thought: { label: "想法", icon: "💭" },
  bookmark: { label: "收藏", icon: "🔖" },
  note: { label: "笔记", icon: "📝" },
};

export function ItemCard({ item, onUpdate, onDelete, onTagClick }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [editingTags, setEditingTags] = useState(false);
  const [tagInput, setTagInput] = useState(item.tags.join(", "));
  const menuRef = useRef<HTMLDivElement>(null);
  const typeMeta = TYPE_LABEL[item.type] ?? TYPE_LABEL.thought;

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
  // For bookmarks, the content might be just the URL — show it as a card instead of raw URL text.
  const bodyContent = showBookmark
    ? item.content.replace(item.bookmark_url ?? "", "").trim()
    : item.content;

  return (
    <article className="bg-card rounded-2xl border border-line p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)] hover:shadow-[0_2px_8px_rgba(0,0,0,0.04)] transition-shadow">
      {/* Header */}
      <header className="flex items-center justify-between gap-2 mb-3 text-xs text-muted">
        <div className="flex items-center gap-2">
          <span className="text-sm">{typeMeta.icon}</span>
          <time>{formatTimestamp(item.created_at)}</time>
          <span className="text-line">·</span>
          <span>{typeMeta.label}</span>
        </div>
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="w-7 h-7 grid place-items-center rounded-md hover:bg-line/60 text-muted hover:text-ink transition-colors"
            aria-label="更多操作"
          >
            <MoreHorizontal size={16} />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-8 w-32 bg-card border border-line rounded-lg shadow-md py-1 z-20">
              <button
                onClick={() => {
                  setMenuOpen(false);
                  setEditingTags(true);
                }}
                className="w-full px-3 py-1.5 text-left text-sm hover:bg-paper flex items-center gap-2"
              >
                <Tag size={13} /> 编辑标签
              </button>
              <button
                onClick={() => {
                  setMenuOpen(false);
                  handleDelete();
                }}
                className="w-full px-3 py-1.5 text-left text-sm hover:bg-paper text-red-600 flex items-center gap-2"
              >
                <Trash2 size={13} /> 删除
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Body */}
      <div className="space-y-3">
        {showBookmark && <BookmarkCard url={item.bookmark_url!} />}

        {bodyContent && (
          <div
            className={cn(
              "prose-card text-[15px]",
              transcribing && "text-muted italic",
            )}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{bodyContent}</ReactMarkdown>
          </div>
        )}

        {item.has_images && item.images.length > 0 && (
          <ImageGrid itemId={item.id} images={item.images} imageUrl={api.imageUrl} />
        )}

        {item.has_audio && <AudioPlayer src={api.audioUrl(item.id)} />}

        {item.has_video && (
          <video
            src={api.videoUrl(item.id)}
            controls
            preload="metadata"
            className="w-full rounded-lg max-h-[400px] bg-black"
          />
        )}
      </div>

      {/* Tags */}
      {(item.tags.length > 0 || editingTags) && (
        <footer className="mt-3 pt-3 border-t border-line/60 flex items-center gap-2 flex-wrap">
          {editingTags ? (
            <>
              <input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                placeholder="逗号分隔，如: 想法, 阅读"
                className="flex-1 min-w-[160px] text-sm px-2 py-1 rounded-md border border-line bg-paper outline-none focus:border-accent/40"
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
                className="w-7 h-7 rounded-md bg-accent text-white grid place-items-center hover:bg-amber-600"
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
                className="text-xs px-2 py-0.5 rounded-md bg-accent-soft text-accent border border-accent/15 hover:bg-accent hover:text-white transition-colors"
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
