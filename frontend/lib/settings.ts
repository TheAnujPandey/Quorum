export type AppSettings = {
  apiUrl: string;
  openaiApiKey: string;
  openaiModel: string;
};

const STORAGE_KEY = "quorum_settings";
const API_KEY_STORAGE_KEY = "quorum_api_key";

export const DEFAULT_API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const DEFAULT_OPENAI_MODEL = "gpt-4o-mini";

export const OPENAI_MODELS = [
  { id: "gpt-4o-mini", label: "gpt-4o-mini (fastest, recommended)" },
  { id: "gpt-3.5-turbo", label: "gpt-3.5-turbo (fast)" },
  { id: "gpt-4o", label: "gpt-4o (higher quality, slower)" },
  { id: "gpt-4-turbo", label: "gpt-4-turbo (higher quality, slower)" },
] as const;

const DEFAULTS: AppSettings = {
  apiUrl: DEFAULT_API_URL,
  openaiApiKey: "",
  openaiModel: DEFAULT_OPENAI_MODEL,
};

export function loadSettings(): AppSettings {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as Partial<AppSettings>) : {};
    const apiKey = sessionStorage.getItem(API_KEY_STORAGE_KEY) ?? "";
    return {
      apiUrl: parsed.apiUrl?.trim() || DEFAULTS.apiUrl,
      openaiApiKey: apiKey,
      openaiModel: parsed.openaiModel?.trim() || DEFAULTS.openaiModel,
    };
  } catch {
    return DEFAULTS;
  }
}

export function saveSettings(settings: AppSettings): void {
  sessionStorage.setItem(API_KEY_STORAGE_KEY, settings.openaiApiKey);
  const { openaiApiKey: _, ...persistent } = settings;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(persistent));
}

export function clearApiKey(): void {
  if (typeof window !== "undefined") {
    sessionStorage.removeItem(API_KEY_STORAGE_KEY);
  }
}

export function getApiBaseUrl(): string {
  return loadSettings().apiUrl.replace(/\/$/, "");
}
