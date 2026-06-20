import { Pressable, StyleSheet, Text, View } from "react-native";
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
}

export function ItemCard({ item, onTagPress, onWikilinkPress }: Props) {
  const meta = typeMeta[item.type] ?? typeMeta.thought;
  const transcribing = item.content.startsWith("[转写");
  const body = item.bookmark_url
    ? item.content.replace(item.bookmark_url, "").trim()
    : item.content;

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.mark}>{meta.mark}</Text>
        <Text style={styles.time}>{formatTime(item.created_at)}</Text>
        <Text style={styles.dot}>·</Text>
        <Text style={styles.label}>{meta.label}</Text>
      </View>

      {!!body && (
        <View style={styles.body}>
          {transcribing ? (
            <Text style={styles.transcribing}>{body}</Text>
          ) : (
            <RichText content={body} onTagPress={onTagPress} onWikilinkPress={onWikilinkPress} />
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
  body: {},
  transcribing: { color: colors.muted, fontStyle: "italic", fontSize: 16 },
  bookmark: { color: colors.accent, fontSize: 14, marginTop: space(2), textDecorationLine: "underline" },
  media: { marginTop: space(3) },
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
