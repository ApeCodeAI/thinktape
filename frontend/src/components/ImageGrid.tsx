import { X } from "lucide-react";
import { useEffect, useState } from "react";

interface Props {
  itemId: string;
  images: string[];
  imageUrl: (id: string, name: string) => string;
}

export function ImageGrid({ itemId, images, imageUrl }: Props) {
  const [zoom, setZoom] = useState<string | null>(null);

  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setZoom(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [zoom]);

  if (images.length === 0) return null;

  const cols = images.length === 1 ? 1 : images.length === 2 ? 2 : 3;

  return (
    <>
      <div
        className="grid gap-1.5"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {images.map((name) => (
          <button
            key={name}
            onClick={() => setZoom(imageUrl(itemId, name))}
            className="aspect-square overflow-hidden rounded-lg bg-line/50 border border-line group"
          >
            <img
              src={imageUrl(itemId, name)}
              alt=""
              loading="lazy"
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            />
          </button>
        ))}
      </div>
      {zoom && (
        <div
          className="fixed inset-0 z-50 bg-black/80 grid place-items-center p-4 cursor-zoom-out"
          onClick={() => setZoom(null)}
        >
          <img
            src={zoom}
            alt=""
            className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
          />
          <button
            onClick={() => setZoom(null)}
            className="absolute top-4 right-4 w-9 h-9 rounded-full bg-white/10 text-white grid place-items-center hover:bg-white/20"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>
      )}
    </>
  );
}
