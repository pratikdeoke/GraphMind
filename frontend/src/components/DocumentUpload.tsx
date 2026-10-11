import React, { useRef, useState } from 'react';
import { documentAPI } from '../lib/api';

interface DocumentUploadProps {
  onUploadSuccess?: (data: any) => void;
  onUploadError?: (error: string) => void;
  onUploadStart?: () => void;
}

interface UploadState {
  isLoading: boolean;
  error: string | null;
  progress: number;
  fileName: string | null;
}

export interface UploadedFile {
  name: string;
  timestamp: Date;
  size: number;
  format: string;
}

export const DocumentUpload: React.FC<DocumentUploadProps> = ({
  onUploadSuccess,
  onUploadError,
  onUploadStart,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>({
    isLoading: false,
    error: null,
    progress: 0,
    fileName: null,
  });
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);

  const supportedFormats = ['.pdf', '.docx', '.doc', '.txt', '.png', '.jpg', '.jpeg'];

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const fileExt = '.' + file.name.split('.').pop()?.toLowerCase();
    
    if (!supportedFormats.includes(fileExt)) {
      const error = `Unsupported format: ${fileExt}. Supported: ${supportedFormats.join(', ')}`;
      setState(prev => ({ ...prev, error }));
      onUploadError?.(error);
      return;
    }

    if (file.size > 50 * 1024 * 1024) {
      const error = 'File too large. Maximum size: 50MB';
      setState(prev => ({ ...prev, error }));
      onUploadError?.(error);
      return;
    }

    setState(prev => ({
      ...prev,
      isLoading: true,
      error: null,
      fileName: file.name,
      progress: 0,
    }));

    // Notify parent that upload is starting
    onUploadStart?.();

    try {
      // Simulate progress updates during upload/processing
      let progress = 10;
      const progressInterval = setInterval(() => {
        progress += Math.random() * 25;
        if (progress > 85) progress = 85; // Cap at 85% until done
        setState(prev => ({ ...prev, progress: Math.min(progress, 100) }));
      }, 400);

      // Use the combined upload-and-ingest endpoint
      const response = await documentAPI.uploadAndIngest(file);
      clearInterval(progressInterval);
      
      if (response.success) {
        setState(prev => ({
          ...prev,
          isLoading: false,
          progress: 100,
        }));
        
        // Add to uploaded files list
        const file = event.target.files?.[0];
        if (file) {
          setUploadedFiles(prev => [...prev, {
            name: file.name,
            timestamp: new Date(),
            size: file.size,
            format: file.name.split('.').pop() || 'unknown'
          }]);
        }
        
        onUploadSuccess?.(response);
        
        // Keep success state visible for 3 seconds before resetting
        setTimeout(() => {
          setState(prev => ({
            ...prev,
            fileName: null,
            progress: 0,
          }));
          if (fileInputRef.current) {
            fileInputRef.current.value = '';
          }
        }, 3000);
      } else {
        throw new Error(response.message || 'Upload failed');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Upload failed';
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: errorMessage,
      }));
      onUploadError?.(errorMessage);
    }
  };

  const handleClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="w-full">
      <input
        ref={fileInputRef}
        type="file"
        onChange={handleFileChange}
        disabled={state.isLoading}
        accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg"
        className="hidden"
      />

      {state.error && (
        <div className="mb-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-start gap-2">
          <svg className="w-5 h-5 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span className="flex-1">{state.error}</span>
        </div>
      )}

      {/* Uploaded Files List */}
      {uploadedFiles.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-white/40 uppercase tracking-wider">Uploaded Files</p>
          <div className="space-y-1">
            {uploadedFiles.map((file, idx) => (
              <div
                key={idx}
                className="flex items-center gap-2 px-3 py-2 bg-white/5 border border-white/10 rounded-lg opacity-60 cursor-not-allowed"
                title="Uploaded file - read only"
              >
                <svg className="w-4 h-4 text-white/30 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                </svg>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white/50 truncate">{file.name}</p>
                  <p className="text-xs text-white/25">{(file.size / 1024).toFixed(1)} KB • {file.timestamp.toLocaleTimeString()}</p>
                </div>
                <span className="px-2 py-0.5 bg-emerald-500/20 text-emerald-300/70 text-xs rounded border border-emerald-500/20 flex-shrink-0">
                  ✓ Ingested
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {state.isLoading ? (
        <div className="flex flex-col gap-3 p-4 bg-white/[0.02] border border-white/[0.06] rounded-lg">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span className="text-sm text-white/70 font-medium">
                {state.fileName && `Processing: ${state.fileName}`}
              </span>
            </div>
            <span className="text-sm font-semibold text-indigo-400">{state.progress}%</span>
          </div>
          <div className="w-full h-2.5 bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-indigo-400 transition-all duration-300"
              style={{ width: `${state.progress}%` }}
            />
          </div>
          <p className="text-xs text-white/40 text-center">Extracting text and ingesting into knowledge graph...</p>
        </div>
      ) : (
        <button
          onClick={handleClick}
          disabled={state.isLoading}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 hover:border-indigo-500/50 rounded-lg text-indigo-300 hover:text-indigo-200 transition-all text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
          </svg>
          Upload Document
        </button>
      )}

      <p className="mt-2 text-xs text-white/40">
        Supported: PDF, DOCX, TXT, Images (OCR) • Max 50MB
      </p>
      
      {uploadedFiles.length > 0 && (
        <p className="mt-3 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded text-xs text-blue-300/70 text-center">
          ✓ Files ingested into knowledge graph. Click <strong>Knowledge Graph</strong> tab to see the updated graph with your documents.
        </p>
      )}
    </div>
  );
};

export default DocumentUpload;
