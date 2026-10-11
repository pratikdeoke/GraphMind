import React, { useState, useRef, useEffect } from "react";
import { exportAPI, type ExportFormat, type ExportTableData, type ResponseType } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";

interface ExportBarProps {
  response_type?: ResponseType;
  exportable?: ExportFormat[];
  export_data?: ExportTableData | null;
  response_text: string;
  message_id: string;
}

function today(): string {
  return new Date().toISOString().split("T")[0];
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

const ExportBar: React.FC<ExportBarProps> = ({
  response_type,
  exportable,
  export_data,
  response_text,
}) => {
  const { user } = useAuth();
  const formats = exportable && exportable.length > 0 ? exportable : ["copy"];
  const hasPdf = formats.includes("pdf");
  const hasExcel = formats.includes("excel");
  const [loading, setLoading] = useState<"pdf" | "excel" | null>(null);
  const [toast, setToast] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
  }, []);

  const showToast = (type: "success" | "error", text: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ type, text });
    toastTimer.current = setTimeout(() => setToast(null), 2000);
  };

  const handleDownload = async (format: "pdf" | "excel") => {
    if (loading) return;
    setLoading(format);
    try {
      const blob = await exportAPI.exportResponse({
        response_text: response_text,
        export_data: export_data ?? null,
        format,
        title: response_type === "structured" && export_data?.node_type
          ? `${export_data.node_type} Holdings`
          : "GraphMind Response",
        user_id: user?.user_id ?? "",
      });
      downloadBlob(blob, `graphmind_export_${today()}.${format === "pdf" ? "pdf" : "xlsx"}`);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      showToast("error", typeof detail === "string" ? detail : "Export failed. Please try again.");
    } finally {
      setLoading(null);
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(response_text);
      showToast("success", "Copied!");
    } catch {
      showToast("error", "Failed to copy");
    }
  };

  const btnClass =
    "flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-white/10 " +
    "bg-white/[0.03] text-white/55 hover:text-white/90 hover:bg-white/[0.08] " +
    "opacity-70 hover:opacity-100 transition-all duration-150 disabled:opacity-40 " +
    "disabled:cursor-not-allowed cursor-pointer";


  return (
    <div className="relative">
      <div
        className="flex items-center gap-2 flex-wrap"
        style={{
          marginTop: "0.6rem",
          paddingTop: "0.5rem",
          borderTop: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        {hasPdf && (
          <button
            className={btnClass}
            onClick={() => handleDownload("pdf")}
            disabled={loading !== null}
            title="Download as PDF"
          >
            {loading === "pdf" ? (
              <svg className="animate-spin" width="11" height="11" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
            ) : (
              <span>📄</span>
            )}
            PDF
          </button>
        )}

        {hasExcel && (
          <button
            className={btnClass}
            onClick={() => handleDownload("excel")}
            disabled={loading !== null}
            title="Download as Excel"
          >
            {loading === "excel" ? (
              <svg className="animate-spin" width="11" height="11" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
            ) : (
              <span>📊</span>
            )}
            Excel
          </button>
        )}

        <button className={btnClass} onClick={handleCopy} title="Copy response">
          <span>📋</span>
          Copy
        </button>

        {!hasExcel && (
          <span className="text-[10px] text-white/25 italic">
            Excel not available for this response
          </span>
        )}
      </div>

      {toast && (
        <div
          className="absolute right-0 -top-8 z-10 animate-fade-up flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg"
          style={{
            background: toast.type === "success" ? "rgba(45,212,191,0.1)" : "rgba(239,68,68,0.1)",
            border: `1px solid ${toast.type === "success" ? "rgba(45,212,191,0.25)" : "rgba(239,68,68,0.25)"}`,
            color: toast.type === "success" ? "#2dd4bf" : "#f87171",
          }}
        >
          {toast.type === "success" ? (
            <svg width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path d="M20 6L9 17l-5-5" />
            </svg>
          ) : (
            <svg width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12.01" y1="16" x2="12.01" y2="16" />
            </svg>
          )}
          {toast.text}
        </div>
      )}
    </div>
  );
};

export default ExportBar;
