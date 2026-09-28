import { useVideoPlayer, VideoView } from "expo-video";
import { StyleSheet } from "react-native";
import { radius } from "../theme";
import { mediaHeaders } from "../lib/api";

export function VideoPlayer({ uri }: { uri: string }) {
  const player = useVideoPlayer({ uri, headers: mediaHeaders() }, (p) => {
    p.loop = false;
  });
  return <VideoView style={styles.video} player={player} nativeControls contentFit="contain" />;
}

const styles = StyleSheet.create({
  video: {
    width: "100%",
    aspectRatio: 16 / 9,
    backgroundColor: "#000",
    borderRadius: radius.sm,
  },
});
