"use client";

import { useCallback, useState } from "react";

interface Props {
  transcript: string;
  filename: string | null;
  onReset: () => void;
  summarizationEnabled?: boolean;
}

export default function TranscriptView({
  transcript,
  filename,
  onReset,
  summarizationEnabled = true,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryCopied, setSummaryCopied] = useState(false);

  const stem = filename?.replace(/\.[^.]+$/, "") ?? "transcript";

  // The summary is prepended to downloads so a saved file is self-contained.
  const composeDocument = useCallback(
    () => (summary ? `## Summary\n\n${summary}\n\n---\n\n${transcript}` : transcript),
    [summary, transcript]
  );

  const download = useCallback(
    (extension: "md" | "txt") => {
      const type = extension === "md" ? "text/markdown" : "text/plain";
      const blob = new Blob([composeDocument()], { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${stem}.${extension}`;
      a.click();
      URL.revokeObjectURL(url);
    },
    [composeDocument, stem]
  );

  const copy = useCallback(() => {
    navigator.clipboard.writeText(transcript).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [transcript]);

  const copySummary = useCallback(() => {
    if (!summary) return;
    navigator.clipboard.writeText(summary).then(() => {
      setSummaryCopied(true);
      setTimeout(() => setSummaryCopied(false), 2000);
    });
  }, [summary]);

  const summarize = useCallback(async () => {
    setSummarizing(true);
    setSummaryError(null);
    try {
      const res = await fetch("/api/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, title: stem }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Summarization failed");
      setSummary(data.summary);
    } catch (e: unknown) {
      setSummaryError(e instanceof Error ? e.message : String(e));
    } finally {
      setSummarizing(false);
    }
  }, [transcript, stem]);

  const lineCount = transcript.split("\n").filter((l) => l.trim()).length;

  return (
    <div className="w-full space-y-4">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex-1 min-w-0">
          <h2 className="font-semibold truncate">{filename ?? "Transcript"}</h2>
          <p className="text-xs text-neutral-500">{lineCount} lines</p>
        </div>

        <button
          onClick={summarize}
          disabled={summarizing || !summarizationEnabled}
          title={
            summarizationEnabled
              ? "Summarize this transcript with AI"
              : "Set OPENAI_API_KEY in your .env file to enable summaries"
          }
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-neutral-800 disabled:text-neutral-500 disabled:cursor-not-allowed text-sm font-medium transition-colors"
        >
          {summarizing ? (
            <>
              <SpinnerIcon className="w-4 h-4 animate-spin" />
              Summarizing…
            </>
          ) : (
            <>
              <SparkleIcon className="w-4 h-4" />
              {summary ? "Regenerate" : "Summarize"}
            </>
          )}
        </button>

        <button
          onClick={copy}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm transition-colors"
        >
          {copied ? (
            <>
              <CheckIcon className="w-4 h-4 text-green-400" />
              Copied
            </>
          ) : (
            <>
              <CopyIcon className="w-4 h-4" />
              Copy
            </>
          )}
        </button>
        <button
          onClick={() => download("md")}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm transition-colors"
        >
          <DownloadIcon className="w-4 h-4" />
          .md
        </button>
        <button
          onClick={() => download("txt")}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm transition-colors"
        >
          <DownloadIcon className="w-4 h-4" />
          .txt
        </button>
        <button
          onClick={onReset}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-700 hover:bg-violet-600 text-sm transition-colors"
        >
          New file
        </button>
      </div>

      {/* Summary error */}
      {summaryError && (
        <div className="flex items-start gap-2 bg-red-950/60 border border-red-900 rounded-xl px-4 py-3 text-sm text-red-300">
          <span className="flex-1">{summaryError}</span>
          <button
            onClick={() => setSummaryError(null)}
            className="text-red-400 hover:text-red-200 transition-colors"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {/* Summary skeleton while generating */}
      {summarizing && !summary && (
        <div className="bg-neutral-900 border border-amber-900/50 rounded-xl p-5 space-y-2.5">
          <div className="h-3 bg-neutral-800 rounded animate-pulse w-1/3" />
          <div className="h-3 bg-neutral-800 rounded animate-pulse w-full" />
          <div className="h-3 bg-neutral-800 rounded animate-pulse w-11/12" />
          <div className="h-3 bg-neutral-800 rounded animate-pulse w-4/5" />
        </div>
      )}

      {/* Summary */}
      {summary && (
        <div className="bg-neutral-900 border border-amber-900/50 rounded-xl overflow-hidden">
          <div className="flex items-center gap-2 px-5 py-3 border-b border-neutral-800 bg-amber-950/20">
            <SparkleIcon className="w-4 h-4 text-amber-400" />
            <span className="text-sm font-semibold text-amber-200">AI Summary</span>
            <button
              onClick={copySummary}
              className="ml-auto text-xs text-neutral-400 hover:text-white transition-colors"
            >
              {summaryCopied ? "Copied" : "Copy summary"}
            </button>
          </div>
          <div className="p-5 text-sm leading-relaxed whitespace-pre-wrap text-neutral-200 max-h-[40vh] overflow-y-auto">
            {summary}
          </div>
        </div>
      )}

      {/* Transcript content */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 font-mono text-sm leading-relaxed max-h-[60vh] overflow-y-auto whitespace-pre-wrap text-neutral-200">
        {transcript}
      </div>
    </div>
  );
}

function CopyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <rect x="7" y="7" width="9" height="11" rx="1.5" />
      <path d="M13 7V5.5A1.5 1.5 0 0011.5 4h-7A1.5 1.5 0 003 5.5v9A1.5 1.5 0 004.5 16H7" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5l4 4 7-7" />
    </svg>
  );
}

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10 3v10m0 0l-3.5-3.5M10 13l3.5-3.5M3 17h14" />
    </svg>
  );
}

function SparkleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M10 2.5l1.6 4.4 4.4 1.6-4.4 1.6L10 14.5 8.4 10.1 4 8.5l4.4-1.6L10 2.5zM15.5 13l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z"
      />
    </svg>
  );
}

function SpinnerIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={className}>
      <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth={2} opacity={0.25} />
      <path d="M17 10a7 7 0 00-7-7" stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
    </svg>
  );
}
