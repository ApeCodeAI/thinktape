// Native stub — browser recording (getUserMedia/MediaRecorder) is web-only.
// On native we record via expo-audio / expo-image-picker instead.
export const webRecordingSupported = false;

export function WebRecorder(_props: {
  mode: "video" | "audio";
  onComplete: (blob: Blob, filename: string) => void;
  onCancel: () => void;
}) {
  return null;
}
