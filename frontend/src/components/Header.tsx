import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  query: string;
  onQueryChange: (q: string) => void;
}

export function Header({ query, onQueryChange }: Props) {
  return (
    <header className="sticky top-0 z-10 bg-paper/85 backdrop-blur-md border-b border-line">
      <div className="max-w-3xl mx-auto px-4 py-3 flex items-center gap-3">
        <div className="flex items-center gap-2 select-none">
          <div className="w-8 h-8 rounded-lg bg-accent grid place-items-center text-white font-bold text-sm shadow-sm">
            B
          </div>
          <h1 className="font-bold text-lg tracking-tight">braindump</h1>
        </div>
        <div className="flex-1" />
        <div
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 rounded-full bg-white border border-line",
            "transition-shadow focus-within:shadow-sm focus-within:border-accent/40",
            "w-full max-w-xs",
          )}
        >
          <Search size={15} className="text-muted shrink-0" />
          <input
            type="search"
            placeholder="搜索..."
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            className="bg-transparent outline-none text-sm flex-1 min-w-0 placeholder:text-muted"
          />
          {query && (
            <button
              onClick={() => onQueryChange("")}
              className="text-muted hover:text-ink transition-colors"
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
