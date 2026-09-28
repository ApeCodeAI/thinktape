/**
 * Lightweight content renderer: paragraphs + clickable #tags, [[wikilinks]]
 * and bare URLs. Mirrors the web Phase-1 tokenizer (Hashtag/Wikilink). Full
 * markdown (bold/lists/code) is intentionally deferred to a later polish pass.
 */
import { Linking, StyleSheet, Text } from "react-native";
import { colors } from "../theme";

type Seg =
  | { kind: "text"; value: string }
  | { kind: "tag"; value: string }
  | { kind: "wikilink"; value: string }
  | { kind: "url"; value: string };

const TOKEN_RE =
  /\[\[([^\[\]]+)\]\]|(^|\s)#([0-9A-Za-z_一-鿿][0-9A-Za-z_一-鿿/]*)|(https?:\/\/[^\s]+)/g;

function tokenize(line: string): Seg[] {
  const out: Seg[] = [];
  let last = 0;
  TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(line)) !== null) {
    const start = m.index;
    if (m[1] !== undefined) {
      if (start > last) out.push({ kind: "text", value: line.slice(last, start) });
      const t = m[1].trim();
      if (t) out.push({ kind: "wikilink", value: t });
    } else if (m[3] !== undefined) {
      const lead = m[2] ?? "";
      const before = line.slice(last, start) + lead;
      if (before) out.push({ kind: "text", value: before });
      const tag = m[3].replace(/\/+$/, "");
      if (tag) out.push({ kind: "tag", value: tag });
    } else if (m[4] !== undefined) {
      if (start > last) out.push({ kind: "text", value: line.slice(last, start) });
      out.push({ kind: "url", value: m[4] });
    }
    last = start + m[0].length;
  }
  if (last < line.length) out.push({ kind: "text", value: line.slice(last) });
  return out;
}

interface Props {
  content: string;
  onTagPress?: (tag: string) => void;
  onWikilinkPress?: (target: string) => void;
}

export function RichText({ content, onTagPress, onWikilinkPress }: Props) {
  const lines = (content || "").split("\n");
  return (
    <Text style={styles.body}>
      {lines.map((line, li) => {
        const segs = tokenize(line);
        return (
          <Text key={li}>
            {segs.map((s, i) => {
              if (s.kind === "tag") {
                return (
                  <Text key={i} style={styles.tag} onPress={() => onTagPress?.(s.value)}>
                    #{s.value}
                  </Text>
                );
              }
              if (s.kind === "wikilink") {
                return (
                  <Text
                    key={i}
                    style={styles.link}
                    onPress={() => onWikilinkPress?.(s.value)}
                  >
                    {s.value}
                  </Text>
                );
              }
              if (s.kind === "url") {
                return (
                  <Text key={i} style={styles.link} onPress={() => Linking.openURL(s.value)}>
                    {s.value}
                  </Text>
                );
              }
              return <Text key={i}>{s.value}</Text>;
            })}
            {li < lines.length - 1 ? "\n" : ""}
          </Text>
        );
      })}
    </Text>
  );
}

const styles = StyleSheet.create({
  body: { fontSize: 17, lineHeight: 27, color: colors.fg },
  tag: { color: colors.accent, fontWeight: "600" },
  link: { color: colors.accent, textDecorationLine: "underline" },
});
