import { Search, X } from "lucide-react";

interface Props {
  query: string;
  onQueryChange: (q: string) => void;
}

export function Header({ query, onQueryChange }: Props) {
  return (
    <header className="sticky top-0 z-10 bg-bg/80 backdrop-blur-md border-b border-border-soft">
      <div className="max-w-3xl mx-auto px-5 py-4 flex items-center gap-4">
        <div className="flex items-baseline gap-2 select-none">
          <h1 className="font-serif text-2xl tracking-tight text-fg leading-none">
            braindump
          </h1>
          <span className="font-serif italic text-sm text-meta leading-none">
            ·&nbsp;a paper desk
          </span>
        </div>
        <div className="flex-1" />
        <div className="group flex items-center gap-2 w-full max-w-xs border-b border-border focus-within:border-accent transition-colors">
          <Search size={14} className="text-muted shrink-0" />
          <input
            type="search"
            placeholder="搜索…"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            className="bg-transparent outline-none text-[15px] flex-1 min-w-0 py-2 placeholder:text-muted text-fg"
          />
          {query && (
            <button
              onClick={() => onQueryChange("")}
              className="text-muted hover:text-accent shrink-0"
              aria-label="清除搜索"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
