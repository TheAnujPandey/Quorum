import { getApiBaseUrl, loadSettings } from "@/lib/settings";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export type UploadInitResponse = {
  upload_id: string;
  session_id: string;
  chunk_size: number;
};

export type UploadCompleteResponse = {
  session_id: string;
  job_id?: string | null;
  source_format: string;
  upload_status?: string;
};

export type SessionResponse = {
  session_id: string;
  source_format: string;
  blob_key: string;
  upload_status: string;
  chunk_count?: number | null;
  chunking_method?: string | null;
  chunking_config?: Record<string, unknown>;
};

export type ChunkPreviewResponse = {
  total: number;
  avg_chars: number;
  min_chars: number;
  max_chars: number;
  method: string | null;
  config: Record<string, unknown>;
  sample: {
    chunk_index: number;
    source_ref: string;
    chunk_text: string;
    char_count: number;
  }[];
};

export type JobResponse = {
  id: string;
  job_type: string;
  status: string;
  stage?: string | null;
  progress_pct?: number | null;
  message?: string | null;
  payload: Record<string, unknown>;
  result_ref?: string | null;
  error?: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
};

export type EvalRunSummary = {
  id: string;
  run_type: string;
  avg_retrieval_hit_rate: number | null;
  avg_answer_correctness: number | null;
  avg_faithfulness: number | null;
  avg_answer_relevancy: number | null;
  question_count: number | null;
  started_at: string;
  completed_at: string | null;
};

export type EvalResultDetail = {
  id: number;
  labeled_qa_id: number;
  generated_answer: string | null;
  retrieved_source_refs: string[];
  retrieval_hit: boolean;
  answer_correctness: number | null;
  faithfulness: number | null;
  answer_relevancy: number | null;
  retries_used: number | null;
};

export type EvalRunDetail = EvalRunSummary & {
  results: EvalResultDetail[];
};

export type AskResponse = {
  answer: string;
  citations: { source_ref: string; excerpt: string }[];
  confidence: {
    label: string;
    faithfulness: number;
    answer_relevancy: number;
  };
  retries_used: number;
  execution_time_ms: number;
  insufficient: boolean;
};

export async function initUpload(filename: string, fileSize: number, contentType: string) {
  return apiFetch<UploadInitResponse>("/uploads/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, file_size: fileSize, content_type: contentType }),
  });
}

export async function uploadChunk(uploadId: string, chunkNumber: number, data: Blob) {
  return apiFetch<{ chunk_number: number; received_bytes: number }>(
    `/uploads/${uploadId}/chunk/${chunkNumber}`,
    {
      method: "PUT",
      body: data,
    },
  );
}

export async function completeUpload(uploadId: string) {
  return apiFetch<UploadCompleteResponse>(`/uploads/${uploadId}/complete`, {
    method: "POST",
  });
}

export async function getJob(jobId: string) {
  return apiFetch<JobResponse>(`/jobs/${jobId}`);
}

export async function getSession(sessionId: string) {
  return apiFetch<SessionResponse>(`/sessions/${sessionId}`);
}

export async function startChunking(
  sessionId: string,
  chunking: { method: string; config: Record<string, unknown> },
) {
  return apiFetch<{ job_id: string }>(`/sessions/${sessionId}/chunk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chunking_method: chunking.method,
      chunking_config: chunking.config,
    }),
  });
}

export async function getChunkPreview(sessionId: string) {
  return apiFetch<ChunkPreviewResponse>(`/sessions/${sessionId}/chunks`);
}

export async function startEmbedding(sessionId: string) {
  return apiFetch<{ job_id: string }>(`/sessions/${sessionId}/embed`, {
    method: "POST",
  });
}

export async function clearSession(sessionId: string) {
  return apiFetch<{ ok: boolean }>(`/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export async function askQuestion(sessionId: string, question: string) {
  const { openaiApiKey, openaiModel } = loadSettings();
  const body: Record<string, string> = {
    session_id: sessionId,
    question,
  };
  if (openaiApiKey.trim()) {
    body.openai_api_key = openaiApiKey.trim();
  }
  if (openaiModel.trim()) {
    body.model = openaiModel.trim();
  }

  return apiFetch<AskResponse>("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function guessContentType(file: File): string {
  if (file.type) return file.type;
  const ext = file.name.toLowerCase().split(".").pop();
  const map: Record<string, string> = {
    csv: "text/csv",
    xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    xls: "application/vnd.ms-excel",
    pdf: "application/pdf",
    txt: "text/plain",
  };
  return map[ext || ""] || "application/octet-stream";
}

export async function uploadFile(file: File, onProgress?: (pct: number) => void) {
  const init = await initUpload(file.name, file.size, guessContentType(file));
  const chunkSize = init.chunk_size;
  const totalChunks = Math.ceil(file.size / chunkSize) || 1;

  for (let i = 0; i < totalChunks; i += 1) {
    const start = i * chunkSize;
    const end = Math.min(start + chunkSize, file.size);
    const chunk = file.slice(start, end);
    await uploadChunk(init.upload_id, i + 1, chunk);
    onProgress?.(Math.round(((i + 1) / totalChunks) * 100));
  }

  const completed = await completeUpload(init.upload_id);
  return { ...completed, upload_id: init.upload_id };
}

export async function startEvalRun(sessionId?: string) {
  return apiFetch<{ job_id: string }>("/eval/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sessionId ? { session_id: sessionId } : {}),
  });
}

export async function getEvalRuns() {
  return apiFetch<EvalRunSummary[]>("/eval/runs");
}

export async function getEvalRun(runId: string) {
  return apiFetch<EvalRunDetail>(`/eval/runs/${runId}`);
}
