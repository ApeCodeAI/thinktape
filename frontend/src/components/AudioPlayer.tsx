import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface Props {
  src: string;
}

function fmt(sec: number) {
  if (!Number.isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function AudioPlayer({ src }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onTime = () => {
      setCurrent(a.currentTime);
      setProgress(a.duration ? a.currentTime / a.duration : 0);
    };
    const onLoaded = () => setDuration(a.duration);
    const onEnded = () => {
      setPlaying(false);
      setProgress(0);
      setCurrent(0);
    };
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("loadedmetadata", onLoaded);
    a.addEventListener("ended", onEnded);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("loadedmetadata", onLoaded);
      a.removeEventListener("ended", onEnded);
    };
  }, []);

  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (playing) {
      a.pause();
      setPlaying(false);
    } else {
      a.play();
      setPlaying(true);
    }
  };

  const onSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const a = audioRef.current;
    if (!a || !a.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    a.currentTime = Math.max(0, Math.min(a.duration, a.duration * ratio));
  };

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-accent-soft/60 border border-accent/15">
      <audio ref={audioRef} src={src} preload="metadata" />
      <button
        onClick={toggle}
        className="w-9 h-9 rounded-full bg-accent text-white grid place-items-center shadow-sm hover:bg-amber-600 transition-colors shrink-0"
        aria-label={playing ? "暂停" : "播放"}
      >
        {playing ? <Pause size={16} /> : <Play size={16} className="ml-0.5" />}
      </button>
      <div className="flex-1 min-w-0">
        <div
          className="h-1.5 bg-accent/15 rounded-full cursor-pointer overflow-hidden"
          onClick={onSeek}
        >
          <div
            className="h-full bg-accent rounded-full transition-all"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
        <div className="text-xs text-muted mt-1 tabular-nums flex justify-between">
          <span>{fmt(current)}</span>
          <span>{fmt(duration)}</span>
        </div>
      </div>
    </div>
  );
}
