import type { Stats } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  type: string | null;
  onTypeChange: (t: string | null) => void;
  tag: string | null;
  onTagChange: (t: string | null) => void;
  stats: Stats | null;
  topTags: string[];
}

export function FilterBar({ type, onTypeChange, tag, onTagChange, stats, topTags }: Props) {
  const total = stats?.total ?? 0;
  const today = stats?.today ?? 0;
  const thoughts = stats?.by_type?.thought ?? 0;
  const bookmarks = stats?.by_type?.bookmark ?? 0;
  const notes = stats?.by_type?.note ?? 0;

  return (
    <div className="max-w-3xl mx-auto px-4 pt-5 pb-3 space-y-3">
      <div className="text-xs text-muted flex items-center gap-3">
        <span>共 <b className="text-ink">{total}</b> 条</span>
        <span className="text-line">·</span>
        <span>今日 <b className="text-ink">{today}</b> 条</span>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <Pill active={type === null} onClick={() => onTypeChange(null)}>
          全部
        </Pill>
        <Pill active={type === "thought"} onClick={() => onTypeChange("thought")}>
          💭 想法 {thoughts > 0 && <Count>{thoughts}</Count>}
        </Pill>
        <Pill active={type === "bookmark"} onClick={() => onTypeChange("bookmark")}>
          🔖 收藏 {bookmarks > 0 && <Count>{bookmarks}</Count>}
        </Pill>
        {notes > 0 && (
          <Pill active={type === "note"} onClick={() => onTypeChange("note")}>
            📝 笔记 <Count>{notes}</Count>
          </Pill>
        )}
      </div>
      {topTags.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-muted">标签:</span>
          {tag && (
            <Pill active onClick={() => onTagChange(null)}>
              #{tag} ×
            </Pill>
          )}
          {!tag &&
            topTags.slice(0, 10).map((t) => (
              <Pill key={t} active={false} onClick={() => onTagChange(t)} subtle>
                #{t}
              </Pill>
            ))}
        </div>
      )}
    </div>
  );
}

function Pill({
  children,
  active,
  onClick,
  subtle = false,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
  subtle?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3 py-1 rounded-full text-sm border transition-all",
        active
          ? "bg-accent text-white border-accent shadow-sm"
          : subtle
            ? "bg-transparent text-muted border-line hover:bg-card hover:text-ink"
            : "bg-card text-ink border-line hover:border-accent/40",
      )}
    >
      {children}
    </button>
  );
}

function Count({ children }: { children: React.ReactNode }) {
  return (
    <span className="ml-1 opacity-70 text-xs tabular-nums">{children}</span>
  );
}
