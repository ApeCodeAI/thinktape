/**
 * Connection config: daemon base URL + device key.
 * Web persists to localStorage; native to expo-secure-store.
 */
import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

const URL_KEY = "thinktape.baseUrl";
const DEVICE_KEY = "thinktape.deviceKey";

export type Conn = { baseUrl: string; deviceKey: string };

let cache: Conn = { baseUrl: "", deviceKey: "" };
let loaded = false;

async function getItem(k: string): Promise<string | null> {
  if (Platform.OS === "web") {
    try {
      return globalThis.localStorage?.getItem(k) ?? null;
    } catch {
      return null;
    }
  }
  return SecureStore.getItemAsync(k);
}

async function setItem(k: string, v: string): Promise<void> {
  if (Platform.OS === "web") {
    try {
      globalThis.localStorage?.setItem(k, v);
    } catch {
      /* ignore */
    }
    return;
  }
  await SecureStore.setItemAsync(k, v);
}

export async function loadConn(): Promise<Conn> {
  const [baseUrl, deviceKey] = await Promise.all([getItem(URL_KEY), getItem(DEVICE_KEY)]);
  cache = { baseUrl: baseUrl ?? "", deviceKey: deviceKey ?? "" };
  loaded = true;
  return cache;
}

export async function saveConn(next: Conn): Promise<void> {
  cache = { baseUrl: next.baseUrl.trim().replace(/\/+$/, ""), deviceKey: next.deviceKey.trim() };
  await Promise.all([setItem(URL_KEY, cache.baseUrl), setItem(DEVICE_KEY, cache.deviceKey)]);
}

/** Synchronous best-effort accessor (after loadConn has run once). */
export function getConn(): Conn {
  return cache;
}

export function isLoaded(): boolean {
  return loaded;
}

/** On web, an empty baseUrl means "same origin" and is valid. Native needs a URL. */
export function needsSetup(): boolean {
  if (Platform.OS === "web") return false;
  return !cache.baseUrl;
}
