"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  getEvalRun,
  getEvalRuns,
  startEvalRun,
  getJob,
  type EvalRunDetail,
  type EvalRunSummary,
} from "@/lib/api-client";

function pct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

export default function EvalPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [evalJobId, setEvalJobId] = useState<string | null>(null);

  useEffect(() => {
    setSessionId(localStorage.getItem("quorum_session_id"));
  }, []);

  const runsQuery = useQuery({
    queryKey: ["eval-runs"],
    queryFn: getEvalRuns,
    refetchInterval: 10000,
  });

  const runDetailQuery = useQuery({
    queryKey: ["eval-run", selectedRunId],
    queryFn: () => getEvalRun(selectedRunId!),
    enabled: !!selectedRunId,
  });

  const evalJobQuery = useQuery({
    queryKey: ["eval-job", evalJobId],
    queryFn: () => getJob(evalJobId!),
    enabled: !!evalJobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 2000 : false;
    },
  });

  const runEvalMutation = useMutation({
    mutationFn: () => startEvalRun(sessionId ?? undefined),
    onSuccess: (data) => setEvalJobId(data.job_id),
  });

  useEffect(() => {
    if (evalJobQuery.data?.status === "completed" && evalJobQuery.data.result_ref) {
      try {
        const result = JSON.parse(evalJobQuery.data.result_ref);
        if (result.eval_run_id) {
          setSelectedRunId(result.eval_run_id);
          runsQuery.refetch();
        }
      } catch {
        /* ignore */
      }
      setEvalJobId(null);
    }
  }, [evalJobQuery.data, runsQuery]);

  const runs = runsQuery.data ?? [];
  const detail = runDetailQuery.data;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Eval dashboard</h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Benchmark retrieval and answer quality against labeled Q&A pairs.
          </p>
        </div>
        <button
          type="button"
          disabled={!sessionId || runEvalMutation.isPending || !!evalJobId}
          onClick={() => runEvalMutation.mutate()}
          className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {evalJobId ? "Running benchmark..." : "Run benchmark"}
        </button>
      </div>

      {!sessionId && (
        <div className="rounded-lg bg-yellow-50 p-4 text-sm text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200">
          Upload a file on the home page first — labeled Q&A is auto-seeded per session.
        </div>
      )}

      {runEvalMutation.isError && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">
          {(runEvalMutation.error as Error).message}
        </div>
      )}

      {evalJobQuery.data && evalJobId && (
        <div className="rounded-lg bg-white p-4 shadow-sm dark:bg-slate-900">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {evalJobQuery.data.message ?? "Evaluating..."} ({evalJobQuery.data.progress_pct ?? 0}%)
          </p>
        </div>
      )}

      <div className="overflow-hidden rounded-lg bg-white shadow-sm dark:bg-slate-900">
        <table className="min-w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800">
            <tr>
              <th className="px-4 py-3 text-left font-medium">Run</th>
              <th className="px-4 py-3 text-left font-medium">Type</th>
              <th className="px-4 py-3 text-left font-medium">Retrieval hit</th>
              <th className="px-4 py-3 text-left font-medium">Correctness</th>
              <th className="px-4 py-3 text-left font-medium">Faithfulness</th>
              <th className="px-4 py-3 text-left font-medium">Relevancy</th>
              <th className="px-4 py-3 text-left font-medium">Questions</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                  No benchmark runs yet.
                </td>
              </tr>
            )}
            {runs.map((run: EvalRunSummary) => (
              <tr
                key={run.id}
                onClick={() => setSelectedRunId(run.id)}
                className={`cursor-pointer border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800 ${
                  selectedRunId === run.id ? "bg-blue-50 dark:bg-blue-950" : ""
                }`}
              >
                <td className="px-4 py-3 font-mono text-xs">{run.id.slice(0, 8)}...</td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      run.run_type === "benchmark"
                        ? "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200"
                        : "bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-200"
                    }`}
                  >
                    {run.run_type}
                  </span>
                </td>
                <td className="px-4 py-3">{pct(run.avg_retrieval_hit_rate)}</td>
                <td className="px-4 py-3">{pct(run.avg_answer_correctness)}</td>
                <td className="px-4 py-3">{pct(run.avg_faithfulness)}</td>
                <td className="px-4 py-3">{pct(run.avg_answer_relevancy)}</td>
                <td className="px-4 py-3">{run.question_count ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">Per-question results</h2>
          {detail.results.map((result) => (
            <div key={result.id} className="rounded-lg bg-white p-4 shadow-sm dark:bg-slate-900">
              <div className="mb-2 flex flex-wrap gap-2 text-xs">
                <span
                  className={`rounded-full px-2 py-1 font-semibold ${
                    result.retrieval_hit
                      ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200"
                      : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200"
                  }`}
                >
                  {result.retrieval_hit ? "Retrieval hit" : "Retrieval miss"}
                </span>
                <span className="rounded-full bg-slate-100 px-2 py-1 dark:bg-slate-800">
                  Correctness: {pct(result.answer_correctness)}
                </span>
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                Retrieved: {result.retrieved_source_refs.join(", ") || "none"}
              </p>
              <p className="mt-2 whitespace-pre-wrap text-sm">{result.generated_answer}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
