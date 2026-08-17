"use client";

import type { ChunkPreviewResponse } from "@/lib/api-client";

export function ChunkPreview({ data }: { data: ChunkPreviewResponse }) {
  return (
    <div className="space-y-4 rounded-lg bg-white p-5 shadow-sm dark:bg-slate-900">
      <div>
        <h2 className="text-lg font-semibold">Chunk preview</h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Method: <span className="font-medium">{data.method ?? "—"}</span>
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
          <p className="text-xs text-slate-500">Total chunks</p>
          <p className="text-xl font-semibold">{data.total}</p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
          <p className="text-xs text-slate-500">Avg chars</p>
          <p className="text-xl font-semibold">{Math.round(data.avg_chars)}</p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
          <p className="text-xs text-slate-500">Min chars</p>
          <p className="text-xl font-semibold">{data.min_chars}</p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
          <p className="text-xs text-slate-500">Max chars</p>
          <p className="text-xl font-semibold">{data.max_chars}</p>
        </div>
      </div>

      <div className="space-y-3">
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
          Sample (first {data.sample.length})
        </p>
        {data.sample.map((chunk) => (
          <div
            key={chunk.chunk_index}
            className="rounded-lg border border-slate-200 p-3 dark:border-slate-700"
          >
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
              <span className="font-mono">{chunk.source_ref}</span>
              <span>{chunk.char_count} chars</span>
            </div>
            <p className="whitespace-pre-wrap text-sm text-slate-800 dark:text-slate-200">
              {chunk.chunk_text}
              {chunk.char_count > 500 ? "…" : ""}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
