import {
  AudioModule,
  RecordingPresets,
  setAudioModeAsync,
  useAudioRecorder,
} from "expo-audio";
import * as ImagePicker from "expo-image-picker";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { api, type UploadFilePart, type UploadParts } from "../lib/api";
import { colors, radius, space } from "../theme";
import { WebRecorder, webRecordingSupported } from "./WebRecorder";

const TYPES: { key: string; label: string }[] = [
  { key: "thought", label: "想法" },
  { key: "bookmark", label: "收藏" },
  { key: "note", label: "笔记" },
];

const URL_RE = /https?:\/\/[^\s]+/;

export function Compose({ onCreated }: { onCreated: () => void }) {
  const [text, setText] = useState("");
  const [type, setType] = useState("thought");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [webMode, setWebMode] = useState<"video" | "audio" | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const native = Platform.OS !== "web";

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const reset = () => {
    setText("");
    setType("thought");
  };

  const runUpload = async (parts: UploadParts, label: string) => {
    setBusy(true);
    setError(null);
    try {
      if (native) {
        // expo-file-system uploadAsync (one file → one item); avoids RN FormData.
        const meta = { content: text.trim(), type };
        if (parts.audio) {
          await api.uploadFileNative(parts.audio.uri, "audio", parts.audio.mimeType ?? "audio/m4a", meta);
        }
        if (parts.video) {
          await api.uploadFileNative(parts.video.uri, "video", parts.video.mimeType ?? "video/mp4", meta);
        }
        for (const img of parts.images ?? []) {
          await api.uploadFileNative(img.uri, "images", img.mimeType ?? "image/jpeg", meta);
        }
      } else {
        await api.upload({ content: text.trim(), type, ...parts });
      }
      reset();
      onCreated();
    } catch (e: any) {
      setError(`${label}失败：${String(e?.message ?? e)}`);
    } finally {
      setBusy(false);
    }
  };

  const submitText = async () => {
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    setError(null);
    try {
      const urlMatch = content.match(URL_RE);
      const isBookmark = type === "bookmark" || (type === "thought" && !!urlMatch);
      await api.create({
        content,
        type: isBookmark ? "bookmark" : type,
        bookmark_url: isBookmark && urlMatch ? urlMatch[0] : null,
      });
      reset();
      onCreated();
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  // ---- audio ----
  const startRecording = async () => {
    try {
      const perm = await AudioModule.requestRecordingPermissionsAsync();
      if (!perm.granted) return setError("需要麦克风权限才能录音");
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    } catch (e: any) {
      setError(`录音启动失败：${String(e?.message ?? e)}`);
    }
  };

  const stopAndUpload = async () => {
    if (timerRef.current) clearInterval(timerRef.current);
    setRecording(false);
    try {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) throw new Error("录音文件为空");
      await runUpload({ audio: { uri, name: "memo.m4a", mimeType: "audio/m4a" } }, "上传语音");
    } catch (e: any) {
      setError(`上传语音失败：${String(e?.message ?? e)}`);
    }
  };

  // ---- images / video ----
  const assetToPart = (a: ImagePicker.ImagePickerAsset, i: number, fallbackExt: string): UploadFilePart => ({
    uri: a.uri,
    name: a.fileName ?? `media-${i + 1}.${fallbackExt}`,
    mimeType: a.mimeType ?? (fallbackExt === "mp4" ? "video/mp4" : "image/jpeg"),
    file: (a as any).file,
  });

  const pickImages = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return setError("需要相册权限才能选图");
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images", "videos"],
      allowsMultipleSelection: true,
      quality: 0.8,
    });
    if (res.canceled || !res.assets?.length) return;
    const images: UploadFilePart[] = [];
    let video: UploadFilePart | null = null;
    res.assets.forEach((a, i) => {
      if (a.type === "video") video = assetToPart(a, i, "mp4");
      else images.push(assetToPart(a, i, "jpg"));
    });
    await runUpload({ images: images.length ? images : undefined, video }, "上传");
  };

  const takePhoto = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) return setError("需要相机权限才能拍照");
    const res = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.8 });
    if (res.canceled || !res.assets?.length) return;
    await runUpload({ images: [assetToPart(res.assets[0], 0, "jpg")] }, "上传照片");
  };

  const recordVideo = async () => {
    const cam = await ImagePicker.requestCameraPermissionsAsync();
    if (!cam.granted) return setError("需要相机权限才能录像");
    const res = await ImagePicker.launchCameraAsync({
      mediaTypes: ["videos"],
      videoMaxDuration: 180,
      quality: 0.8,
    });
    if (res.canceled || !res.assets?.length) return;
    await runUpload({ video: assetToPart(res.assets[0], 0, "mp4") }, "上传视频");
  };

  if (recording) {
    return (
      <View style={styles.wrap}>
        <View style={styles.recRow}>
          <View style={styles.recDot} />
          <Text style={styles.recText}>录音中 {fmt(elapsed)}</Text>
          <Pressable style={styles.stop} onPress={stopAndUpload}>
            <Text style={styles.stopText}>停止并保存</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  const IconBtn = ({ label, onPress }: { label: string; onPress: () => void }) => (
    <Pressable style={styles.iconBtn} onPress={onPress} disabled={busy}>
      <Text style={styles.iconText}>{label}</Text>
    </Pressable>
  );

  return (
    <View style={styles.wrap}>
      <TextInput
        style={styles.input}
        value={text}
        onChangeText={setText}
        placeholder="写点什么… 用 #标签 归类"
        placeholderTextColor={colors.muted}
        multiline
      />

      <View style={styles.toolbar}>
        <IconBtn label="📷" onPress={pickImages} />
        {native ? (
          <>
            <IconBtn label="📸" onPress={takePhoto} />
            <IconBtn label="🎬" onPress={recordVideo} />
            <IconBtn label="🎤" onPress={startRecording} />
          </>
        ) : (
          webRecordingSupported && (
            <>
              <IconBtn label="🎬" onPress={() => setWebMode("video")} />
              <IconBtn label="🎤" onPress={() => setWebMode("audio")} />
            </>
          )
        )}
        {busy && <ActivityIndicator color={colors.accent} size="small" style={{ marginLeft: 4 }} />}
      </View>

      {webMode && (
        <WebRecorder
          mode={webMode}
          onComplete={(blob, filename) => {
            const m = webMode;
            setWebMode(null);
            const part: UploadFilePart = { uri: "", name: filename, mimeType: blob.type, file: blob };
            if (m === "video") runUpload({ video: part }, "上传视频");
            else runUpload({ audio: part }, "上传语音");
          }}
          onCancel={() => setWebMode(null)}
        />
      )}

      <View style={styles.row}>
        <View style={styles.types}>
          {TYPES.map((t) => (
            <Pressable
              key={t.key}
              onPress={() => setType(t.key)}
              style={[styles.typePill, type === t.key && styles.typePillOn]}
            >
              <Text style={[styles.typeText, type === t.key && styles.typeTextOn]}>{t.label}</Text>
            </Pressable>
          ))}
        </View>
        <Pressable
          style={[styles.send, (!text.trim() || busy) && styles.sendOff]}
          onPress={submitText}
          disabled={!text.trim() || busy}
        >
          <Text style={styles.sendText}>记录</Text>
        </Pressable>
      </View>

      {error && <Text style={styles.error}>{error}</Text>}
    </View>
  );
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    padding: space(4),
    marginBottom: space(4),
  },
  input: { fontSize: 17, lineHeight: 25, color: colors.fg, minHeight: 48, textAlignVertical: "top" },
  toolbar: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: space(3) },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: space(3) },
  types: { flexDirection: "row", gap: 6 },
  typePill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border },
  typePillOn: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  typeText: { fontSize: 12, color: colors.muted },
  typeTextOn: { color: colors.meta },
  iconBtn: { width: 40, height: 40, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  iconText: { fontSize: 18 },
  send: { backgroundColor: colors.accent, borderRadius: radius.md, paddingHorizontal: 18, paddingVertical: 9, minWidth: 64, alignItems: "center" },
  sendOff: { opacity: 0.5 },
  sendText: { color: colors.accentOn, fontWeight: "600", fontSize: 14 },
  error: { color: colors.danger, fontSize: 13, marginTop: space(2) },
  recRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  recDot: { width: 12, height: 12, borderRadius: 6, backgroundColor: colors.danger },
  recText: { flex: 1, color: colors.fg, fontSize: 16, fontVariant: ["tabular-nums"] },
  stop: { backgroundColor: colors.danger, borderRadius: radius.md, paddingHorizontal: 16, paddingVertical: 9 },
  stopText: { color: "#fff", fontWeight: "600" },
});
