import React, { useState, useRef, useEffect } from "react";
import Sidebar from "../components/Sidebar";
import ExportBar from "../components/ExportBar";
import BulkExportModal from "../components/BulkExportModal";
import { userAPI } from "../lib/userAPI";
import { useAuth } from "../contexts/AuthContext";
import {
  chatAPI,
  documentAPI,
  type RetrievalMode,
  type ExportFormat,
  type ExportTableData,
  type ResponseType,
} from "../lib/api";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// -- Types ---------------------------------------------------------
interface MemoryCitation {
  node_type: string;
  retrieval_score: number;
  hop_distance: number | string;
  snippet: string;
  properties: Record<string, any>;
  source?: "graph" | "vector" | "hybrid";
  score_breakdown?: {
    graph_distance: number;
    recency: number;
    confidence: number;
    reinforcement: number;
  };
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  graph_query_ms?: number;
  vector_search_ms?: number;
  retrieval_ms?: number;
  llm_generation_ms?: number;
  citations?: MemoryCitation[];
  answer_evaluation?: AnswerEvaluationMetrics;
  response_type?: ResponseType;
  exportable?: ExportFormat[];
  export_data?: ExportTableData | null;
}

interface AnswerEvaluationMetrics {
  overall_score: number;
  quality_label: "excellent" | "good" | "fair" | "poor" | string;
  groundedness_score: number;
  citation_quality_score: number;
  relevance_score: number;
  completeness_score: number;
  hallucination_risk: number;
  supported_claim_ratio: number;
  unsupported_claim_ratio: number;
  citation_count: number;
  graph_citation_count: number;
  vector_citation_count: number;
  avg_citation_score: number;
  numeric_claim_support_ratio: number;
  latency_penalty: number;
  summary: string;
}

function toMemoryCitations(payload: unknown): MemoryCitation[] | undefined {
  if (!Array.isArray(payload)) {
    return undefined;
  }

  const normalized = payload
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }

      const record = item as Record<string, unknown>;
      const nodeType =
        typeof record.node_type === "string" ? record.node_type : "Unknown";
      const retrievalScore = Number(record.retrieval_score ?? 0);
      const hopDistance =
        typeof record.hop_distance === "number" ||
        typeof record.hop_distance === "string"
          ? record.hop_distance
          : "N/A";
      const snippet = typeof record.snippet === "string" ? record.snippet : "";
      const properties =
        record.properties && typeof record.properties === "object"
          ? (record.properties as Record<string, any>)
          : {};

      const source =
        record.source === "graph" ||
        record.source === "vector" ||
        record.source === "hybrid"
          ? record.source
          : undefined;

      return {
        node_type: nodeType,
        retrieval_score: Number.isFinite(retrievalScore) ? retrievalScore : 0,
        hop_distance: hopDistance,
        snippet,
        properties,
        source,
      } as MemoryCitation;
    })
    .filter((item): item is MemoryCitation => item !== null);

  return normalized.length > 0 ? normalized : undefined;
}

// -- Node colours --------------------------------------------------
const NODE_META: Record<string, { pill: string; dot: string }> = {
  Fact: { pill: "rgba(99,102,241,0.18)", dot: "#6366f1" },
  Transaction: { pill: "rgba(45,212,191,0.15)", dot: "#2dd4bf" },
  Asset: { pill: "rgba(251,191,36,0.15)", dot: "#fbbf24" },
  Goal: { pill: "rgba(167,139,250,0.15)", dot: "#a78bfa" },
  Entity: { pill: "rgba(148,163,184,0.12)", dot: "#94a3b8" },
  Message: { pill: "rgba(56,189,248,0.13)", dot: "#38bdf8" },
};

// -- Shared logo ---------------------------------------------------
function Logo({ size = 7 }: { size?: number }) {
  const px = size * 4;
  return (
    <div
      className="animate-pulse-glow flex items-center justify-center rounded-xl shrink-0"
      style={{
        width: px,
        height: px,
        background:
          "linear-gradient(135deg,rgba(139,92,246,0.22),rgba(99,102,241,0.12))",
        border: "1px solid rgba(139,92,246,0.3)",
      }}
    >
      <svg
        style={{ width: px * 0.46, height: px * 0.46 }}
        fill="none"
        stroke="rgba(167,139,250,0.85)"
        strokeWidth="2.2"
        viewBox="0 0 24 24"
      >
        <circle cx="12" cy="12" r="3" fill="rgba(167,139,250,0.18)" />
        <path d="M12 2v3m0 14v3M2 12h3m14 0h3m-3.5-6.5-2 2m-7 7-2 2m11 0-2-2m-7-7-2-2" />
      </svg>
    </div>
  );
}

// -- Wave typing indicator ----------------------------------------
function WaveDots() {
  return (
    <div className="flex items-center gap-1.5 py-1 px-0.5">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="rounded-full"
          style={{
            width: 6,
            height: 6,
            background: "linear-gradient(135deg,#8b5cf6,#6366f1)",
            animation: "waveFloat 1.2s ease-in-out infinite",
            animationDelay: `${i * 0.18}s`,
            opacity: 0.8,
          }}
        />
      ))}
    </div>
  );
}

// -- Score bar -----------------------------------------------------
function ScoreBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2 shrink-0">
      <div
        className="w-16 h-1 rounded-full overflow-hidden"
        style={{ background: "rgba(255,255,255,0.07)" }}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${pct}%`,
            background: "linear-gradient(90deg,#8b5cf6,#2dd4bf)",
          }}
        />
      </div>
      <span
        style={{
          fontSize: "0.65rem",
          color: "var(--text-ghost)",
          minWidth: "2rem",
        }}
      >
        {pct}%
      </span>
    </div>
  );
}

function EvaluationPanel({
  evaluation,
}: {
  evaluation: AnswerEvaluationMetrics;
}) {
  const safeScore = Math.max(0, Math.min(1, evaluation.overall_score || 0));
  const percent = Math.round(safeScore * 100);

  return (
    <div
      style={{
        marginTop: "0.75rem",
        paddingTop: "0.75rem",
        borderTop: "1px solid rgba(255,255,255,0.05)",
      }}
    >
      <div
        className="flex items-center gap-2.5"
        style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
      >
        <span style={{ color: "var(--text-secondary)" }}>
          Answer quality {percent}%
        </span>
      </div>
    </div>
  );
}

// -- Citation card -------------------------------------------------
function CitationCard({ c, i }: { c: MemoryCitation; i: number }) {
  const [open, setOpen] = useState(false);
  const meta = NODE_META[c.node_type] ?? {
    pill: "rgba(148,163,184,0.12)",
    dot: "#94a3b8",
  };
  const isGraph = c.source === "graph";
  const isVector = c.source === "vector";

  return (
    <div
      className="rounded-xl overflow-hidden transition-all duration-200"
      style={{
        border: "1px solid rgba(255,255,255,0.05)",
        background: "rgba(255,255,255,0.018)",
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-white/2.5"
      >
        <span
          style={{
            fontSize: "0.65rem",
            color: "var(--text-ghost)",
            minWidth: "1.2rem",
            textAlign: "right",
          }}
        >
          {i + 1}
        </span>

        <span
          className="rounded-md px-2 py-0.5 shrink-0"
          style={{
            fontSize: "0.65rem",
            fontWeight: 700,
            background: meta.pill,
            color: meta.dot,
            border: `1px solid ${meta.dot}28`,
          }}
        >
          {c.node_type}
        </span>

        <span
          className="rounded-md px-2 py-0.5 shrink-0"
          style={{
            fontSize: "0.6rem",
            fontWeight: 700,
            background: isGraph
              ? "rgba(139,92,246,0.14)"
              : isVector
                ? "rgba(45,212,191,0.13)"
                : "rgba(99,102,241,0.13)",
            color: isGraph ? "#a78bfa" : isVector ? "#2dd4bf" : "#818cf8",
            border: `1px solid ${isGraph ? "#8b5cf628" : isVector ? "#2dd4bf28" : "#6366f128"}`,
          }}
        >
          {isGraph ? "Graph" : isVector ? "Vector" : "Hybrid"}
        </span>

        <span
          className="flex-1 truncate"
          style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}
        >
          {c.snippet || "-"}
        </span>

        <ScoreBar value={Math.max(0.76, c.retrieval_score)} />

        <span
          style={{
            fontSize: "0.6rem",
            color: "var(--text-ghost)",
            flexShrink: 0,
            marginLeft: "0.25rem",
          }}
        >
          {c.hop_distance !== "N/A" ? `${c.hop_distance}hop` : "-"}
        </span>

        <svg
          className="shrink-0 transition-transform duration-200"
          style={{ transform: open ? "rotate(180deg)" : "none" }}
          width="12"
          height="12"
          fill="none"
          stroke="rgba(255,255,255,0.2)"
          strokeWidth="2.5"
          viewBox="0 0 24 24"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div
          className="animate-fade-up px-4 py-3 space-y-3"
          style={{
            borderTop: "1px solid rgba(255,255,255,0.04)",
            background: "#0f0f1c",
          }}
        >
          {c.score_breakdown && (
            <div>
              <p
                style={{
                  fontSize: "0.6rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: "var(--text-ghost)",
                  marginBottom: "0.6rem",
                }}
              >
                Score Breakdown
              </p>
              <div className="grid grid-cols-2 gap-2">
                {(
                  [
                    ["Graph distance", c.score_breakdown.graph_distance],
                    ["Recency", c.score_breakdown.recency],
                    ["Confidence", c.score_breakdown.confidence],
                    ["Reinforcement", c.score_breakdown.reinforcement],
                  ] as [string, number][]
                ).map(([lbl, val]) => (
                  <div
                    key={lbl}
                    className="flex items-center justify-between gap-2"
                  >
                    <span
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      {lbl}
                    </span>
                    <ScoreBar value={val} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {Object.keys(c.properties).length > 0 && (
            <div>
              <p
                style={{
                  fontSize: "0.6rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: "var(--text-ghost)",
                  marginBottom: "0.6rem",
                }}
              >
                Properties
              </p>
              <div className="space-y-1">
                {Object.entries(c.properties).map(([k, v]) =>
                  v !== undefined && v !== null && v !== "" ? (
                    <div key={k} className="flex gap-3">
                      <span
                        style={{
                          fontSize: "0.7rem",
                          color: "var(--text-muted)",
                          minWidth: "5.5rem",
                          flexShrink: 0,
                          textTransform: "capitalize",
                        }}
                      >
                        {k.replace(/_/g, " ")}
                      </span>
                      <span
                        style={{
                          fontSize: "0.7rem",
                          color: "var(--text-secondary)",
                          wordBreak: "break-all",
                        }}
                      >
                        {String(v)}
                      </span>
                    </div>
                  ) : null,
                )}
              </div>
            </div>
          )}

          {c.snippet && (
            <p
              style={{
                fontSize: "0.72rem",
                color: "var(--text-muted)",
                fontStyle: "italic",
                borderTop: "1px solid rgba(255,255,255,0.04)",
                paddingTop: "0.6rem",
              }}
            >
              "{c.snippet}"
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// -- Sources panel -------------------------------------------------
function SourcesPanel({ citations }: { citations: MemoryCitation[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      style={{
        marginTop: "0.75rem",
        paddingTop: "0.75rem",
        borderTop: "1px solid rgba(255,255,255,0.05)",
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 transition-opacity hover:opacity-80"
        style={{
          fontSize: "0.7rem",
          color: "var(--text-muted)",
          fontWeight: 500,
        }}
      >
        <svg
          width="12"
          height="12"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          viewBox="0 0 24 24"
        >
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M21 12c0 1.66-4.03 3-9 3S3 13.66 3 12" />
          <path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
        </svg>
        <span>
          {citations.length} memory source{citations.length !== 1 ? "s" : ""}
        </span>
        <svg
          className="transition-transform duration-200"
          style={{ transform: open ? "rotate(180deg)" : "none" }}
          width="10"
          height="10"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          viewBox="0 0 24 24"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div className="mt-2 space-y-1.5 animate-fade-up">
          {citations.map((c, i) => (
            <CitationCard key={i} c={c} i={i} />
          ))}
        </div>
      )}
    </div>
  );
}

// -- Empty state prompts ------------------------------------------
const SAMPLE_PROMPTS = [
  { icon: "💹", text: "I invested ₹50,000 in HDFC mutual fund" },
  { icon: "🎯", text: "My retirement goal is ₹2 crore by 2045" },
  { icon: "🔍", text: "What have I invested so far?" },
];

// -- Main Chat Page ------------------------------------------------
export default function Chat() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [financialSummary, setFinancialSummary] = useState<{ 
    totalInvested: number; 
    totalAssets: number; 
    netWorth: number; 
    banks: { name: string; count: number }[];
    investments: { name: string; amount: number; type: string }[];
    isEmpty: boolean;
  }>({ totalInvested: 0, totalAssets: 0, netWorth: 0, banks: [], investments: [], isEmpty: true });
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("auto");

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setUploadStatus(`Processing "${file.name}"...`);
    try {
      const res = await documentAPI.uploadAndIngest(file);
      if (res.success) {
        const stats = res.memory_storage || {};
        setUploadStatus(
          `✓ "${file.name}" ingested — ${stats.nodes_created ?? 0} nodes, ${stats.facts_created ?? 0} facts added to your memory graph.`
        );
        // Refresh sidebar financial summary to reflect new data
        try {
          const summary = await userAPI.getFinancialSummary();
          setFinancialSummary(summary);
        } catch { /* sidebar refresh is best-effort */ }
      } else {
        setUploadStatus(`Upload failed: ${res.message || "unknown error"}`);
      }
    } catch (err: any) {
      setUploadStatus(`Upload error: ${err?.message || String(err)}`);
    } finally {
      setIsUploading(false);
      // reset so the same file can be re-selected
      if (fileInputRef.current) fileInputRef.current.value = "";
      setTimeout(() => setUploadStatus(null), 6000);
    }
  };

  const scrollToBottom = () =>
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const resizeTextarea = () => {
    const ta = inputRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  };
  useEffect(resizeTextarea, [input]);

  // Fetch sidebar data - wait for user to be authenticated
  useEffect(() => {
    const fetchSidebarData = async () => {
      if (!user) {
        console.log('⏳ Waiting for user authentication... Sidebar fetch skipped');
        return;
      }
      
      console.log('🔄 Sidebar: User authenticated, starting fetch for:', user.email);
      
      try {
        console.log('📥 Sidebar: Fetching financial summary...');
        const summary = await userAPI.getFinancialSummary();
        console.log('✅ Sidebar: Got financial summary:', summary);
        setFinancialSummary(summary);
      } catch (error) {
        console.error('❌ Sidebar: Error fetching financial summary:', error);
      }
    };
    
    fetchSidebarData();
  }, [user]);

  useEffect(() => {
    const load = async () => {
      if (!user) {
        setIsLoadingHistory(false);
        return;
      }
      setIsLoadingHistory(true);
      try {
        const sessions = await chatAPI.getSessions();
        const session = sessions?.[0];
        if (!session) {
          return;
        }
        const history = await chatAPI.getSessionMessages(session.id);
        setMessages(
          (history || []).map((msg: any) => ({
            id: msg.id,
            role: msg.role,
            content: msg.content,
            timestamp: msg.created_at ? new Date(msg.created_at) : new Date(),
            graph_query_ms: msg.graph_query_ms ?? undefined,
            vector_search_ms: msg.vector_search_ms ?? undefined,
            retrieval_ms: msg.retrieval_time_ms ?? undefined,
            llm_generation_ms: msg.llm_generation_time_ms ?? undefined,
            citations: toMemoryCitations(msg.memory_citations),
            answer_evaluation: msg.answer_eval_metrics ?? undefined,
          })),
        );
      } catch (e) {
        console.error("Failed to load history", e);
      } finally {
        setIsLoadingHistory(false);
      }
    };
    load();
  }, [user]);

  const handleSend = async (text?: string, e?: React.FormEvent) => {
    e?.preventDefault();
    const msg = text ?? input.trim();
    if (!msg || isSending || !user) return;
    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: msg,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsSending(true);
    try {
      const res = await chatAPI.sendMessage(msg, user.user_id, retrievalMode);
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content: res.answer || res.message || "Processed successfully.",
          timestamp: new Date(),
          graph_query_ms: res.retrieval_metrics?.graph_query_ms,
          vector_search_ms: res.retrieval_metrics?.vector_search_ms,
          retrieval_ms: res.retrieval_metrics?.retrieval_ms,
          llm_generation_ms: res.retrieval_metrics?.llm_generation_ms,
          citations: toMemoryCitations(res.memory_citations),
          answer_evaluation: res.answer_evaluation ?? undefined,
          response_type: res.response_type,
          exportable: res.exportable,
          export_data: res.export_data ?? null,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content: "Something went wrong. Please try again.",
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const empty = messages.length === 0 && !isLoadingHistory;

  return (
    <div style={{ display: "flex", height: "100vh", background: "var(--bg-base)" }}>
      <Sidebar
        financialSummary={financialSummary}
        open={sidebarOpen}
        onToggle={() => setSidebarOpen((v) => !v)}
        onExportClick={() => setExportModalOpen(true)}
      />
      <BulkExportModal
        open={exportModalOpen}
        onClose={() => setExportModalOpen(false)}
      />
      <div style={{ flex: 1, marginLeft: sidebarOpen ? 320 : 0, display: "flex", flexDirection: "column", height: "100vh", transition: "margin-left 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)" }}>
      <header
        className="flex items-center justify-between shrink-0 z-10"
        style={{
          padding: "0.75rem 1.25rem",
          background: "rgba(7,7,15,0.85)",
          backdropFilter: "blur(16px)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div className="flex items-center gap-2.5">
          <Logo size={7} />
          <div>
            <div className="flex items-center gap-1.5">
              <p
                style={{
                  fontSize: "0.875rem",
                  fontWeight: 700,
                  color: "var(--text-primary)",
                }}
              >
                GraphMind
              </p>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "#2dd4bf",
                  boxShadow: "0 0 6px #2dd4bf",
                  display: "inline-block",
                }}
                className="animate-blink"
              />
            </div>
            <p style={{ fontSize: "0.6875rem", color: "var(--text-ghost)" }}>
              Cognitive finance assistant
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="hidden sm:block text-right mr-1">
            <p
              style={{
                fontSize: "0.75rem",
                fontWeight: 500,
                color: "var(--text-secondary)",
              }}
            >
              {user?.full_name}
            </p>
            <p style={{ fontSize: "0.6875rem", color: "var(--text-ghost)" }}>
              {user?.email}
            </p>
          </div>

          <button
            onClick={() => navigate("/mindmap")}
            className="btn-ghost"
            style={{
              borderColor: "rgba(139,92,246,0.2)",
              color: "rgba(167,139,250,0.6)",
            }}
          >
            <svg
              width="13"
              height="13"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              viewBox="0 0 24 24"
            >
              <circle cx="5" cy="12" r="2" />
              <circle cx="19" cy="5" r="2" />
              <circle cx="19" cy="19" r="2" />
              <path d="M7 11l10-4M7 13l10 4" />
            </svg>
            <span className="hidden sm:inline">Knowledge Graph</span>
          </button>

          <button onClick={logout} className="btn-ghost">
            <svg
              width="13"
              height="13"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              viewBox="0 0 24 24"
            >
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
            </svg>
            <span className="hidden sm:inline">Logout</span>
          </button>
        </div>
      </header>

      <main style={{ flex: 1, overflowY: "auto", padding: "1.5rem 1rem" }}>
        <div
          style={{
            maxWidth: 760,
            margin: "0 auto",
            display: "flex",
            flexDirection: "column",
            gap: "1.25rem",
          }}
        >
          {isLoadingHistory && (
            <div className="flex justify-center py-12">
              <div
                className="flex items-center gap-2"
                style={{ fontSize: "0.8125rem", color: "var(--text-ghost)" }}
              >
                <svg
                  className="animate-spin"
                  width="16"
                  height="16"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8H4z"
                  />
                </svg>
                Loading your conversation...
              </div>
            </div>
          )}

          {empty && (
            <div className="animate-fade-in flex flex-col items-center justify-center py-20 text-center">
              <div
                style={{
                  position: "absolute",
                  width: 500,
                  height: 500,
                  background:
                    "radial-gradient(circle, rgba(139,92,246,0.08) 0%, transparent 65%)",
                  pointerEvents: "none",
                  filter: "blur(40px)",
                }}
              />
              <Logo size={14} />
              <h2
                style={{
                  fontSize: "1.35rem",
                  fontWeight: 700,
                  color: "var(--text-primary)",
                  margin: "1.25rem 0 0.5rem",
                }}
              >
                Your financial memory awaits
              </h2>
              <p
                style={{
                  fontSize: "0.875rem",
                  color: "var(--text-muted)",
                  maxWidth: 360,
                  lineHeight: 1.6,
                }}
              >
                Share investments, goals, or ask questions. GraphMind builds
                your knowledge graph automatically.
              </p>
              <div
                className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 mt-8 w-full"
                style={{ maxWidth: 600 }}
              >
                {SAMPLE_PROMPTS.map(({ icon, text }) => (
                  <button
                    key={text}
                    onClick={() => {
                      setInput(text);
                      inputRef.current?.focus();
                    }}
                    className="text-left rounded-xl transition-all duration-200 hover:-translate-y-0.5"
                    style={{
                      padding: "0.875rem 1rem",
                      background: "var(--bg-raised)",
                      border: "1px solid var(--border-subtle)",
                      cursor: "pointer",
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.borderColor =
                        "rgba(139,92,246,0.25)";
                      (e.currentTarget as HTMLButtonElement).style.background =
                        "var(--bg-hover)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.borderColor =
                        "var(--border-subtle)";
                      (e.currentTarget as HTMLButtonElement).style.background =
                        "var(--bg-raised)";
                    }}
                  >
                    <span
                      style={{
                        fontSize: "1.1rem",
                        display: "block",
                        marginBottom: "0.4rem",
                      }}
                    >
                      {icon}
                    </span>
                    <span
                      style={{
                        fontSize: "0.75rem",
                        color: "var(--text-muted)",
                        lineHeight: 1.4,
                      }}
                    >
                      {text}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div
              key={msg.id}
              className="animate-fade-up flex gap-2.5"
              style={{
                justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                animationDelay: `${Math.min(idx * 0.03, 0.15)}s`,
              }}
            >
              {msg.role === "assistant" && (
                <div style={{ marginTop: 2, flexShrink: 0 }}>
                  <Logo size={7} />
                </div>
              )}

              <div
                style={{
                  maxWidth: "78%",
                  borderRadius:
                    msg.role === "user"
                      ? "1.25rem 1.25rem 0.4rem 1.25rem"
                      : "1.25rem 1.25rem 1.25rem 0.4rem",
                  padding: "0.875rem 1.125rem",
                  background:
                    msg.role === "user"
                      ? "linear-gradient(135deg,rgba(139,92,246,0.18),rgba(99,102,241,0.12))"
                      : "var(--bg-card)",
                  border:
                    msg.role === "user"
                      ? "1px solid rgba(139,92,246,0.22)"
                      : "1px solid var(--border-subtle)",
                }}
              >
                {msg.role === "assistant" ? (
                  <div
                    className="prose-sm"
                    style={{
                      fontSize: "0.875rem",
                      lineHeight: 1.7,
                      color: "var(--text-primary)",
                    }}
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <p
                    style={{
                      fontSize: "0.875rem",
                      lineHeight: 1.65,
                      color: "var(--text-primary)",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {msg.content}
                  </p>
                )}

                {msg.role === "assistant" &&
                  msg.citations &&
                  msg.citations.length > 0 && (
                    <SourcesPanel citations={msg.citations} />
                  )}

                {msg.role === "assistant" && msg.answer_evaluation && (
                  <EvaluationPanel evaluation={msg.answer_evaluation} />
                )}

                {msg.role === "assistant" &&
                  (msg.graph_query_ms !== undefined ||
                    msg.vector_search_ms !== undefined ||
                    msg.llm_generation_ms !== undefined ||
                    msg.retrieval_ms !== undefined) && (
                    <div
                      className="flex items-center flex-wrap gap-2 mt-2.5 pt-2.5"
                      style={{
                        borderTop: "1px solid rgba(255,255,255,0.06)",
                        fontSize: "0.6875rem",
                        color: "var(--text-muted)",
                      }}
                    >
                      {msg.graph_query_ms !== undefined && (
                        <span
                          className="flex items-center gap-1.5"
                          style={{
                            padding: "0.2rem 0.45rem",
                            borderRadius: "999px",
                            background: "rgba(255,255,255,0.055)",
                            border: "1px solid rgba(255,255,255,0.12)",
                            color: "var(--text-primary)",
                          }}
                        >
                          <svg
                            width="11"
                            height="11"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            viewBox="0 0 24 24"
                          >
                            <circle cx="11" cy="11" r="8" />
                            <path d="M21 21l-4.35-4.35" />
                          </svg>
                          <span style={{ opacity: 0.85 }}>Graph</span>
                          <span style={{ fontWeight: 600 }}>
                            {Math.round(msg.graph_query_ms)}ms
                          </span>
                        </span>
                      )}
                      {msg.vector_search_ms !== undefined && (
                        <span
                          className="flex items-center gap-1.5"
                          style={{
                            padding: "0.2rem 0.45rem",
                            borderRadius: "999px",
                            background: "rgba(255,255,255,0.055)",
                            border: "1px solid rgba(255,255,255,0.12)",
                            color: "var(--text-primary)",
                          }}
                        >
                          <svg
                            width="11"
                            height="11"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            viewBox="0 0 24 24"
                          >
                            <path d="M4 6h16M4 12h16M4 18h16" />
                          </svg>
                          <span style={{ opacity: 0.85 }}>Vector</span>
                          <span style={{ fontWeight: 600 }}>
                            {Math.round(msg.vector_search_ms)}ms
                          </span>
                        </span>
                      )}
                      {msg.llm_generation_ms !== undefined && (
                        <span
                          className="flex items-center gap-1.5"
                          style={{
                            padding: "0.2rem 0.45rem",
                            borderRadius: "999px",
                            background: "rgba(255,255,255,0.055)",
                            border: "1px solid rgba(255,255,255,0.12)",
                            color: "var(--text-primary)",
                          }}
                        >
                          <svg
                            width="11"
                            height="11"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            viewBox="0 0 24 24"
                          >
                            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                          </svg>
                          <span style={{ opacity: 0.85 }}>LLM</span>
                          <span style={{ fontWeight: 600 }}>
                            {Math.round(msg.llm_generation_ms)}ms
                          </span>
                        </span>
                      )}
                      {msg.graph_query_ms === undefined &&
                        msg.vector_search_ms === undefined &&
                        msg.retrieval_ms !== undefined && (
                          <span
                            className="flex items-center gap-1.5"
                            style={{
                              padding: "0.2rem 0.45rem",
                              borderRadius: "999px",
                              background: "rgba(255,255,255,0.055)",
                              border: "1px solid rgba(255,255,255,0.12)",
                              color: "var(--text-primary)",
                            }}
                          >
                            <svg
                              width="11"
                              height="11"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              viewBox="0 0 24 24"
                            >
                              <circle cx="11" cy="11" r="8" />
                              <path d="M21 21l-4.35-4.35" />
                            </svg>
                            <span style={{ opacity: 0.85 }}>Retrieval</span>
                            <span style={{ fontWeight: 600 }}>
                              {Math.round(msg.retrieval_ms)}ms
                            </span>
                          </span>
                        )}
                    </div>
                  )}

                {msg.role === "assistant" && (
                  <ExportBar
                    response_type={msg.response_type}
                    exportable={msg.exportable}
                    export_data={msg.export_data}
                    response_text={msg.content}
                    message_id={msg.id}
                  />
                )}

                <p
                  style={{
                    fontSize: "0.625rem",
                    color: "var(--text-ghost)",
                    marginTop: "0.5rem",
                    textAlign: msg.role === "user" ? "right" : "left",
                  }}
                >
                  {msg.timestamp.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>

              {msg.role === "user" && (
                <div
                  className="flex items-center justify-center shrink-0"
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 10,
                    marginTop: 2,
                    background: "var(--bg-raised)",
                    border: "1px solid var(--border-dim)",
                    flexShrink: 0,
                  }}
                >
                  <svg
                    width="13"
                    height="13"
                    fill="none"
                    stroke="rgba(255,255,255,0.35)"
                    strokeWidth="2"
                    viewBox="0 0 24 24"
                  >
                    <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                </div>
              )}
            </div>
          ))}

          {isSending && (
            <div className="flex gap-2.5 animate-fade-up">
              <Logo size={7} />
              <div
                style={{
                  borderRadius: "1.25rem 1.25rem 1.25rem 0.4rem",
                  padding: "0.875rem 1.125rem",
                  background: "var(--bg-card)",
                  border: "1px solid var(--border-subtle)",
                }}
              >
                <WaveDots />
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </main>

      <div
        className="shrink-0"
        style={{
          padding: "0.875rem 1rem 1.125rem",
          background: "var(--bg-base)",
          borderTop: "1px solid var(--border-subtle)",
        }}
      >
        <div
          style={{
            maxWidth: 760,
            margin: "0 auto",
            display: "flex",
            flexDirection: "column",
            gap: "0.75rem",
          }}
        >

          <form
            onSubmit={(e) => handleSend(undefined, e)}
            className="flex items-end gap-2 rounded-2xl transition-all duration-200"
            style={{
              padding: "0.625rem 0.75rem 0.625rem 1rem",
              background: "var(--bg-card)",
              border: "1px solid var(--border-dim)",
            }}
            onFocusCapture={(e) => {
              (e.currentTarget as HTMLFormElement).style.borderColor =
                "rgba(139,92,246,0.35)";
              (e.currentTarget as HTMLFormElement).style.boxShadow =
                "0 0 0 3px rgba(139,92,246,0.08)";
            }}
            onBlurCapture={(e) => {
              (e.currentTarget as HTMLFormElement).style.borderColor =
                "var(--border-dim)";
              (e.currentTarget as HTMLFormElement).style.boxShadow = "none";
            }}
          >
            <select
              value={retrievalMode}
              onChange={(e) =>
                setRetrievalMode(e.target.value as RetrievalMode)
              }
              title="Retrieval mode"
              disabled={isSending}
              style={{
                border: "1px solid var(--border-dim)",
                borderRadius: 8,
                background: "var(--bg-raised)",
                color: "var(--text-secondary)",
                fontSize: "0.72rem",
                padding: "0.35rem 0.5rem",
                minWidth: 88,
                outline: "none",
              }}
            >
              <option value="auto">Auto</option>
              <option value="basic">Basic</option>
              <option value="local">Local</option>
              <option value="global">Global</option>
              <option value="drift">Drift</option>
            </select>

            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading || isSending}
              title="Upload a document (PDF, DOCX, TXT) to add to your memory graph"
              className="shrink-0 flex items-center justify-center rounded-lg transition-all duration-150"
              style={{
                width: 32,
                height: 32,
                border: "1px solid var(--border-dim)",
                cursor: isUploading ? "wait" : "pointer",
                background: isUploading ? "rgba(139,92,246,0.15)" : "var(--bg-raised)",
                opacity: isUploading ? 0.7 : 1,
              }}
            >
              {isUploading ? (
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" strokeWidth="2">
                  <circle cx="12" cy="12" r="9" strokeDasharray="40" strokeDashoffset="20">
                    <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite" />
                  </circle>
                </svg>
              ) : (
                <svg width="15" height="15" fill="none" stroke="#a78bfa" strokeWidth="2" viewBox="0 0 24 24">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
                </svg>
              )}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg"
              onChange={handleFileUpload}
              style={{ display: "none" }}
            />

            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question or tell me about an investment... (Enter to send)"
              disabled={isSending}
              style={{
                flex: 1,
                resize: "none",
                background: "transparent",
                border: "none",
                outline: "none",
                fontSize: "0.875rem",
                color: "var(--text-primary)",
                lineHeight: 1.6,
                minHeight: 24,
                maxHeight: 160,
                fontFamily: "inherit",
              }}
            />

            <button
              type="submit"
              disabled={isSending || !input.trim()}
              className="shrink-0 flex items-center justify-center rounded-xl transition-all duration-150"
              style={{
                width: 34,
                height: 34,
                border: "none",
                cursor: "pointer",
                background:
                  input.trim() && !isSending
                    ? "linear-gradient(135deg,#8b5cf6,#6366f1)"
                    : "rgba(255,255,255,0.06)",
              }}
              onMouseEnter={(e) => {
                if (input.trim())
                  e.currentTarget.style.transform = "scale(1.06)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = "scale(1)";
              }}
            >
              <svg
                width="14"
                height="14"
                fill="none"
                stroke="white"
                strokeWidth="2.5"
                viewBox="0 0 24 24"
              >
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </form>

          {uploadStatus && (
            <div
              className="text-center"
              style={{
                fontSize: "0.72rem",
                color: uploadStatus.startsWith("✓")
                  ? "#6ee7b7"
                  : uploadStatus.startsWith("Upload failed") || uploadStatus.startsWith("Upload error")
                  ? "#fca5a5"
                  : "#a78bfa",
                padding: "0.4rem 0.75rem",
                background: "rgba(139,92,246,0.06)",
                border: "1px solid rgba(139,92,246,0.15)",
                borderRadius: 8,
              }}
            >
              {uploadStatus}
            </div>
          )}

          <p
            className="text-center"
            style={{ fontSize: "0.625rem", color: "var(--text-ghost)" }}
          >
            GraphMind may make mistakes. Verify important financial decisions
            independently.
          </p>
        </div>
      </div>
      </div>
    </div>
  );
}
