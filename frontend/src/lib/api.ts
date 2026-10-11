import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Create axios instance with default config
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Add auth token to requests if available
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auth API
export const authAPI = {
  signup: async (email: string, password: string, fullName: string) => {
    const response = await api.post("/auth/signup", {
      email,
      password,
      full_name: fullName,
    });
    return response.data;
  },

  login: async (email: string, password: string) => {
    const response = await api.post("/auth/login", { email, password });
    return response.data;
  },

  getCurrentUser: async () => {
    const response = await api.get("/auth/me");
    return response.data;
  },
};

// Chat API
export type RetrievalMode = "auto" | "basic" | "local" | "global" | "drift";

export interface AnswerEvaluation {
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

export interface ChatApiResponse {
  intent: "MEMORY" | "QUESTION" | "BOTH";
  answer?: string;
  message: string;
  retrieval_metrics?: {
    graph_query_ms: number;
    vector_search_ms: number;
    context_assembly_ms: number;
    retrieval_ms: number;
    llm_generation_ms: number;
    [key: string]: unknown;
  };
  memory_citations?: Array<Record<string, unknown>>;
  answer_evaluation?: AnswerEvaluation;
}

export const chatAPI = {
  sendMessage: async (
    message: string,
    userId: string,
    retrievalMode: RetrievalMode = "auto",
  ): Promise<ChatApiResponse> => {
    const response = await api.post("/chat", {
      message,
      user_id: userId,
      retrieval_mode: retrievalMode,
    });
    return response.data;
  },

  getSessions: async () => {
    const response = await api.get("/sessions");
    return response.data;
  },

  getSessionMessages: async (
    sessionId: string,
    limit: number = 200,
    offset: number = 0,
  ) => {
    const response = await api.get(`/sessions/${sessionId}/messages`, {
      params: { limit, offset },
    });
    return response.data;
  },

  clearSessions: async () => {
    const response = await api.delete("/sessions/clear");
    return response.data;
  },
};

// Memory/Mindmap API
export const memoryAPI = {
  getMindmap: async () => {
    const response = await api.get("/memory/mindmap");
    return response.data;
  },

  clearGraph: async () => {
    const response = await api.delete("/memory/clear");
    return response.data;
  },

  getVectorEntries: async (limit: number = 100) => {
    const response = await api.get("/memory/vectors", {
      params: { limit },
    });
    return response.data;
  },
};

// Document API
export const documentAPI = {
  uploadDocument: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post("/documents/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  ingestDocument: async (
    documentText: string,
    documentName: string,
    documentFormat: string,
    userId: string,
    metadata?: Record<string, any>,
  ) => {
    const response = await api.post("/documents/ingest", {
      user_id: userId,
      document_text: documentText,
      document_name: documentName,
      document_format: documentFormat,
      metadata: metadata || {},
    });
    return response.data;
  },

  uploadAndIngest: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post("/documents/upload-and-ingest", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },
};

export default api;
