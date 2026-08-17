"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ChunkMethodForm } from "@/components/ChunkMethodForm";
import { ChunkPreview } from "@/components/ChunkPreview";
import { PipelineProgress } from "@/components/PipelineProgress";
import { QnaPanel, type QnaItem } from "@/components/QnaPanel";
import {
  CHUNKING_METHODS,
  getDefaultMethodForFormat,
  getMethodsForFormat,
  loadChunkingPreferences,
  saveChunkingPreferences,
  type ChunkingConfig,
  type ChunkingMethodId,
} from "@/lib/chunking-config";
import {
  askQuestion,
  clearSession,
  getChunkPreview,
  getJob,
  getSession,
  startChunking,
  startEmbedding,
  uploadFile,
} from "@/lib/api-client";

type Step = "upload" | "chunk" | "preview" | "embed" | "ready";

export default function HomePage() {
  const [mounted, setMounted] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<QnaItem[]>([]);
  const [chunkingMethod, setChunkingMethod] = useState<ChunkingMethodId>("sentence");
  const [chunkingConfig, setChunkingConfig] = useState<ChunkingConfig>(
    CHUNKING_METHODS[0].defaultConfig,
  );
  const [sourceFormat, setSourceFormat] = useState<string | null>(null);

  useEffect(() => {
    setMounted(true);
    const stored = localStorage.getItem("quorum_session_id");
    if (stored && stored !== "null" && /^[0-9a-f-]{36}$/i.test(stored)) {
      setSessionId(stored);
    }
    const storedJob = localStorage.getItem("quorum_job_id");
    if (storedJob && /^[0-9a-f-]{36}$/i.test(storedJob)) {
      setJobId(storedJob);
    }
    const prefs = loadChunkingPreferences();
    setChunkingMethod(prefs.method);
    setChunkingConfig(prefs.config);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    saveChunkingPreferences(chunkingMethod, chunkingConfig);
  }, [chunkingMethod, chunkingConfig, mounted]);

  const sessionQuery = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => getSession(sessionId!),
    enabled: !!sessionId && mounted && /^[0-9a-f-]{36}$/i.test(sessionId),
    retry: false,
    refetchInterval: (query) => {
      const s = query.state.data?.upload_status;
      return s === "chunking" || s === "embedding" ? 1500 : false;
    },
  });

  useEffect(() => {
    if (sessionQuery.data?.source_format) {
      const fmt = sessionQuery.data.source_format;
      if (fmt !== sourceFormat) {
        setSourceFormat(fmt);
        const methods = getMethodsForFormat(fmt);
        const currentValid = methods.some((m) => m.id === chunkingMethod);
        if (!currentValid) {
          const defaultMethod = getDefaultMethodForFormat(fmt);
          const meta = methods.find((m) => m.id === defaultMethod)!;
          setChunkingMethod(defaultMethod);
          setChunkingConfig(meta.defaultConfig);
        }
      }
    }
  }, [sessionQuery.data]);

  const status = sessionQuery.data?.upload_status;
  const step: Step =
    status === "ingested"
      ? "ready"
      : status === "embedding"
        ? "embed"
        : status === "chunked"
          ? "preview"
          : status === "chunking"
            ? "chunk"
            : status === "uploaded"
              ? "chunk"
              : "upload";

  void step;

  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "pending" || s === "running" || !query.state.data ? 1500 : false;
    },
  });

  useEffect(() => {
    const job = jobQuery.data;
    if (!job || !sessionId) return;
    if (job.status === "completed") {
      setJobId(null);
      localStorage.removeItem("quorum_job_id");
      sessionQuery.refetch();
    }
  }, [jobQuery.data, sessionId, sessionQuery]);

  const previewQuery = useQuery({
    queryKey: ["chunks", sessionId],
    queryFn: () => getChunkPreview(sessionId!),
    enabled: !!sessionId && (status === "chunked" || status === "ingested"),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadFile(file, setUploadProgress),
    onSuccess: (result) => {
      setSessionId(result.session_id);
      setSourceFormat(result.source_format);
      setHistory([]);
      setJobId(null);
      localStorage.setItem("quorum_session_id", result.session_id);
      localStorage.removeItem("quorum_job_id");
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const chunkMutation = useMutation({
    mutationFn: () =>
      startChunking(sessionId!, {
        method: chunkingMethod,
        config: chunkingConfig as Record<string, unknown>,
      }),
    onSuccess: (result) => {
      setJobId(result.job_id);
      localStorage.setItem("quorum_job_id", result.job_id);
      setError(null);
      sessionQuery.refetch();
    },
    onError: (err: Error) => setError(err.message),
  });

  const embedMutation = useMutation({
    mutationFn: () => startEmbedding(sessionId!),
    onSuccess: (result) => {
      setJobId(result.job_id);
      localStorage.setItem("quorum_job_id", result.job_id);
      setError(null);
      sessionQuery.refetch();
    },
    onError: (err: Error) => setError(err.message),
  });

  const askMutation = useMutation({
    mutationFn: () => askQuestion(sessionId!, question),
    onSuccess: (data) => {
      setHistory((prev) => [{ question, ...data }, ...prev]);
      setQuestion("");
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  async function onClearSession() {
    if (sessionId) {
      try {
        await clearSession(sessionId);
      } catch {
        /* ignore */
      }
    }
    setSessionId(null);
    setJobId(null);
    setHistory([]);
    setSourceFormat(null);
    localStorage.removeItem("quorum_session_id");
    localStorage.removeItem("quorum_job_id");
    setError(null);
  }

  const ACCEPTED_EXTENSIONS = [".csv", ".xlsx", ".xls", ".pdf", ".txt"];

  function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      setError(`Unsupported file type. Accepted: ${ACCEPTED_EXTENSIONS.join(", ")}`);
      return;
    }
    setUploadProgress(0);
    uploadMutation.mutate(file);
  }

  const job = jobQuery.data;
  const isJobRunning = job?.status === "pending" || job?.status === "running";
  const showUpload = !sessionId || status === "uploading" || (!status && !sessionQuery.isLoading);

  if (!mounted) {
    return (
      <div className="space-y-8">
        <h1 className="text-2xl font-semibold">Quorum</h1>
        <p className="text-slate-600 dark:text-slate-400">Loading…</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Quorum</h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Upload → choose chunking → preview → embed → ask questions.
          </p>
        </div>
        {sessionId && (
          <button
            type="button"
            onClick={onClearSession}
            className="rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950"
          >
            Clear session
          </button>
        )}
      </div>

      {sessionId && (
        <div className="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          Session <span className="font-mono text-xs">{sessionId}</span>
          {sourceFormat && (
            <>
              {" "}
              · format <span className="font-medium">{sourceFormat}</span>
            </>
          )}
          {status && (
            <>
              {" "}
              · status <span className="font-medium">{status}</span>
            </>
          )}
        </div>
      )}

      {(showUpload || !sessionId) && status !== "uploaded" && status !== "chunking" && status !== "chunked" && status !== "embedding" && status !== "ingested" && (
        <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-white p-10 hover:border-slate-400 dark:border-slate-600 dark:bg-slate-900 dark:hover:border-slate-500">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {uploadMutation.isPending ? "Uploading..." : "Choose a file to upload (CSV, Excel, PDF, TXT)"}
          </span>
          <input type="file" accept=".csv,.xlsx,.xls,.pdf,.txt" className="hidden" onChange={onFileChange} />
        </label>
      )}

      {uploadMutation.isPending && (
        <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-slate-900">
          <div className="mb-2 text-sm text-slate-600 dark:text-slate-400">
            Upload progress: {uploadProgress}%
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div className="h-full bg-blue-600 transition-all" style={{ width: `${uploadProgress}%` }} />
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">
          {error}
        </div>
      )}

      {(status === "uploaded" || status === "chunked") && !isJobRunning && (
        <div className="space-y-4">
          <ChunkMethodForm
            method={chunkingMethod}
            config={chunkingConfig}
            sourceFormat={sourceFormat ?? "csv"}
            onMethodChange={setChunkingMethod}
            onConfigChange={setChunkingConfig}
            disabled={chunkMutation.isPending}
          />
          <button
            type="button"
            onClick={() => chunkMutation.mutate()}
            disabled={chunkMutation.isPending}
            className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {status === "chunked" ? "Re-chunk" : "Run chunking"}
          </button>
        </div>
      )}

      {isJobRunning && job && (
        <PipelineProgress
          stage={job.stage}
          progressPct={job.progress_pct}
          message={job.message}
          status={job.status}
        />
      )}

      {job?.error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">
          {job.error}
        </div>
      )}

      {previewQuery.data && (status === "chunked" || status === "ingested") && (
        <ChunkPreview data={previewQuery.data} />
      )}

      {status === "chunked" && !isJobRunning && (
        <button
          type="button"
          onClick={() => embedMutation.mutate()}
          disabled={embedMutation.isPending}
          className="rounded-lg bg-purple-600 px-4 py-2 font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {embedMutation.isPending ? "Starting embedding..." : "Embed chunks & index"}
        </button>
      )}

      {status === "ingested" && sessionId && (
        <QnaPanel
          sessionId={sessionId}
          history={history}
          question={question}
          onQuestionChange={setQuestion}
          onAsk={() => {
            if (!question.trim()) return;
            askMutation.mutate();
          }}
          isAsking={askMutation.isPending}
          error={askMutation.isError ? (askMutation.error as Error).message : null}
        />
      )}
    </div>
  );
}
