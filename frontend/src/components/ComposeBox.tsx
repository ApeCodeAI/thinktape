import { Loader2, Send } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";

import { api, type Item } from "@/lib/api";
import { cn } from "@/lib/utils";

type ItemType = "thought" | "bookmark" | "note";

const TYPE_OPTIONS: { value: ItemType; label: string; mark: string }[] = [
  { value: "thought", label: "想法", mark: "✦" },
  { value: "bookmark", label: "收藏", mark: "❖" },
  { value: "note", label: "笔记", mark: "§" },
];

const URL_RE = /https?:\/\/[^\s<>"']+/i;

interface Props {
  onCreated: (item: Item) => void;
}

export function ComposeBox({ onCreated }: Props) {
  const [content, setContent] = useState("");
  const [type, setType] = useState<ItemType>("thought");
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [expanded, setExpanded] = useState(false);

  // auto-resize textarea
  useLayoutEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.max(ta.scrollHeight, expanded ? 100 : 44)}px`;
  }, [content, expanded]);

  const detectedUrl = type === "bookmark" || URL_RE.test(content)
    ? content.match(URL_RE)?.[0] ?? null
    : null;

  const clear = () => {
    setContent("");
    setTagInput("");
    setError(null);
    setExpanded(false);
    setType("thought");
  };

  const submit = async () => {
    const text = content.trim();
    if (!text || saving) return;
    setSaving(true);
    setError(null);
    const tags = tagInput
      .split(/[,，\s]+/)
      .map((t) => t.replace(/^#/, "").trim())
      .filter(Boolean);
    const effectiveType = detectedUrl && type === "thought" ? "bookmark" : type;
    try {
      const item = await api.create({
        content: text,
        type: effectiveType,
        source: "web",
        tags,
        bookmark_url: effectiveType === "bookmark" ? detectedUrl : null,
      });
      onCreated(item);
      clear();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape" && !content) {
      setExpanded(false);
      textareaRef.current?.blur();
    }
  };

  const onFocus = () => setExpanded(true);
  const onBlur = () => {
    // collapse only if empty
    if (!content.trim() && !tagInput.trim()) setExpanded(false);
  };

  return (
    <section
      className={cn(
        "bg-surface rounded-2xl border border-border-soft px-5 pt-4 pb-3",
        "transition-shadow duration-200",
        expanded
          ? "shadow-[0_20px_52px_rgba(32,25,20,0.08)] ring-1 ring-accent/15"
          : "hover:shadow-[0_8px_24px_rgba(32,25,20,0.05)]",
      )}
    >
      <textarea
        ref={textareaRef}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={onFocus}
        onBlur={onBlur}
        placeholder="记录想法…"
        rows={1}
        className="edit-textarea"
      />

      {(expanded || content) && (
        <div className="mt-3 pt-3 border-t border-border-soft space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] text-muted font-serif italic mr-1">类型</span>
            {TYPE_OPTIONS.map((opt) => {
              const active = type === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => setType(opt.value)}
                  className={cn(
                    "px-3 py-1 rounded-full text-[12px] border leading-5 select-none",
                    active
                      ? "bg-accent text-white border-accent"
                      : "bg-surface text-fg-2 border-border hover:text-fg hover:border-accent/50",
                  )}
                >
                  <span className="font-serif mr-1">{opt.mark}</span>
                  {opt.label}
                </button>
              );
            })}
            {detectedUrl && type === "thought" && (
              <span className="text-[11px] text-meta font-serif italic">
                ↪ 检测到链接，将保存为收藏
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <input
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              placeholder="标签：逗号分隔，如 AI, 阅读"
              className="flex-1 text-[13px] px-0 py-1 bg-transparent border-b border-border-soft focus:border-accent outline-none text-fg placeholder:text-muted"
            />
          </div>

          {error && (
            <div className="text-[12px] text-[color:var(--color-danger)]">
              {error}
            </div>
          )}

          <div className="flex items-center justify-between gap-2 pt-1">
            <span className="text-[11px] text-muted font-serif italic">
              ⌘/Ctrl + Enter 发送
            </span>
            <div className="flex items-center gap-1.5">
              <button
                onClick={clear}
                disabled={saving}
                className="px-2.5 py-1 rounded-md text-[12px] text-muted hover:text-fg hover:bg-border-soft/60 disabled:opacity-40"
              >
                清空
              </button>
              <button
                onClick={submit}
                disabled={saving || !content.trim()}
                className="px-3 py-1 rounded-md text-[12px] bg-accent text-white hover:bg-[#86492a] disabled:opacity-60 inline-flex items-center gap-1.5"
              >
                {saving ? (
                  <>
                    <Loader2 size={12} className="animate-spin" /> 保存中
                  </>
                ) : (
                  <>
                    <Send size={12} /> 记录
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
