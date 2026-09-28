// Browser camera/mic recording via getUserMedia + MediaRecorder.
// Uses raw DOM elements (this file only runs on web). Globals are cast to any
// so it typechecks without requiring the DOM lib in tsconfig.
import { useEffect, useRef, useState } from "react";

export const webRecordingSupported =
  typeof navigator !== "undefined" &&
  !!(navigator as any).mediaDevices?.getUserMedia &&
  typeof (globalThis as any).MediaRecorder !== "undefined";

interface Props {
  mode: "video" | "audio";
  onComplete: (blob: Blob, filename: string) => void;
  onCancel: () => void;
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function WebRecorder({ mode, onComplete, onCancel }: Props) {
  const videoRef = useRef<any>(null);
  const streamRef = useRef<any>(null);
  const recRef = useRef<any>(null);
  const chunksRef = useRef<any[]>([]);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const constraints = mode === "video" ? { video: true, audio: true } : { audio: true };
        const stream = await (navigator as any).mediaDevices.getUserMedia(constraints);
        if (!active) {
          stream.getTracks().forEach((t: any) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (mode === "video" && videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play?.().catch(() => {});
        }
      } catch (e: any) {
        setError("无法访问摄像头/麦克风：" + String(e?.message ?? e));
      }
    })();
    return () => {
      active = false;
      stopStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  useEffect(() => {
    if (!recording) return;
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [recording]);

  const stopStream = () => {
    try {
      if (recRef.current && recRef.current.state === "recording") recRef.current.stop();
    } catch {}
    streamRef.current?.getTracks?.().forEach((t: any) => t.stop());
    streamRef.current = null;
  };

  const pickMime = (): string => {
    const MR: any = (globalThis as any).MediaRecorder;
    const candidates =
      mode === "video"
        ? ["video/webm;codecs=vp9,opus", "video/webm", "video/mp4"]
        : ["audio/webm", "audio/ogg", "audio/mp4"];
    for (const c of candidates) if (MR?.isTypeSupported?.(c)) return c;
    return mode === "video" ? "video/webm" : "audio/webm";
  };

  const start = () => {
    if (!streamRef.current) return;
    chunksRef.current = [];
    const mime = pickMime();
    const MR: any = (globalThis as any).MediaRecorder;
    const rec = new MR(streamRef.current, { mimeType: mime });
    rec.ondataavailable = (e: any) => {
      if (e.data && e.data.size) chunksRef.current.push(e.data);
    };
    rec.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mime });
      const ext = mime.includes("mp4") ? (mode === "video" ? "mp4" : "m4a") : "webm";
      stopStream();
      onComplete(blob, `${mode === "video" ? "video" : "memo"}.${ext}`);
    };
    recRef.current = rec;
    rec.start();
    setRecording(true);
    setElapsed(0);
  };

  const stop = () => {
    try {
      recRef.current?.stop();
    } catch {}
    setRecording(false);
  };

  const overlay: any = {
    position: "fixed",
    inset: 0,
    background: "rgba(20,16,12,0.6)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  };
  const panel: any = {
    background: "#fffdf8",
    borderRadius: 20,
    padding: 20,
    width: "min(520px, 92vw)",
    boxShadow: "0 20px 52px rgba(32,25,20,0.25)",
  };
  const btn = (bg: string, color: string): any => ({
    background: bg,
    color,
    border: "none",
    borderRadius: 12,
    padding: "10px 18px",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer",
  });

  return (
    <div style={overlay}>
      <div style={panel}>
        {error ? (
          <div style={{ color: "#b33a3a", marginBottom: 16 }}>{error}</div>
        ) : mode === "video" ? (
          <video
            ref={videoRef}
            muted
            playsInline
            style={{ width: "100%", borderRadius: 12, background: "#000", maxHeight: "60vh" }}
          />
        ) : (
          <div style={{ textAlign: "center", padding: 28, fontSize: 18, color: "#201914" }}>
            {recording ? `录音中 ${fmt(elapsed)}` : "准备录音"}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginTop: 14, justifyContent: "center" }}>
          {!error &&
            (!recording ? (
              <button style={btn("#9b5b32", "#fff")} onClick={start}>
                ● 开始录制
              </button>
            ) : (
              <button style={btn("#b33a3a", "#fff")} onClick={stop}>
                ■ 停止并发送 {fmt(elapsed)}
              </button>
            ))}
          <button
            style={btn("transparent", "#7a6d63")}
            onClick={() => {
              stopStream();
              onCancel();
            }}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
