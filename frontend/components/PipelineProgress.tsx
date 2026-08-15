"use client";

type Stage = "upload" | "chunking" | "embedding" | "ready";

const STEPS: { id: Stage; label: string }[] = [
  { id: "upload", label: "Upload" },
  { id: "chunking", label: "Chunking" },
  { id: "embedding", label: "Embedding" },
  { id: "ready", label: "Ready" },
];

function stepIndex(stage: Stage): number {
  return STEPS.findIndex((s) => s.id === stage);
}

export function PipelineProgress({
  stage,
  progressPct,
  message,
  status,
}: {
  stage: string | null | undefined;
  progressPct: number | null | undefined;
  message: string | null | undefined;
  status: string;
}) {
  const currentStage: Stage =
    status === "completed"
      ? "ready"
      : stage === "embedding"
        ? "embedding"
        : stage === "chunking" || status === "running" || status === "pending"
          ? "chunking"
          : "upload";

  const activeIdx = stepIndex(currentStage);
  const pct = progressPct ?? (status === "completed" ? 100 : 0);

  return (
    <div className="rounded-lg bg-white p-6 shadow-sm dark:bg-slate-900">
      <h2 className="mb-4 text-lg font-semibold">Ingestion pipeline</h2>

      <div className="mb-6 flex items-center justify-between gap-2">
        {STEPS.map((step, idx) => {
          const done = idx < activeIdx || (idx === activeIdx && status === "completed");
          const active = idx === activeIdx && status !== "completed";
          return (
            <div key={step.id} className="flex flex-1 flex-col items-center gap-2">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold ${
                  done
                    ? "bg-green-600 text-white"
                    : active
                      ? "bg-blue-600 text-white"
                      : "bg-slate-200 text-slate-500 dark:bg-slate-700 dark:text-slate-400"
                }`}
              >
                {done ? "✓" : idx + 1}
              </div>
              <span
                className={`text-xs font-medium ${
                  active || done ? "text-slate-900 dark:text-slate-100" : "text-slate-400"
                }`}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {(status === "pending" || status === "running") && (
        <div>
          <div className="mb-2 flex justify-between text-sm text-slate-600 dark:text-slate-400">
            <span className="capitalize">{stage ?? "processing"}...</span>
            <span>{pct}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div
              className={`h-full transition-all ${
                stage === "embedding" ? "bg-purple-600" : "bg-blue-600"
              }`}
              style={{ width: `${pct}%` }}
            />
          </div>
          {message && <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{message}</p>}
        </div>
      )}

      {status === "completed" && (
        <p className="text-sm text-green-700 dark:text-green-300">
          Ingestion complete — you can ask questions below.
        </p>
      )}

      {status === "failed" && (
        <p className="text-sm text-red-600 dark:text-red-400">Ingestion failed. Try uploading again.</p>
      )}
    </div>
  );
}
