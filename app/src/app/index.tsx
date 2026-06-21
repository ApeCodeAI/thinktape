import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Compose } from "@/components/Compose";
import { ItemCard } from "@/components/ItemCard";
import { api } from "@/lib/api";
import { colors, radius, space } from "@/theme";

function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable onPress={onPress} style={[styles.chip, active && styles.chipOn]}>
      <Text style={[styles.chipText, active && styles.chipTextOn]}>{label}</Text>
    </Pressable>
  );
}

export default function Feed() {
  const qc = useQueryClient();
  const [tag, setTag] = useState<string | undefined>(undefined);
  const [q, setQ] = useState("");
  const [submittedQ, setSubmittedQ] = useState("");

  const itemsQ = useQuery({
    queryKey: ["items", { tag, q: submittedQ }],
    queryFn: () => api.list({ tag, q: submittedQ || undefined, limit: 50 }),
  });
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: () => api.tags() });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
  };

  const items = itemsQ.data?.items ?? [];
  const allTags = tagsQ.data?.tags ?? [];

  return (
    <FlatList
      style={styles.flex}
      data={items}
      keyExtractor={(i) => i.id}
      contentContainerStyle={styles.list}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={itemsQ.isFetching && !itemsQ.isLoading}
          onRefresh={refresh}
          tintColor={colors.accent}
        />
      }
      ListHeaderComponent={
        <View>
          <View style={styles.searchRow}>
            <TextInput
              style={styles.search}
              value={q}
              onChangeText={setQ}
              onSubmitEditing={() => setSubmittedQ(q.trim())}
              placeholder="搜索…"
              placeholderTextColor={colors.muted}
              returnKeyType="search"
            />
            <Link href="/settings" asChild>
              <Pressable style={styles.gear} hitSlop={8}>
                <Text style={styles.gearText}>⚙</Text>
              </Pressable>
            </Link>
          </View>

          {(allTags.length > 0 || tag) && (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.chips}
            >
              {tag && <Chip label={`#${tag} ✕`} active onPress={() => setTag(undefined)} />}
              {allTags
                .filter((t) => t !== tag)
                .slice(0, 40)
                .map((t) => (
                  <Chip key={t} label={`#${t}`} onPress={() => setTag(t)} />
                ))}
            </ScrollView>
          )}

          <Compose onCreated={refresh} />
        </View>
      }
      renderItem={({ item }) => (
        <ItemCard
          item={item}
          onTagPress={(t) => setTag(t)}
          onWikilinkPress={(target) => {
            setQ(target);
            setSubmittedQ(target);
          }}
          onChanged={refresh}
        />
      )}
      ListEmptyComponent={
        itemsQ.isLoading ? (
          <ActivityIndicator color={colors.accent} style={{ marginTop: 48 }} />
        ) : itemsQ.isError ? (
          <View style={styles.errorBox}>
            <Text style={styles.errorTitle}>连接不上 daemon</Text>
            <Text style={styles.errorMsg}>{String((itemsQ.error as Error)?.message ?? itemsQ.error)}</Text>
            <View style={styles.errorActions}>
              <Pressable style={styles.retryBtn} onPress={() => itemsQ.refetch()}>
                <Text style={styles.retryText}>重试</Text>
              </Pressable>
              <Link href="/settings" asChild>
                <Pressable style={styles.linkBtn}>
                  <Text style={styles.linkText}>打开设置</Text>
                </Pressable>
              </Link>
            </View>
          </View>
        ) : (
          <Text style={styles.empty}>还没有记录，写下第一条吧。</Text>
        )
      }
    />
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  list: { padding: space(4), maxWidth: 720, width: "100%", alignSelf: "center" },
  searchRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: space(3) },
  search: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 9,
    fontSize: 15,
    color: colors.fg,
  },
  gear: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    alignItems: "center",
    justifyContent: "center",
  },
  gearText: { fontSize: 18, color: colors.meta },
  chips: { gap: 6, paddingBottom: space(3) },
  chip: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  chipOn: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { fontSize: 13, color: colors.muted },
  chipTextOn: { color: colors.accentOn },
  empty: { textAlign: "center", color: colors.muted, marginTop: 48, fontSize: 15 },
  errorBox: {
    marginTop: 40,
    padding: space(5),
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSoft,
  },
  errorTitle: { fontSize: 16, fontWeight: "600", color: colors.fg, marginBottom: 6 },
  errorMsg: { fontSize: 13, color: colors.muted, marginBottom: space(4) },
  errorActions: { flexDirection: "row", gap: 10 },
  retryBtn: { backgroundColor: colors.accent, borderRadius: radius.md, paddingHorizontal: 16, paddingVertical: 8 },
  retryText: { color: colors.accentOn, fontWeight: "600" },
  linkBtn: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 16, paddingVertical: 8 },
  linkText: { color: colors.meta, fontWeight: "600" },
});
