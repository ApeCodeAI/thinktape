import { ExternalLink, Globe } from "lucide-react";

interface Props {
  url: string;
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function BookmarkCard({ url }: Props) {
  const host = hostOf(url);
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-border-soft bg-bg/60 hover:bg-bg hover:border-accent/40 group"
    >
      <div className="w-8 h-8 rounded-md bg-surface border border-border-soft grid place-items-center text-muted group-hover:text-accent shrink-0">
        <Globe size={14} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] text-muted truncate font-serif italic">{host}</div>
        <div className="text-[14px] text-fg-2 truncate group-hover:text-accent">
          {url}
        </div>
      </div>
      <ExternalLink size={14} className="text-muted shrink-0 group-hover:text-accent" />
    </a>
  );
}
