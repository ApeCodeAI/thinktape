import { Loader2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, type Item, type Stats } from "@/lib/api";
import { ComposeBox } from "@/components/ComposeBox";
import { ConceptsPanel } from "@/components/ConceptsPanel";
import { FilterBar } from "@/components/FilterBar";
import { Header } from "@/components/Header";
import { ItemCard } from "@/components/ItemCard";

const PAGE_SIZE = 30;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function App() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [type, setType] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const [concept, setConcept] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebounced(query, 250);

  const [stats, setStats] = useState<Stats | null>(null);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [conceptsOpen, setConceptsOpen] = useState(false);

  const sentinelRef = useRef<HTMLDivElement>(null);
  const reqId = useRef(0);

  const topTags = useMemo(() => {
    if (!stats) return allTags;
    const sorted = Object.entries(stats.by_tag)
      .sort((a, b) => b[1] - a[1])
      .map(([t]) => t);
    return sorted.length ? sorted : allTags;
  }, [stats, allTags]);

  const refreshStats = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([api.stats(), api.tags()]);
      setStats(s);
      setAllTags(t.tags);
    } catch (e) {
      console.error("stats failed", e);
    }
  }, []);

  const loadPage = useCallback(
    async (offset: number, replace: boolean) => {
      const myReq = ++reqId.current;
      setLoading(true);
      setError(null);
      try {
        if (concept) {
          // Concept-filtered view: server returns all matches in one shot.
          if (offset > 0) {
            setLoading(false);
            return;
          }
          const resp = await api.concept(concept);
          if (myReq !== reqId.current) return;
          setItems(resp.items);
          setDone(true);
          return;
        }
        const resp = await api.list({
          type: type ?? undefined,
          tag: tag ?? undefined,
          q: debouncedQuery || undefined,
          limit: PAGE_SIZE,
          offset,
        });
        if (myReq !== reqId.current) return;
        setItems((prev) => (replace ? resp.items : [...prev, ...resp.items]));
        setDone(resp.items.length < PAGE_SIZE);
      } catch (e) {
        if (myReq !== reqId.current) return;
        setError(String(e));
      } finally {
        if (myReq === reqId.current) setLoading(false);
      }
    },
    [type, tag, debouncedQuery, concept],
  );

  useEffect(() => {
    setItems([]);
    setDone(false);
    loadPage(0, true);
  }, [type, tag, debouncedQuery, concept, loadPage]);

  useEffect(() => {
    refreshStats();
  }, [refreshStats]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loading && !done && items.length > 0) {
          loadPage(items.length, false);
        }
      },
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [items.length, loading, done, loadPage]);

  const handleUpdate = (i: Item) => {
    setItems((prev) => prev.map((x) => (x.id === i.id ? i : x)));
    refreshStats();
  };
  const handleDelete = (id: string) => {
    setItems((prev) => prev.filter((x) => x.id !== id));
    refreshStats();
  };
  const handleCreated = (i: Item) => {
    setItems((prev) => [i, ...prev.filter((x) => x.id !== i.id)]);
    refreshStats();
  };

  const handleConceptPick = (name: string) => {
    setConcept(name);
    setType(null);
    setTag(null);
    setQuery("");
    if (typeof window !== "undefined") window.scrollTo({ top: 0 });
  };

  const handleItemLink = (id: string) => {
    if (typeof document === "undefined") return;
    const node = document.getElementById(`item-${id}`);
    if (node) {
      node.scrollIntoView({ behavior: "smooth", block: "center" });
      node.classList.add("link-flash");
      setTimeout(() => node.classList.remove("link-flash"), 1400);
    } else {
      // Item not in current view — fetch and scroll to it once loaded.
      api
        .get(id)
        .then((it) => {
          setItems((prev) => (prev.some((p) => p.id === it.id) ? prev : [it, ...prev]));
          setTimeout(() => {
            const n = document.getElementById(`item-${id}`);
            if (n) {
              n.scrollIntoView({ behavior: "smooth", block: "center" });
              n.classList.add("link-flash");
              setTimeout(() => n.classList.remove("link-flash"), 1400);
            }
          }, 80);
        })
        .catch(() => {
          alert(`未找到 ${id}`);
        });
    }
  };

  const empty = !loading && items.length === 0 && !error;

  return (
    <div className="min-h-screen">
      <Header
        query={query}
        onQueryChange={setQuery}
        onConceptsClick={() => setConceptsOpen(true)}
      />
      <FilterBar
        type={type}
        onTypeChange={(t) => {
          setType(t);
          setTag(null);
          setConcept(null);
        }}
        tag={tag}
        onTagChange={(t) => {
          setTag(t);
          setConcept(null);
        }}
        stats={stats}
        topTags={topTags}
      />

      <main className="max-w-3xl mx-auto px-5 pb-24">
        {concept && (
          <div className="my-4 flex items-center justify-between gap-3 px-4 py-3 rounded-2xl bg-accent-soft border border-accent/15">
            <div className="text-[13px] text-meta">
              <span className="font-serif italic mr-1.5">概念</span>
              <span className="font-medium">[[{concept}]]</span>
              <span className="ml-2 text-muted">{items.length} 条相关</span>
            </div>
            <button
              onClick={() => setConcept(null)}
              className="inline-flex items-center gap-1 text-[12px] text-meta hover:text-[color:var(--color-accent)] px-2 py-1 rounded-md hover:bg-surface"
              aria-label="清除概念筛选"
            >
              <X size={13} />
              <span>清除</span>
            </button>
          </div>
        )}

        <div className="mt-2 mb-4">
          <ComposeBox onCreated={handleCreated} />
        </div>

        {error && (
          <div className="my-4 p-4 rounded-2xl border border-[rgba(179,58,58,0.25)] bg-[rgba(179,58,58,0.06)] text-[color:var(--color-danger)] text-sm">
            加载失败: {error}
          </div>
        )}

        {empty && (
          <div className="my-20 text-center text-muted">
            <div className="font-serif text-meta text-2xl mb-3">✦</div>
            <p className="font-serif italic text-[15px] text-fg-2">
              {debouncedQuery
                ? `没有匹配 "${debouncedQuery}" 的记录`
                : concept
                  ? `没有任何记录关联 [[${concept}]]`
                  : tag
                    ? `"${tag}" 还没有记录`
                    : "还没有任何记录，发送消息给 Bot 试试吧"}
            </p>
          </div>
        )}

        <div className="space-y-4 mt-4">
          {items.map((i) => (
            <div key={i.id} id={`item-${i.id}`}>
              <ItemCard
                item={i}
                onUpdate={handleUpdate}
                onDelete={handleDelete}
                onTagClick={(t) => setTag(t)}
                onConceptClick={handleConceptPick}
                onItemLinkClick={handleItemLink}
              />
            </div>
          ))}
        </div>

        <div ref={sentinelRef} className="h-8" />
        {loading && (
          <div className="py-6 grid place-items-center text-meta">
            <Loader2 size={18} className="animate-spin" />
          </div>
        )}
        {done && items.length > 0 && (
          <div className="py-8 text-center text-[13px] text-muted font-serif italic tracking-wide">
            — 到底啦 —
          </div>
        )}
      </main>

      <ConceptsPanel
        open={conceptsOpen}
        onClose={() => setConceptsOpen(false)}
        onPick={handleConceptPick}
      />
    </div>
  );
}
