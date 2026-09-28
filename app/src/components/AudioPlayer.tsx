import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors, radius } from "../theme";
import { mediaHeaders } from "../lib/api";

function fmt(sec: number): string {
  if (!sec || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function AudioPlayer({ uri }: { uri: string }) {
  const player = useAudioPlayer({ uri, headers: mediaHeaders() });
  const status = useAudioPlayerStatus(player);
  const playing = status?.playing ?? false;

  return (
    <View style={styles.wrap}>
      <Pressable
        style={styles.btn}
        onPress={() => {
          if (playing) player.pause();
          else {
            if ((status?.currentTime ?? 0) >= (status?.duration ?? 0) && status?.duration) {
              player.seekTo(0);
            }
            player.play();
          }
        }}
      >
        <Text style={styles.icon}>{playing ? "❚❚" : "▶"}</Text>
      </Pressable>
      <Text style={styles.time}>
        {fmt(status?.currentTime ?? 0)} / {fmt(status?.duration ?? 0)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.accentSoft,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  btn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  icon: { color: colors.accentOn, fontSize: 14 },
  time: { color: colors.meta, fontSize: 13, fontVariant: ["tabular-nums"] },
});
