import { ChevronDown, ChevronRight, Link2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type Backlink, type OutgoingLink } from "@/lib/api";
import { cn, formatTimestamp } from "@/lib/utils";

interface Props {
  itemId: string;
  onItemClick: (id: string) => void;
  onConceptClick: (name: string) => void;
}

interface LoadedLinks {
  outgoing: OutgoingLink[];
  backlinks: Backlink[];
}

export function Backlinks({ itemId, onItemClick, onConceptClick }: Props) {
  const [data, setData] = useState<LoadedLinks | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .links(itemId)
      .then((d) => {
        if (cancelled) return;
        setData(d);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [itemId]);

  if (loading) return null;
  if (error) return null;
  if (!data) return null;

  const outgoingItem = data.outgoing.filter((l) => l.type === "item");
  const outgoingConcept = data.outgoing.filter((l) => l.type === "concept");
  const totalOutgoing = outgoingItem.length + outgoingConcept.length;
  const totalBack = data.backlinks.length;
  const total = totalOutgoing + totalBack;
  if (total === 0) return null;

  return (
    <section className="mt-4 pt-3 border-t border-border-soft">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[12px] text-muted hover:text-meta font-serif italic"
        aria-expanded={open}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Link2 size={12} className="opacity-70" />
        <span>关联 {total}</span>
        {totalOutgoing > 0 && <span className="text-muted/80">· 链出 {totalOutgoing}</span>}
        {totalBack > 0 && <span className="text-muted/80">· 反链 {totalBack}</span>}
      </button>
      {open && (
        <div className="mt-3 space-y-2.5 text-[13px]">
          {outgoingConcept.length > 0 && (
            <ul className="space-y-1.5">
              {outgoingConcept.map((link) =>
                link.type === "concept" ? (
                  <li key={`oc-${link.target}`} className="flex items-start gap-2">
                    <span className="text-meta">→</span>
                    <button
                      onClick={() => onConceptClick(link.target)}
                      className="text-meta hover:text-[color:var(--color-accent)] underline decoration-dotted underline-offset-2"
                    >
                      [[{link.target}]]
                    </button>
                    {link.match_count > 0 && (
                      <span className="text-muted text-[12px]">
                        {link.match_count} 处提及
                      </span>
                    )}
                  </li>
                ) : null,
              )}
            </ul>
          )}

          {outgoingItem.length > 0 && (
            <ul className="space-y-1.5">
              {outgoingItem.map((link) =>
                link.type === "item" ? (
                  <li key={`oi-${link.target}`} className="flex items-start gap-2">
                    <span className="text-meta">→</span>
                    <button
                      onClick={() => onItemClick(link.target)}
                      className="text-left hover:text-[color:var(--color-accent)]"
                    >
                      <span className="text-meta font-serif italic">{link.target}</span>
                      {link.item && (
                        <span className="text-fg-2 ml-2">
                          {truncate(link.item.content, 60)}
                        </span>
                      )}
                    </button>
                  </li>
                ) : null,
              )}
            </ul>
          )}

          {totalBack > 0 && (
            <ul className="space-y-1.5">
              {data.backlinks.map((b) => (
                <li key={`bl-${b.id}`} className={cn("flex items-start gap-2")}>
                  <span className="text-meta">←</span>
                  <button
                    onClick={() => onItemClick(b.id)}
                    className="text-left hover:text-[color:var(--color-accent)] flex-1"
                  >
                    <span className="text-meta font-serif italic mr-2">
                      {formatTimestamp(b.created_at)}
                    </span>
                    <span className="text-fg-2">{truncate(b.content, 100)}</span>
                    <span className="ml-1 text-muted text-[11px]">
                      [[{b.link_text}]]
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function truncate(s: string, n: number): string {
  const v = (s ?? "").replace(/\s+/g, " ").trim();
  return v.length > n ? v.slice(0, n - 1) + "…" : v;
}
