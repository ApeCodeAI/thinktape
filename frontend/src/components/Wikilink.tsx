import { cn } from "@/lib/utils";

export type WikilinkKind = "concept" | "item";

interface Props {
  target: string;
  kind: WikilinkKind;
  onClick: (target: string, kind: WikilinkKind) => void;
}

export function Wikilink({ target, kind, onClick }: Props) {
  const isItem = kind === "item";
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClick(target, kind);
      }}
      title={isItem ? `跳转到 ${target}` : `查看 “${target}” 相关`}
      className={cn(
        "inline-flex items-center align-baseline gap-0.5",
        "px-1.5 py-0 rounded-md leading-snug",
        "text-[0.92em] font-medium border whitespace-nowrap",
        "transition-colors duration-150",
        isItem
          ? "text-[color:var(--color-accent)] bg-transparent border-transparent underline decoration-dotted underline-offset-2 hover:bg-accent-soft"
          : "text-meta bg-accent-soft border-accent/15 hover:bg-accent hover:text-white hover:border-accent",
      )}
    >
      {!isItem && <span className="opacity-60">[[</span>}
      <span>{target}</span>
      {!isItem && <span className="opacity-60">]]</span>}
    </button>
  );
}

const WIKILINK_RE = /\[\[([^\[\]]+)\]\]/g;
const ITEM_ID_RE = /^\d{8}-\d{6}-[0-9a-f]{4}$/;

export function splitWikilinks(text: string): Array<
  | { kind: "text"; value: string }
  | { kind: "link"; target: string; type: WikilinkKind }
> {
  if (!text) return [];
  const out: Array<
    | { kind: "text"; value: string }
    | { kind: "link"; target: string; type: WikilinkKind }
  > = [];
  let lastIndex = 0;
  WIKILINK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = WIKILINK_RE.exec(text)) !== null) {
    if (m.index > lastIndex) {
      out.push({ kind: "text", value: text.slice(lastIndex, m.index) });
    }
    const raw = m[1].trim();
    if (raw) {
      const type: WikilinkKind = ITEM_ID_RE.test(raw) ? "item" : "concept";
      out.push({ kind: "link", target: raw, type });
    }
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) {
    out.push({ kind: "text", value: text.slice(lastIndex) });
  }
  return out;
}
