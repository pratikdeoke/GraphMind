import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  MarkerType,
  Position,
  Handle,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useAuth } from "../contexts/AuthContext";
import { memoryAPI } from "../lib/api";

const NODE_CONFIG: Record<string, {
  bg: string; border: string; text: string; glow: string; icon: string;
}> = {
  User:        { bg: "#13102a", border: "#8b5cf6", text: "#c4b5fd", glow: "rgba(139,92,246,0.55)", icon: "👤" },
  Message:     { bg: "#0e1e2a", border: "#38bdf8", text: "#7dd3fc", glow: "rgba(56,189,248,0.45)", icon: "💬" },
  Fact:        { bg: "#0e1530", border: "#6366f1", text: "#a5b4fc", glow: "rgba(99,102,241,0.45)", icon: "📌" },
  Asset:       { bg: "#0e2016", border: "#2dd4bf", text: "#99f6e4", glow: "rgba(45,212,191,0.45)", icon: "📈" },
  Goal:        { bg: "#201208", border: "#f59e0b", text: "#fde68a", glow: "rgba(245,158,11,0.45)", icon: "🎯" },
  Transaction: { bg: "#1a0f28", border: "#a855f7", text: "#d8b4fe", glow: "rgba(168,85,247,0.45)", icon: "💳" },
  RiskProfile: { bg: "#220d0d", border: "#f87171", text: "#fca5a5", glow: "rgba(248,113,113,0.45)", icon: "⚠️" },
  Entity:      { bg: "#141418", border: "#64748b", text: "#cbd5e1", glow: "rgba(100,116,139,0.35)", icon: "🔷" },
  Preference:  { bg: "#0e1830", border: "#60a5fa", text: "#bfdbfe", glow: "rgba(96,165,250,0.4)", icon: "⚙️" },
  VectorEntry: { bg: "#0a1f2a", border: "#0ea5e9", text: "#7dd3fc", glow: "rgba(14,165,233,0.4)", icon: "🔮" },
};

function GraphNode({ data }: NodeProps) {
  const cfg = (NODE_CONFIG as any)[data.nodeType as string] ?? NODE_CONFIG.Entity;
  const isUser = data.nodeType === "User";
  return (
    <div
      style={{
        background: cfg.bg,
        border: `1.5px solid ${cfg.border}`,
        borderRadius: 14,
        padding: isUser ? "10px 16px" : "8px 13px",
        minWidth: isUser ? 120 : 100,
        boxShadow: isUser
          ? `0 0 24px ${cfg.glow}, 0 0 8px ${cfg.glow}`
          : `0 0 10px ${cfg.glow}`,
        cursor: "default",
        transition: "box-shadow 0.2s ease",
        position: "relative",
        animation: isUser ? "pulseGlow 2.6s ease-in-out infinite" : undefined,
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLDivElement).style.boxShadow = `0 0 28px ${cfg.glow}, 0 0 14px ${cfg.glow}`;
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLDivElement).style.boxShadow = isUser
          ? `0 0 24px ${cfg.glow}, 0 0 8px ${cfg.glow}`
          : `0 0 10px ${cfg.glow}`;
      }}
    >
      <Handle type="target" position={Position.Top}
        style={{ background: cfg.border, width: 7, height: 7, border: "1.5px solid #07070f" }} />

      <div style={{ display: "flex", alignItems: "center", gap: 6, textAlign: "center", flexDirection: "column" }}>
        <span style={{ fontSize: isUser ? 18 : 14 }}>{cfg.icon}</span>
        <div>
          <div style={{
            fontSize: isUser ? 12 : 11, fontWeight: 700,
            color: cfg.text, lineHeight: 1.3, maxWidth: 120,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {String(data.label)}
          </div>
          <div style={{
            fontSize: 9, fontWeight: 500, color: cfg.border,
            opacity: 0.75, marginTop: 2, textTransform: "uppercase", letterSpacing: "0.06em",
          }}>
            {String(data.nodeType)}
          </div>
        </div>
      </div>

      <Handle type="source" position={Position.Bottom}
        style={{ background: cfg.border, width: 7, height: 7, border: "1.5px solid #07070f" }} />
    </div>
  );
}

const nodeTypes = { graphNode: GraphNode };

function Logo() {
  return (
    <div className="animate-pulse-glow flex-shrink-0 flex items-center justify-center rounded-xl"
      style={{ width: 30, height: 30, background: "linear-gradient(135deg,rgba(139,92,246,0.22),rgba(99,102,241,0.12))", border: "1px solid rgba(139,92,246,0.3)" }}>
      <svg width="14" height="14" fill="none" stroke="rgba(167,139,250,0.85)" strokeWidth="2.2" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="3" fill="rgba(167,139,250,0.18)" />
        <path d="M12 2v3m0 14v3M2 12h3m14 0h3m-3.5-6.5-2 2m-7 7-2 2m11 0-2-2m-7-7-2-2" />
      </svg>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center space-y-6">
        <div className="relative w-20 h-20 mx-auto">
          <div className="absolute inset-0 rounded-full" style={{
            background: "radial-gradient(circle, rgba(139,92,246,0.2) 0%, transparent 70%)",
            animation: "pulseGlow 2s ease-in-out infinite",
          }} />
          <div className="absolute inset-3 rounded-full flex items-center justify-center"
            style={{ background: "var(--bg-raised)", border: "1px solid rgba(139,92,246,0.25)" }}>
            <svg className="animate-spin" width="24" height="24" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-20" cx="12" cy="12" r="10" stroke="rgba(139,92,246,0.8)" strokeWidth="3" />
              <path className="opacity-75" fill="rgba(139,92,246,0.9)" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          </div>
        </div>
        <div className="flex gap-4 justify-center opacity-30">
          {[80, 110, 90].map((w, i) => (
            <div key={i} className="shimmer-skeleton h-10 rounded-xl" style={{ width: w, animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
        <p style={{ fontSize: "0.8125rem", color: "var(--text-ghost)" }}>Building your knowledge graph...</p>
      </div>
    </div>
  );
}

function hierarchyLayout(rawNodes: any[], rawEdges: any[]) {
  const userNode = rawNodes.find(n => n.type === "User");
  if (!userNode) return rawNodes;
  const adj = new Map<string, string[]>();
  rawEdges.forEach(e => {
    if (!adj.has(e.source)) adj.set(e.source, []);
    adj.get(e.source)!.push(e.target);
  });
  const layers = new Map<string, number>();
  const visited = new Set<string>();
  const queue: { id: string; layer: number }[] = [{ id: userNode.id, layer: 0 }];
  layers.set(userNode.id, 0);
  visited.add(userNode.id);
  while (queue.length) {
    const { id, layer } = queue.shift()!;
    (adj.get(id) || []).forEach(cid => {
      if (!visited.has(cid)) {
        visited.add(cid);
        layers.set(cid, layer + 1);
        queue.push({ id: cid, layer: layer + 1 });
      }
    });
  }
  rawNodes.forEach(n => {
    if (!layers.has(n.id))
      layers.set(n.id, Math.max(...Array.from(layers.values())) + 1);
  });
  const byLayer = new Map<number, any[]>();
  rawNodes.forEach(n => {
    const l = layers.get(n.id) || 0;
    if (!byLayer.has(l)) byLayer.set(l, []);
    byLayer.get(l)!.push(n);
  });
  return rawNodes.map(n => {
    const l = layers.get(n.id) || 0;
    const inLayer = byLayer.get(l) || [];
    const idx = inLayer.indexOf(n);
    const totalW = (inLayer.length - 1) * 220;
    return { ...n, x: -totalW / 2 + 400 + idx * 220, y: 80 + l * 210 };
  });
}

export default function Mindmap() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);
  const [isClearing, setIsClearing] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [legendVisible, setLegendVisible] = useState(true);

  const loadMindmap = useCallback(async () => {
    if (!user) return;
    setIsLoading(true);
    setError(null);
    setIsLoading(true);
    setError(null);
    try {
      const data = await memoryAPI.getMindmap();
      const positioned = hierarchyLayout(data.nodes, data.edges);
      setNodeCount(positioned.length);
      setEdgeCount(data.edges.length);
      setNodes(
        positioned.map((n: any): Node => ({
          id: n.id,
          type: "graphNode",
          position: { x: n.x, y: n.y },
          data: { label: n.label, nodeType: n.type },
          sourcePosition: Position.Bottom,
          targetPosition: Position.Top,
        }))
      );
      setEdges(
        data.edges.map((e: any): Edge => {
          const isContradicts = e.label?.includes("CONTRADICTS");
          return {
            id: e.id,
            source: e.source,
            target: e.target,
            label: e.label,
            type: "bezier",
            animated: !isContradicts,
            style: {
              stroke: isContradicts ? "#f87171" : "url(#edgeGradient)",
              strokeWidth: isContradicts ? 1.5 : 1.5,
              strokeDasharray: isContradicts ? "5 4" : undefined,
            },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: isContradicts ? "#f87171" : "#8b5cf6",
              width: 12, height: 12,
            },
            labelStyle: {
              fill: isContradicts ? "#f87171" : "rgba(167,139,250,0.8)",
              fontSize: 8, fontWeight: 700,
            },
            labelBgStyle: { fill: "#07070f", fillOpacity: 0.85, rx: 4 },
            labelBgPadding: [4, 3] as [number, number],
          };
        })
      );
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to load knowledge graph");
    } finally {
      setIsLoading(false);
    }
  }, [user, setNodes, setEdges]);

  useEffect(() => { loadMindmap(); }, [loadMindmap]);

  const handleClearGraph = async () => {
    if (!window.confirm("Delete your entire knowledge graph? This cannot be undone.")) return;
    setIsClearing(true);
    try {
      const result = await memoryAPI.clearGraph();
      if (result.success) {
        setToast({ type: "success", text: `Cleared ${result.deleted_nodes} nodes and ${result.deleted_vectors} vectors` });
        setNodes([]); setEdges([]); setNodeCount(0); setEdgeCount(0);
      } else {
        setToast({ type: "error", text: result.message || "Failed to clear" });
      }
    } catch (err: any) {
      setToast({ type: "error", text: err.response?.data?.detail || "Error clearing graph" });
    } finally {
      setIsClearing(false);
      setTimeout(() => setToast(null), 3500);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-base)" }}>
      <svg width="0" height="0" style={{ position: "absolute" }}>
        <defs>
          <linearGradient id="edgeGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#8b5cf6" />
            <stop offset="100%" stopColor="#2dd4bf" />
          </linearGradient>
        </defs>
      </svg>

      <header
        className="flex items-center justify-between flex-shrink-0 z-10"
        style={{
          padding: "0.75rem 1.25rem",
          background: "rgba(7,7,15,0.85)",
          backdropFilter: "blur(16px)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/chat")} className="btn-ghost">
            <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path d="M19 12H5M12 5l-7 7 7 7" />
            </svg>
            Back
          </button>
          <div className="flex items-center gap-2.5">
            <Logo />
            <div>
              <p style={{ fontSize: "0.875rem", fontWeight: 700, color: "var(--text-primary)" }}>Knowledge Graph</p>
              <p style={{ fontSize: "0.6875rem", color: "var(--text-ghost)" }}>Your financial memory visualised</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {!isLoading && nodes.length > 0 && (
            <div className="hidden sm:flex items-center gap-3">
              {[[nodeCount, "nodes"], [edgeCount, "edges"]].map(([val, lbl]) => (
                <div key={lbl as string} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1"
                  style={{ background: "var(--bg-raised)", border: "1px solid var(--border-subtle)" }}>
                  <span style={{ fontSize: "0.8125rem", fontWeight: 700, color: "var(--text-primary)" }}>{val}</span>
                  <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>{lbl}</span>
                </div>
              ))}
            </div>
          )}

          <button onClick={loadMindmap} disabled={isLoading} className="btn-ghost">
            <svg className={isLoading ? "animate-spin" : ""} width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M23 4v6h-6M1 20v-6h6" />
              <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
            </svg>
            Refresh
          </button>

          <button
            onClick={handleClearGraph}
            disabled={isClearing || isLoading}
            className="btn-ghost"
            style={{ borderColor: "rgba(248,113,113,0.2)", color: "rgba(248,113,113,0.6)" }}
          >
            <svg className={isClearing ? "animate-spin" : ""} width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Clear
          </button>
        </div>
      </header>

      {toast && (
        <div
          className="animate-scale-in flex items-center gap-2 px-4 py-2.5 text-xs font-medium"
          style={{
            borderBottom: "1px solid",
            background: toast.type === "success" ? "rgba(45,212,191,0.07)" : "rgba(239,68,68,0.07)",
            borderColor: toast.type === "success" ? "rgba(45,212,191,0.2)" : "rgba(239,68,68,0.2)",
            color: toast.type === "success" ? "#2dd4bf" : "#f87171",
          }}
        >
          <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
            {toast.type === "success"
              ? <path d="M20 6L9 17l-5-5" />
              : <><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></>
            }
          </svg>
          {toast.text}
        </div>
      )}

      <main style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        {isLoading && nodes.length === 0 ? (
          <LoadingSkeleton />
        ) : error ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center space-y-4 animate-fade-up" style={{ maxWidth: 340 }}>
              <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto"
                style={{ background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.2)" }}>
                <svg width="22" height="22" fill="none" stroke="#f87171" strokeWidth="2" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
              </div>
              <div>
                <p style={{ fontSize: "0.9rem", fontWeight: 600, color: "var(--text-primary)", marginBottom: "0.3rem" }}>Failed to load graph</p>
                <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>{error}</p>
              </div>
              <button onClick={loadMindmap} className="btn-primary" style={{ width: "auto", padding: "0.6rem 1.5rem" }}>Try again</button>
            </div>
          </div>
        ) : nodes.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center space-y-5 animate-fade-up" style={{ maxWidth: 340 }}>
              <div style={{
                width: 72, height: 72, borderRadius: 20, display: "flex", alignItems: "center", justifyContent: "center",
                margin: "0 auto", fontSize: 32,
                background: "var(--bg-raised)", border: "1px solid var(--border-dim)",
              }}>🌐</div>
              <div>
                <p style={{ fontSize: "1rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: "0.4rem" }}>No graph data yet</p>
                <p style={{ fontSize: "0.8125rem", color: "var(--text-muted)", lineHeight: 1.6 }}>
                  Start chatting to build your financial knowledge graph.
                </p>
              </div>
              <button onClick={() => navigate("/chat")} className="btn-primary" style={{ width: "auto", padding: "0.65rem 1.75rem" }}>
                Go to Chat
              </button>
            </div>
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.18 }}
            style={{ background: "var(--bg-base)" }}
          >
            <Background
              variant={BackgroundVariant.Cross}
              gap={28}
              size={1}
              color="rgba(255,255,255,0.03)"
            />
            <Controls
              style={{
                background: "var(--bg-raised)",
                border: "1px solid var(--border-subtle)",
                borderRadius: 10,
              }}
            />
          </ReactFlow>
        )}

        {nodes.length > 0 && (
          <div
            className="absolute bottom-4 left-4 animate-fade-up"
            style={{
              background: "rgba(14,14,26,0.82)",
              backdropFilter: "blur(14px)",
              border: "1px solid rgba(255,255,255,0.07)",
              borderRadius: 16,
              padding: legendVisible ? "1rem 1.125rem" : "0.6rem 1rem",
              boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
              transition: "all 0.25s ease",
              zIndex: 10,
            }}
          >
            <button
              onClick={() => setLegendVisible(v => !v)}
              className="flex items-center justify-between w-full gap-3 mb-0"
              style={{ background: "none", border: "none", cursor: "pointer" }}
            >
              <p style={{ fontSize: "0.6rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-ghost)" }}>
                Node Types
              </p>
              <svg
                className="transition-transform duration-200"
                style={{ transform: legendVisible ? "rotate(0deg)" : "rotate(180deg)" }}
                width="10" height="10" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="2.5" viewBox="0 0 24 24"
              >
                <path d="M18 15l-6-6-6 6" />
              </svg>
            </button>

            {legendVisible && (
              <div className="animate-fade-up" style={{ marginTop: "0.75rem", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.45rem 1.25rem" }}>
                {Object.entries(NODE_CONFIG).map(([type, cfg]) => (
                  <div key={type} className="flex items-center gap-2">
                    <div style={{
                      width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                      background: cfg.border,
                      boxShadow: `0 0 6px ${cfg.glow}`,
                    }} />
                    <span style={{ fontSize: "0.7rem", color: cfg.text, opacity: 0.75 }}>{type}</span>
                  </div>
                ))}
              </div>
            )}

            {legendVisible && (
              <div style={{ marginTop: "0.75rem", paddingTop: "0.6rem", borderTop: "1px solid rgba(255,255,255,0.05)", fontSize: "0.6rem", color: "var(--text-ghost)" }}>
                Drag to rearrange - Scroll to zoom
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
