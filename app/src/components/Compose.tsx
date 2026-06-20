import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { api } from "../lib/api";
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

  const submit = async () => {
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
        <Pressable
          style={[styles.send, (!text.trim() || busy) && styles.sendOff]}
          onPress={submit}
          disabled={!text.trim() || busy}
        >
          {busy ? (
            <ActivityIndicator color={colors.accentOn} size="small" />
          ) : (
            <Text style={styles.sendText}>记录</Text>
          )}
        </Pressable>
      </View>
      {error && <Text style={styles.error}>{error}</Text>}
    </View>
  );
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
  send: { backgroundColor: colors.accent, borderRadius: radius.md, paddingHorizontal: 18, paddingVertical: 8, minWidth: 64, alignItems: "center" },
  sendOff: { opacity: 0.5 },
  sendText: { color: colors.accentOn, fontWeight: "600", fontSize: 14 },
  error: { color: colors.danger, fontSize: 13, marginTop: space(2) },
});
