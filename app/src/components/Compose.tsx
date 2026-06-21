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
import { api, type UploadFilePart } from "../lib/api";
import { colors, radius, space } from "../theme";

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
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const canRecord = Platform.OS !== "web";

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

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
      setText("");
      setType("thought");
      onCreated();
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const startRecording = async () => {
    try {
      const perm = await AudioModule.requestRecordingPermissionsAsync();
      if (!perm.granted) {
        setError("需要麦克风权限才能录音");
        return;
      }
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
    setBusy(true);
    setError(null);
    try {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) throw new Error("录音文件为空");
      await api.upload({
        content: text.trim(),
        audio: { uri, name: "memo.m4a", mimeType: "audio/m4a" },
      });
      setText("");
      onCreated();
    } catch (e: any) {
      setError(`上传语音失败：${String(e?.message ?? e)}`);
    } finally {
      setBusy(false);
    }
  };

  const pickImages = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        setError("需要相册权限才能选图");
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        allowsMultipleSelection: true,
        quality: 0.8,
      });
      if (res.canceled || !res.assets?.length) return;
      setBusy(true);
      setError(null);
      const images: UploadFilePart[] = res.assets.map((a, i) => ({
        uri: a.uri,
        name: a.fileName ?? `image-${i + 1}.jpg`,
        mimeType: a.mimeType ?? "image/jpeg",
        file: (a as any).file,
      }));
      await api.upload({ content: text.trim(), type, images });
      setText("");
      onCreated();
    } catch (e: any) {
      setError(`上传图片失败：${String(e?.message ?? e)}`);
    } finally {
      setBusy(false);
    }
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
      <View style={styles.row}>
        <View style={styles.types}>
          {TYPES.map((t) => (
            <Pressable
              key={t.key}
              onPress={() => setType(t.key)}
              style={[styles.typePill, type === t.key && styles.typePillOn]}
            >
              <Text style={[styles.typeText, type === t.key && styles.typeTextOn]}>
                {t.label}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.actions}>
          <Pressable style={styles.iconBtn} onPress={pickImages} disabled={busy}>
            <Text style={styles.iconText}>📷</Text>
          </Pressable>
          {canRecord && (
            <Pressable style={styles.iconBtn} onPress={startRecording} disabled={busy}>
              <Text style={styles.iconText}>🎤</Text>
            </Pressable>
          )}
          <Pressable
            style={[styles.send, (!text.trim() || busy) && styles.sendOff]}
            onPress={submitText}
            disabled={!text.trim() || busy}
          >
            {busy ? (
              <ActivityIndicator color={colors.accentOn} size="small" />
            ) : (
              <Text style={styles.sendText}>记录</Text>
            )}
          </Pressable>
        </View>
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
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: space(3) },
  types: { flexDirection: "row", gap: 6 },
  typePill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border },
  typePillOn: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  typeText: { fontSize: 12, color: colors.muted },
  typeTextOn: { color: colors.meta },
  actions: { flexDirection: "row", alignItems: "center", gap: 8 },
  iconBtn: { width: 38, height: 38, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  iconText: { fontSize: 17 },
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
