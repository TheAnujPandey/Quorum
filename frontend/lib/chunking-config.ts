export type ChunkingMethodId =
  | "sentence"
  | "fixed"
  | "recursive"
  | "semantic"
  | "line"
  | "paragraph"
  | "page";

export type ChunkingConfig = {
  max_chunk_chars?: number;
  chunk_size?: number;
  chunk_overlap?: number;
  breakpoint_threshold_type?: "percentile" | "standard_deviation" | "interquartile";
};

export type ChunkingMethod = {
  id: ChunkingMethodId;
  label: string;
  speed: "fast" | "medium" | "slow";
  description: string;
  defaultConfig: ChunkingConfig;
  configFields: Array<{
    key: keyof ChunkingConfig;
    label: string;
    type: "number" | "select";
    options?: string[];
    min?: number;
    max?: number;
  }>;
};

export type SourceFormat = "csv" | "xlsx" | "pdf" | "txt" | string;

const METHOD_SENTENCE: ChunkingMethod = {
  id: "sentence",
  label: "Sentence",
  speed: "fast",
  description: "Split on sentence and paragraph boundaries. Fast, no ML model needed.",
  defaultConfig: { max_chunk_chars: 2000 },
  configFields: [
    { key: "max_chunk_chars", label: "Max chunk size (chars)", type: "number", min: 200, max: 8000 },
  ],
};

const METHOD_FIXED: ChunkingMethod = {
  id: "fixed",
  label: "Fixed size",
  speed: "fast",
  description: "Fixed character windows with overlap.",
  defaultConfig: { chunk_size: 1000, chunk_overlap: 100 },
  configFields: [
    { key: "chunk_size", label: "Chunk size", type: "number", min: 200, max: 4000 },
    { key: "chunk_overlap", label: "Overlap", type: "number", min: 0, max: 500 },
  ],
};

const METHOD_RECURSIVE: ChunkingMethod = {
  id: "recursive",
  label: "Recursive",
  speed: "medium",
  description: "Split on paragraphs, then sentences, then words — adapts to content structure.",
  defaultConfig: { chunk_size: 1000, chunk_overlap: 100 },
  configFields: [
    { key: "chunk_size", label: "Chunk size", type: "number", min: 200, max: 4000 },
    { key: "chunk_overlap", label: "Overlap", type: "number", min: 0, max: 500 },
  ],
};

const METHOD_SEMANTIC: ChunkingMethod = {
  id: "semantic",
  label: "Semantic",
  speed: "slow",
  description: "Embedding-based breakpoints. Highest quality but slowest — loads ML model.",
  defaultConfig: { max_chunk_chars: 2000, breakpoint_threshold_type: "percentile" },
  configFields: [
    { key: "max_chunk_chars", label: "Max chunk size (chars)", type: "number", min: 200, max: 8000 },
    {
      key: "breakpoint_threshold_type",
      label: "Breakpoint threshold",
      type: "select",
      options: ["percentile", "standard_deviation", "interquartile"],
    },
  ],
};

const METHOD_LINE: ChunkingMethod = {
  id: "line",
  label: "Line-based",
  speed: "fast",
  description: "Group consecutive lines into chunks. Best for logs, code, and line-oriented text.",
  defaultConfig: { max_chunk_chars: 2000 },
  configFields: [
    { key: "max_chunk_chars", label: "Max chunk size (chars)", type: "number", min: 200, max: 8000 },
  ],
};

const METHOD_PARAGRAPH: ChunkingMethod = {
  id: "paragraph",
  label: "Paragraph",
  speed: "fast",
  description: "Split on double-newlines (paragraphs). Best for articles, reports, and prose.",
  defaultConfig: { max_chunk_chars: 2000 },
  configFields: [
    { key: "max_chunk_chars", label: "Max chunk size (chars)", type: "number", min: 200, max: 8000 },
  ],
};

const METHOD_PAGE: ChunkingMethod = {
  id: "page",
  label: "Page-based",
  speed: "fast",
  description: "One chunk per PDF page. Preserves layout context — good for scanned or layout-heavy PDFs.",
  defaultConfig: {},
  configFields: [],
};

const TABULAR_METHODS: ChunkingMethod[] = [METHOD_SENTENCE, METHOD_FIXED, METHOD_RECURSIVE, METHOD_SEMANTIC];
const PDF_METHODS: ChunkingMethod[] = [METHOD_PAGE, METHOD_RECURSIVE, METHOD_SEMANTIC, METHOD_SENTENCE];
const TXT_METHODS: ChunkingMethod[] = [METHOD_PARAGRAPH, METHOD_LINE, METHOD_RECURSIVE, METHOD_SEMANTIC];

const FORMAT_METHODS: Record<string, ChunkingMethod[]> = {
  csv: TABULAR_METHODS,
  xlsx: TABULAR_METHODS,
  pdf: PDF_METHODS,
  txt: TXT_METHODS,
};

export function getMethodsForFormat(format: SourceFormat): ChunkingMethod[] {
  return FORMAT_METHODS[format] ?? TABULAR_METHODS;
}

export function getDefaultMethodForFormat(format: SourceFormat): ChunkingMethodId {
  const methods = getMethodsForFormat(format);
  return methods[0].id;
}

export const CHUNKING_METHODS: ChunkingMethod[] = [
  METHOD_SENTENCE,
  METHOD_FIXED,
  METHOD_RECURSIVE,
  METHOD_SEMANTIC,
  METHOD_LINE,
  METHOD_PARAGRAPH,
  METHOD_PAGE,
];

export const DEFAULT_CHUNKING_METHOD: ChunkingMethodId = "sentence";

const STORAGE_KEY = "quorum_chunking";

export function loadChunkingPreferences(): {
  method: ChunkingMethodId;
  config: ChunkingConfig;
} {
  if (typeof window === "undefined") {
    return { method: DEFAULT_CHUNKING_METHOD, config: TABULAR_METHODS[0].defaultConfig };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return { method: DEFAULT_CHUNKING_METHOD, config: TABULAR_METHODS[0].defaultConfig };
    }
    const parsed = JSON.parse(raw) as { method?: ChunkingMethodId; config?: ChunkingConfig };
    const method = CHUNKING_METHODS.some((m) => m.id === parsed.method)
      ? (parsed.method as ChunkingMethodId)
      : DEFAULT_CHUNKING_METHOD;
    const meta = CHUNKING_METHODS.find((m) => m.id === method)!;
    return { method, config: { ...meta.defaultConfig, ...parsed.config } };
  } catch {
    return { method: DEFAULT_CHUNKING_METHOD, config: TABULAR_METHODS[0].defaultConfig };
  }
}

export function saveChunkingPreferences(method: ChunkingMethodId, config: ChunkingConfig): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ method, config }));
}
