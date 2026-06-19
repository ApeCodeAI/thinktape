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
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-line bg-paper/60 hover:bg-paper hover:border-accent/40 transition-colors group"
    >
      <div className="w-8 h-8 rounded-md bg-white border border-line grid place-items-center text-muted shrink-0">
        <Globe size={14} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-muted truncate">{host}</div>
        <div className="text-sm truncate group-hover:text-accent transition-colors">
          {url}
        </div>
      </div>
      <ExternalLink size={14} className="text-muted shrink-0 group-hover:text-accent" />
    </a>
  );
}
