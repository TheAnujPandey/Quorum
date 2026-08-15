"use client";

function confidenceColor(label: string, insufficient: boolean) {
  if (insufficient) return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200";
  if (label === "high") return "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200";
  if (label === "medium") return "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200";
  return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200";
}

export type QnaItem = {
  question: string;
  answer: string;
  citations: { source_ref: string; excerpt: string }[];
  confidence: { label: string; faithfulness: number; answer_relevancy: number };
  retries_used: number;
  execution_time_ms: number;
  insufficient: boolean;
};

export function QnaPanel({
  sessionId,
  history,
  question,
  onQuestionChange,
  onAsk,
  isAsking,
  error,
}: {
  sessionId: string;
  history: QnaItem[];
  question: string;
  onQuestionChange: (value: string) => void;
  onAsk: () => void;
  isAsking: boolean;
  error: string | null;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Ask questions</h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Your data is indexed. Ask anything about the uploaded CSV.
        </p>
      </div>

      <form
        className="flex gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          onAsk();
        }}
      >
        <input
          className="flex-1 rounded-lg border border-slate-300 bg-white px-4 py-2 dark:border-slate-600 dark:bg-slate-950"
          placeholder="What was the deployment force in complaint VA201301-0455?"
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
        />
        <button
          type="submit"
          disabled={isAsking || !question.trim()}
          className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {isAsking ? "Asking..." : "Ask"}
        </button>
      </form>

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">
          {error}
        </div>
      )}

      <div className="space-y-4">
        {history.map((item, index) => (
          <div key={index} className="rounded-lg bg-white p-5 shadow-sm dark:bg-slate-900">
            <p className="mb-2 text-sm font-medium text-slate-500 dark:text-slate-400">Q: {item.question}</p>
            <div className="mb-3 flex items-center justify-between gap-4">
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${confidenceColor(
                  item.confidence.label,
                  item.insufficient,
                )}`}
              >
                {item.insufficient ? "Insufficient" : item.confidence.label}
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {item.execution_time_ms}ms · {item.retries_used} retries
              </span>
            </div>
            <p className="whitespace-pre-wrap text-slate-800 dark:text-slate-100">{item.answer}</p>
            {item.citations.length > 0 && (
              <div className="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
                <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">Citations</p>
                <ul className="space-y-2 text-sm text-slate-600 dark:text-slate-400">
                  {item.citations.map((citation) => (
                    <li key={citation.source_ref}>
                      <span className="font-mono text-slate-800 dark:text-slate-200">{citation.source_ref}</span>
                      <p className="mt-1">{citation.excerpt}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
