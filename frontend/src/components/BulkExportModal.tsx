import React, { useState } from "react";
import { exportAPI } from "../lib/api";

interface BulkExportModalProps {
  open: boolean;
  onClose: () => void;
}

function today(): string {
  return new Date().toISOString().split("T")[0];
}

const CHECKBOXES: { key: string; label: string }[] = [
  { key: "stocks", label: "Stock Holdings" },
  { key: "funds", label: "Mutual Funds" },
  { key: "transactions", label: "Transactions" },
  { key: "chat", label: "Chat History" },
];

const BulkExportModal: React.FC<BulkExportModalProps> = ({ open, onClose }) => {
  const [include, setInclude] = useState<Record<string, boolean>>({
    stocks: true,
    funds: true,
    transactions: true,
    chat: true,
  });
  const [format, setFormat] = useState<"pdf" | "excel">("pdf");
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const anySelected = Object.values(include).some(Boolean);

  const toggle = (key: string) => {
    setInclude((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleDownload = async () => {
    if (downloading || !anySelected) return;
    setDownloading(true);
    setError(null);
    try {
      const blob = await exportAPI.exportMemory({
        format,
        stocks: include.stocks,
        funds: include.funds,
        transactions: include.transactions,
        chat: include.chat,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `graphmind_export_${today()}.${format === "pdf" ? "pdf" : "xlsx"}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Export failed. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm animate-scale-in"
        style={{
          background: "linear-gradient(135deg,#12121f 0%,#171727 100%)",
          border: "1px solid rgba(139,92,246,0.2)",
          borderRadius: 16,
          boxShadow: "0 24px 64px rgba(0,0,0,0.5)",
          padding: "1.25rem",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-bold text-white/90">📥 Export Memory</h3>
          <button
            onClick={onClose}
            className="text-white/30 hover:text-white/70 transition-colors cursor-pointer"
            aria-label="Close export dialog"
          >
            <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Include checkboxes */}
        <div className="space-y-2 mb-4">
          {CHECKBOXES.map(({ key, label }) => (
            <label
              key={key}
              className="flex items-center gap-2.5 text-xs text-white/70 cursor-pointer group"
            >
              <input
                type="checkbox"
                checked={include[key]}
                onChange={() => toggle(key)}
                className="accent-indigo-500 w-3.5 h-3.5 cursor-pointer"
              />
              <span className="group-hover:text-white/90 transition-colors">{label}</span>
            </label>
          ))}
        </div>

        {/* Format selection */}
        <div className="flex items-center gap-4 mb-4 text-xs text-white/70">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="export-format"
              checked={format === "pdf"}
              onChange={() => setFormat("pdf")}
              className="accent-indigo-500 w-3.5 h-3.5 cursor-pointer"
            />
            PDF
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="export-format"
              checked={format === "excel"}
              onChange={() => setFormat("excel")}
              className="accent-indigo-500 w-3.5 h-3.5 cursor-pointer"
            />
            Excel
          </label>
        </div>

        {error && (
          <p className="text-[11px] text-red-400 mb-3">{error}</p>
        )}

        <button
          onClick={handleDownload}
          disabled={downloading || !anySelected}
          className="w-full flex items-center justify-center gap-2 text-xs font-semibold py-2.5 rounded-xl transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          style={{
            background: "linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%)",
            color: "#fff",
          }}
        >
          {downloading ? (
            <>
              <svg className="animate-spin" width="13" height="13" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
              Generating…
            </>
          ) : (
            <>Download {format === "pdf" ? "PDF" : "Excel"}</>
          )}
        </button>
      </div>
    </div>
  );
};

export default BulkExportModal;

