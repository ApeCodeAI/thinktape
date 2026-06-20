import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { api } from "@/lib/api";
import { getConn, saveConn } from "@/lib/config";
import { colors, radius, space } from "@/theme";

export default function Settings() {
  const router = useRouter();
  const qc = useQueryClient();
  const initial = getConn();
  const [baseUrl, setBaseUrl] = useState(initial.baseUrl);
  const [deviceKey, setDeviceKey] = useState(initial.deviceKey);
  const [status, setStatus] = useState<string | null>(null);
  const [minted, setMinted] = useState<string | null>(null);

  const apply = async () => {
    await saveConn({ baseUrl, deviceKey });
  };

  const test = async () => {
    setStatus("测试中…");
    await apply();
    try {
      await api.health();
      setStatus("✓ 连接成功");
    } catch (e: any) {
      setStatus(`✗ ${String(e?.message ?? e)}`);
    }
  };

  const save = async () => {
    await apply();
    qc.invalidateQueries();
    router.back();
  };

  const pair = async () => {
    setStatus("正在生成设备 Key…");
    await apply();
    try {
      const r = await api.pair("device");
      setMinted(r.key);
      setStatus("✓ 已生成新设备 Key（见下方）");
    } catch (e: any) {
      setStatus(`✗ 生成失败：${String(e?.message ?? e)}`);
    }
  };

  return (
    <ScrollView style={styles.flex} contentContainerStyle={styles.container}>
      <Text style={styles.label}>Daemon 地址</Text>
      <TextInput
        style={styles.input}
        value={baseUrl}
        onChangeText={setBaseUrl}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        placeholder={Platform.OS === "web" ? "(留空 = 同源)" : "http://192.168.1.10:8080"}
        placeholderTextColor={colors.muted}
      />
      <Text style={styles.hint}>
        手机与电脑在同一 Wi-Fi 时，填电脑局域网地址，例如 http://192.168.x.x:8080
      </Text>

      <Text style={styles.label}>设备 Key</Text>
      <TextInput
        style={styles.input}
        value={deviceKey}
        onChangeText={setDeviceKey}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder="在电脑上运行 thinktape pair 获取"
        placeholderTextColor={colors.muted}
      />
      <Text style={styles.hint}>
        本机访问无需 Key；远程设备需先在电脑上 `thinktape pair` 生成并填入这里。
      </Text>

      <View style={styles.row}>
        <Pressable style={styles.primary} onPress={save}>
          <Text style={styles.primaryText}>保存</Text>
        </Pressable>
        <Pressable style={styles.secondary} onPress={test}>
          <Text style={styles.secondaryText}>测试连接</Text>
        </Pressable>
      </View>

      <Pressable style={styles.pair} onPress={pair}>
        <Text style={styles.secondaryText}>在受信任的机器上生成新设备 Key</Text>
      </Pressable>

      {status && <Text style={styles.status}>{status}</Text>}
      {minted && (
        <View style={styles.minted}>
          <Text style={styles.mintedLabel}>新设备 Key（填到手机端的「设备 Key」）：</Text>
          <Text selectable style={styles.mintedKey}>
            {minted}
          </Text>
          <Pressable onPress={() => setDeviceKey(minted)}>
            <Text style={styles.useKey}>用在本机 →</Text>
          </Pressable>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  container: { padding: space(5), maxWidth: 640, width: "100%", alignSelf: "center", gap: space(2) },
  label: { fontSize: 13, fontWeight: "600", color: colors.fg2, marginTop: space(3) },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    color: colors.fg,
  },
  hint: { fontSize: 12, color: colors.muted, lineHeight: 18 },
  row: { flexDirection: "row", gap: 10, marginTop: space(4) },
  primary: { flex: 1, backgroundColor: colors.accent, borderRadius: radius.md, paddingVertical: 11, alignItems: "center" },
  primaryText: { color: colors.accentOn, fontWeight: "600", fontSize: 15 },
  secondary: { flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingVertical: 11, alignItems: "center" },
  secondaryText: { color: colors.meta, fontWeight: "600", fontSize: 14 },
  pair: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingVertical: 11, alignItems: "center", marginTop: space(2) },
  status: { marginTop: space(3), fontSize: 14, color: colors.fg2 },
  minted: { marginTop: space(3), padding: space(4), backgroundColor: colors.accentSoft, borderRadius: radius.md },
  mintedLabel: { fontSize: 12, color: colors.meta, marginBottom: 6 },
  mintedKey: { fontSize: 13, color: colors.fg, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" },
  useKey: { marginTop: 8, color: colors.accent, fontWeight: "600" },
});
