import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { api, type Item } from "../lib/api";
import { colors, radius, shadowRaised, space, typeMeta } from "../theme";
import { AudioPlayer } from "./AudioPlayer";
import { ImageGrid } from "./ImageGrid";
import { RichText } from "./RichText";
import { VideoPlayer } from "./VideoPlayer";

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    if (sameDay) return `今天 ${hh}:${mm}`;
    return `${d.getMonth() + 1}月${d.getDate()}日 ${hh}:${mm}`;
  } catch {
    return iso;
  }
}

interface Props {
  item: Item;
  onTagPress?: (tag: string) => void;
  onWikilinkPress?: (target: string) => void;
  onChanged?: () => void;
}

export function ItemCard({ item, onTagPress, onWikilinkPress, onChanged }: Props) {
  const meta = typeMeta[item.type] ?? typeMeta.thought;
  const transcribing = item.content.startsWith("[转写");
  const body = item.bookmark_url
    ? item.content.replace(item.bookmark_url, "").trim()
    : item.content;

  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.content);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(item.content);
  }, [item.content, editing]);

  const saveEdit = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.patch(item.id, { content: draft });
      setEditing(false);
      setMenuOpen(false);
      onChanged?.();
    } catch {
      /* keep editor open on failure */
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.remove(item.id);
      onChanged?.();
    } catch {
      setBusy(false);
      setConfirmDelete(false);
    }
  };

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.mark}>{meta.mark}</Text>
        <Text style={styles.time}>{formatTime(item.created_at)}</Text>
        <Text style={styles.dot}>·</Text>
        <Text style={styles.label}>{meta.label}</Text>
        <View style={styles.spacer} />
        {!editing && (
          <Pressable
            hitSlop={8}
            onPress={() => {
              setMenuOpen((v) => !v);
              setConfirmDelete(false);
            }}
          >
            <Text style={styles.more}>⋯</Text>
          </Pressable>
        )}
      </View>

      {menuOpen && !editing && (
        <View style={styles.menu}>
          {confirmDelete ? (
            <>
              <Text style={styles.confirmText}>确认删除？</Text>
              <Pressable style={styles.menuBtn} onPress={doDelete} disabled={busy}>
                <Text style={styles.menuDanger}>{busy ? "删除中…" : "删除"}</Text>
              </Pressable>
              <Pressable style={styles.menuBtn} onPress={() => setConfirmDelete(false)}>
                <Text style={styles.menuText}>取消</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Pressable
                style={styles.menuBtn}
                onPress={() => {
                  setEditing(true);
                  setMenuOpen(false);
                }}
              >
                <Text style={styles.menuText}>编辑</Text>
              </Pressable>
              <Pressable style={styles.menuBtn} onPress={() => setConfirmDelete(true)}>
                <Text style={styles.menuDanger}>删除</Text>
              </Pressable>
            </>
          )}
        </View>
      )}

      {editing ? (
        <View>
          <TextInput
            style={styles.editor}
            value={draft}
            onChangeText={setDraft}
            multiline
            autoFocus
          />
          <View style={styles.editActions}>
            <Pressable style={styles.cancelBtn} onPress={() => setEditing(false)}>
              <Text style={styles.menuText}>取消</Text>
            </Pressable>
            <Pressable style={styles.saveBtn} onPress={saveEdit} disabled={busy}>
              {busy ? (
                <ActivityIndicator color={colors.accentOn} size="small" />
              ) : (
                <Text style={styles.saveText}>保存</Text>
              )}
            </Pressable>
          </View>
        </View>
      ) : (
        <>
          {!!body && (
            <View style={styles.body}>
              {transcribing ? (
                <Text style={styles.transcribing}>{body}</Text>
              ) : (
                <RichText
                  content={body}
                  onTagPress={onTagPress}
                  onWikilinkPress={onWikilinkPress}
                />
              )}
            </View>
          )}

          {!!item.bookmark_url && (
            <Text style={styles.bookmark} onPress={() => onWikilinkPress?.(item.bookmark_url!)}>
              {item.bookmark_url}
            </Text>
          )}

          {item.has_images && item.images.length > 0 && (
            <View style={styles.media}>
              <ImageGrid itemId={item.id} images={item.images} />
            </View>
          )}

          {item.has_audio && (
            <View style={styles.media}>
              <AudioPlayer uri={api.audioUrl(item.id)} />
            </View>
          )}

          {item.has_video && (
            <View style={styles.media}>
              <VideoPlayer uri={api.videoUrl(item.id)} />
            </View>
          )}

          {item.tags.length > 0 && (
            <View style={styles.tags}>
              {item.tags.map((t) => (
                <Pressable key={t} style={styles.tagPill} onPress={() => onTagPress?.(t)}>
                  <Text style={styles.tagText}>#{t}</Text>
                </Pressable>
              ))}
            </View>
          )}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    paddingHorizontal: space(5),
    paddingVertical: space(4),
    marginBottom: space(3),
    ...shadowRaised,
  },
  header: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: space(3) },
  mark: { color: colors.meta, fontSize: 14 },
  time: { color: colors.muted, fontSize: 12, fontStyle: "italic" },
  dot: { color: colors.border, fontSize: 12 },
  label: { color: colors.muted, fontSize: 12 },
  spacer: { flex: 1 },
  more: { color: colors.muted, fontSize: 20, lineHeight: 20 },
  menu: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: space(3),
    paddingBottom: space(2),
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSoft,
  },
  menuBtn: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.sm },
  menuText: { color: colors.fg2, fontSize: 13 },
  menuDanger: { color: colors.danger, fontSize: 13 },
  confirmText: { color: colors.muted, fontSize: 13, flex: 1 },
  body: {},
  transcribing: { color: colors.muted, fontStyle: "italic", fontSize: 16 },
  bookmark: { color: colors.accent, fontSize: 14, marginTop: space(2), textDecorationLine: "underline" },
  media: { marginTop: space(3) },
  editor: {
    fontSize: 17,
    lineHeight: 25,
    color: colors.fg,
    minHeight: 80,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: space(3),
    textAlignVertical: "top",
  },
  editActions: { flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: space(3) },
  cancelBtn: { paddingHorizontal: 16, paddingVertical: 8, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  saveBtn: { backgroundColor: colors.accent, borderRadius: radius.md, paddingHorizontal: 18, paddingVertical: 8, minWidth: 64, alignItems: "center" },
  saveText: { color: colors.accentOn, fontWeight: "600" },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: space(4), paddingTop: space(3), borderTopWidth: 1, borderTopColor: colors.borderSoft },
  tagPill: {
    backgroundColor: colors.accentSoft,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderWidth: 1,
    borderColor: "rgba(155,91,50,0.12)",
  },
  tagText: { color: colors.meta, fontSize: 12 },
});
