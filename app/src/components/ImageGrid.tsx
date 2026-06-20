import { Image } from "expo-image";
import { useState } from "react";
import { Modal, Pressable, StyleSheet, View } from "react-native";
import { radius } from "../theme";
import { api, mediaHeaders } from "../lib/api";

export function ImageGrid({ itemId, images }: { itemId: string; images: string[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!images?.length) return null;
  const headers = mediaHeaders();

  return (
    <View style={styles.grid}>
      {images.map((name) => {
        const uri = api.imageUrl(itemId, name);
        return (
          <Pressable key={name} style={styles.cell} onPress={() => setOpen(uri)}>
            <Image
              source={{ uri, headers }}
              style={styles.thumb}
              contentFit="cover"
              transition={150}
            />
          </Pressable>
        );
      })}

      <Modal visible={!!open} transparent animationType="fade" onRequestClose={() => setOpen(null)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(null)}>
          {open && (
            <Image
              source={{ uri: open, headers }}
              style={styles.full}
              contentFit="contain"
            />
          )}
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  cell: { width: "32%", aspectRatio: 1 },
  thumb: { width: "100%", height: "100%", borderRadius: radius.sm },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.92)", alignItems: "center", justifyContent: "center" },
  full: { width: "100%", height: "100%" },
});
