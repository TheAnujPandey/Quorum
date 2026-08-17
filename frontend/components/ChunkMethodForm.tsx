"use client";

import {
  getMethodsForFormat,
  type ChunkingConfig,
  type ChunkingMethodId,
  type SourceFormat,
} from "@/lib/chunking-config";

const SPEED_BADGE: Record<string, string> = {
  fast: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200",
  slow: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-200",
};

export function ChunkMethodForm({
  method,
  config,
  sourceFormat = "csv",
  onMethodChange,
  onConfigChange,
  disabled,
}: {
  method: ChunkingMethodId;
  config: ChunkingConfig;
  sourceFormat?: SourceFormat;
  onMethodChange: (method: ChunkingMethodId) => void;
  onConfigChange: (config: ChunkingConfig) => void;
  disabled?: boolean;
}) {
  const methods = getMethodsForFormat(sourceFormat);
  const selected = methods.find((m) => m.id === method) ?? methods[0];

  return (
    <div className="rounded-lg bg-white p-5 shadow-sm dark:bg-slate-900">
      <h2 className="text-lg font-semibold">Chunking method</h2>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
        Choose how to split your <strong>{sourceFormat.toUpperCase()}</strong> file into chunks for retrieval.
      </p>

      <div className="mt-4">
        <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
          Method
        </label>
        <select
          disabled={disabled}
          className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2 dark:border-slate-600 dark:bg-slate-950"
          value={selected.id}
          onChange={(e) => {
            const next = e.target.value as ChunkingMethodId;
            const meta = methods.find((m) => m.id === next)!;
            onMethodChange(next);
            onConfigChange(meta.defaultConfig);
          }}
        >
          {methods.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase ${SPEED_BADGE[selected.speed]}`}>
          {selected.speed}
        </span>
        <p className="text-sm text-slate-600 dark:text-slate-400">{selected.description}</p>
      </div>

      {selected.configFields.length > 0 && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {selected.configFields.map((field) => (
            <div key={field.key}>
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
                {field.label}
              </label>
              {field.type === "select" ? (
                <select
                  disabled={disabled}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                  value={String(config[field.key] ?? selected.defaultConfig[field.key])}
                  onChange={(e) => onConfigChange({ ...config, [field.key]: e.target.value })}
                >
                  {field.options?.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  disabled={disabled}
                  min={field.min}
                  max={field.max}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
                  value={Number(config[field.key] ?? selected.defaultConfig[field.key])}
                  onChange={(e) =>
                    onConfigChange({ ...config, [field.key]: Number(e.target.value) })
                  }
                />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
