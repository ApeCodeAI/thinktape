import { cn } from "@/lib/utils";

interface Props {
  tag: string;
  onClick?: (tag: string) => void;
}

export function Hashtag({ tag, onClick }: Props) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClick?.(tag);
      }}
      title={`查看 #${tag}`}
      className={cn(
        "inline align-baseline font-medium text-[0.95em]",
        "text-[color:var(--color-accent)] rounded",
        "transition-colors duration-150 hover:underline underline-offset-2",
      )}
    >
      #{tag}
    </button>
  );
}

// Mirror of thinktape/tags.py HASHTAG_RE. The leading boundary (start or
// whitespace) is captured so it can be re-emitted as text — this avoids
// lookbehind and keeps URL fragments / "C#" / Markdown headings unmatched.
const HASHTAG_RE = /(^|\s)#([0-9A-Za-z_一-鿿][0-9A-Za-z_一-鿿/]*)/g;

export function splitHashtags(text: string): Array<
  | { kind: "text"; value: string }
  | { kind: "tag"; tag: string }
> {
  if (!text) return [];
  const out: Array<
    | { kind: "text"; value: string }
    | { kind: "tag"; tag: string }
  > = [];
  let lastIndex = 0;
  HASHTAG_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = HASHTAG_RE.exec(text)) !== null) {
    const lead = m[1] ?? "";
    // text before the match plus the boundary char (whitespace/start)
    const before = text.slice(lastIndex, m.index) + lead;
    if (before) out.push({ kind: "text", value: before });
    const tag = m[2].replace(/\/+$/, "");
    if (tag) out.push({ kind: "tag", tag });
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) {
    out.push({ kind: "text", value: text.slice(lastIndex) });
  }
  return out;
}
