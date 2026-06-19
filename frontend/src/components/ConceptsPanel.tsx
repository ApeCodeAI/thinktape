import { Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type Concept } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onClose: () => void;
  onPick: (name: string) => void;
}

export function ConceptsPanel({ open, onClose, onPick }: Props) {
  const [concepts, setConcepts] = useState<Concept[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .concepts()
      .then((r) => {
        if (!cancelled) setConcepts(r.concepts);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const max = concepts && concepts.length ? Math.max(...concepts.map((c) => c.count)) : 1;

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center px-4 py-12 bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl bg-surface rounded-2xl shadow-[0_30px_80px_rgba(32,25,20,0.25)] border border-border-soft overflow-hidden"
      >
        <header className="flex items-center justify-between px-6 py-4 border-b border-border-soft">
          <div className="flex items-baseline gap-3">
            <h2 className="text-[16px] font-serif tracking-tight text-fg">概念索引</h2>
            <span className="text-[12px] text-muted font-serif italic">
              所有 [[wikilink]] 概念
            </span>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="w-8 h-8 grid place-items-center rounded-md hover:bg-border-soft/70 text-muted hover:text-fg"
          >
            <X size={16} />
          </button>
        </header>
        <div className="px-6 py-4 max-h-[60vh] overflow-y-auto">
          {loading && (
            <div className="py-10 grid place-items-center text-meta">
              <Loader2 size={18} className="animate-spin" />
            </div>
          )}
          {error && (
            <div className="text-[color:var(--color-danger)] text-[13px]">
              加载失败: {error}
            </div>
          )}
          {!loading && !error && concepts && concepts.length === 0 && (
            <p className="text-muted font-serif italic text-center py-8">
              还没有任何 [[概念]] — 在内容里试着写 [[Agent 记忆]] 看看
            </p>
          )}
          {!loading && concepts && concepts.length > 0 && (
            <div className="flex flex-wrap gap-2.5">
              {concepts.map((c) => {
                const weight = Math.max(0.7, Math.min(1.6, 0.7 + (c.count / max) * 0.9));
                return (
                  <button
                    key={c.name}
                    onClick={() => {
                      onPick(c.name);
                      onClose();
                    }}
                    className={cn(
                      "inline-flex items-baseline gap-1.5 px-3 py-1 rounded-full",
                      "bg-accent-soft text-meta border border-accent/15",
                      "hover:bg-accent hover:text-white hover:border-accent",
                    )}
                    style={{ fontSize: `${weight}em` }}
                  >
                    <span>[[{c.name}]]</span>
                    <span className="text-[10px] tabular-nums opacity-80">{c.count}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
