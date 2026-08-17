"use client";

import { useEffect, useState } from "react";
import {
  DEFAULT_API_URL,
  DEFAULT_OPENAI_MODEL,
  loadSettings,
  OPENAI_MODELS,
  saveSettings,
  type AppSettings,
} from "@/lib/settings";

type HealthResponse = {
  status: string;
  postgres: boolean;
  redis: boolean;
  blob_store: boolean;
  qdrant: boolean;
};

type ConfigResponse = {
  default_model: string;
  openai_key_configured: boolean;
};

export default function SettingsPage() {
  const [form, setForm] = useState<AppSettings>({
    apiUrl: DEFAULT_API_URL,
    openaiApiKey: "",
    openaiModel: DEFAULT_OPENAI_MODEL,
  });
  const [saved, setSaved] = useState(false);
  const [apiStatus, setApiStatus] = useState<string | null>(null);
  const [serverConfig, setServerConfig] = useState<ConfigResponse | null>(null);

  useEffect(() => {
    setForm(loadSettings());
  }, []);

  async function testConnection() {
    setApiStatus("Checking...");
    setServerConfig(null);
    try {
      const base = form.apiUrl.replace(/\/$/, "");
      const [health, config] = await Promise.all([
        fetch(`${base}/health`).then((r) => {
          if (!r.ok) throw new Error(`Health check failed (${r.status})`);
          return r.json() as Promise<HealthResponse>;
        }),
        fetch(`${base}/config`).then((r) => {
          if (!r.ok) throw new Error(`Config fetch failed (${r.status})`);
          return r.json() as Promise<ConfigResponse>;
        }),
      ]);
      setServerConfig(config);
      setApiStatus(
        health.status === "ok"
          ? "Connected — all services healthy."
          : "Connected — API is degraded (some services down).",
      );
    } catch (err) {
      setApiStatus((err as Error).message);
    }
  }

  function onSave(event: React.FormEvent) {
    event.preventDefault();
    saveSettings(form);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400">
          Configure the backend API URL and OpenAI credentials used for chat. Values are stored in
          your browser only.
        </p>
      </div>

      <form onSubmit={onSave} className="space-y-6 rounded-lg bg-white p-6 shadow-sm dark:bg-slate-900">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            API URL
          </label>
          <input
            className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2 dark:border-slate-600 dark:bg-slate-950"
            value={form.apiUrl}
            onChange={(e) => setForm((prev) => ({ ...prev, apiUrl: e.target.value }))}
            placeholder="http://localhost:8000"
          />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Backend FastAPI server. Default: {DEFAULT_API_URL}
          </p>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            OpenAI API Key
          </label>
          <input
            type="password"
            className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2 dark:border-slate-600 dark:bg-slate-950"
            value={form.openaiApiKey}
            onChange={(e) => setForm((prev) => ({ ...prev, openaiApiKey: e.target.value }))}
            placeholder="sk-..."
            autoComplete="off"
          />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Sent with chat requests. Leave empty to use the server&apos;s{" "}
            <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">OPENAI_API_KEY</code> from
            .env.
          </p>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            OpenAI Model
          </label>
          <select
            className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2 dark:border-slate-600 dark:bg-slate-950"
            value={form.openaiModel}
            onChange={(e) => setForm((prev) => ({ ...prev, openaiModel: e.target.value }))}
          >
            {OPENAI_MODELS.map((model) => (
              <option key={model.id} value={model.id}>
                {model.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700"
          >
            {saved ? "Saved" : "Save settings"}
          </button>
          <button
            type="button"
            onClick={testConnection}
            className="rounded-lg border border-slate-300 px-4 py-2 font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Test API connection
          </button>
        </div>

        {apiStatus && (
          <div className="rounded-lg bg-slate-100 p-4 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            {apiStatus}
            {serverConfig && (
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                Server default model: {serverConfig.default_model} · Server key configured:{" "}
                {serverConfig.openai_key_configured ? "yes" : "no"}
              </p>
            )}
          </div>
        )}
      </form>
    </div>
  );
}
