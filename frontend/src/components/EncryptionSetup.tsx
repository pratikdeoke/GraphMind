import React, { useState } from "react";
import { encryptionAPI } from "../lib/api";
import { deriveAndStoreKey, clearKeyFromSession } from "../services/encryptionService";

/**
 * EncryptionSetup - a modal shown to the user to set up or unlock
 * End-to-End Encryption (E2EE) of their memory graph.
 *
 * Two modes:
 *  - "setup":  shown after first signup. User chooses a PIN (+ optional hint).
 *              The backend generates a salt, encrypts existing nodes, and the
 *              client derives the AES key locally and stores it in
 *              sessionStorage (cleared on tab close).
 *  - "unlock": shown after login when encryption is already enabled. User
 *              enters their PIN to verify and derive the key for this session.
 *
 * SECURITY: The PIN is never persisted. The derived key lives only in
 * sessionStorage and is sent per-request via the X-Encryption-Key header.
 */

export type EncryptionMode = "setup" | "unlock";

interface EncryptionSetupProps {
  mode: EncryptionMode;
  /** Called after the key is successfully derived and stored. */
  onComplete: () => void;
  /** Optional: called if the user skips setup (only meaningful in "setup"). */
  onSkip?: () => void;
  /** Optional PIN hint to display (unlock mode). */
  hint?: string | null;
  /** Whether this is the very first setup right after signup. */
  isFirstTime?: boolean;
}

const MIN_PIN_LENGTH = 4;

export default function EncryptionSetup({
  mode,
  onComplete,
  onSkip,
  hint,
  isFirstTime = false,
}: EncryptionSetupProps) {
  const isSetup = mode === "setup";

  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [pinHint, setPinHint] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validate = (): string | null => {
    if (pin.length < MIN_PIN_LENGTH) {
      return `PIN must be at least ${MIN_PIN_LENGTH} characters`;
    }
    if (isSetup && pin !== confirmPin) {
      return "PINs do not match";
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsSubmitting(true);
    try {
      if (isSetup) {
        // 1. Tell the backend to enable encryption (it stores only the salt).
        const { salt } = await encryptionAPI.setup(
          pin,
          pinHint.trim() ? pinHint.trim() : undefined
        );
        // 2. Derive the AES key locally from PIN + salt and store it.
        await deriveAndStoreKey(pin, salt);
      } else {
        // 1. Verify the PIN; the backend returns the salt.
        const { salt } = await encryptionAPI.verifyPin(pin);
        // 2. Derive the AES key locally and store it in sessionStorage.
        await deriveAndStoreKey(pin, salt);
      }
      onComplete();
    } catch (err: any) {
      const message =
        err?.response?.data?.detail ||
        err?.message ||
        "Something went wrong. Please try again.";
      setError(message);
      // Make sure no half-stored key lingers on failure.
      clearKeyFromSession();
    } finally {
      setIsSubmitting(false);
    }
  };
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(3, 3, 10, 0.72)", backdropFilter: "blur(6px)" }}
    >
      <div
        className="animate-scale-in w-full max-w-[440px] rounded-2xl p-7 relative"
        style={{
          background: "var(--bg-card)",
          border: "1px solid var(--border-mid)",
          boxShadow: "0 24px 70px rgba(0,0,0,0.55)",
        }}
      >
        {/* Header */}
        <div className="flex items-center gap-3 mb-1">
          <div
            className="flex items-center justify-center rounded-xl"
            style={{
              width: 40,
              height: 40,
              background:
                "linear-gradient(135deg, rgba(139,92,246,0.25), rgba(99,102,241,0.15))",
              border: "1px solid rgba(139,92,246,0.35)",
            }}
          >
            <svg width="20" height="20" fill="none" stroke="rgba(167,139,250,0.95)" strokeWidth="2" viewBox="0 0 24 24">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          </div>
          <div>
            <h2 style={{ fontSize: "1.15rem", fontWeight: 700, color: "var(--text-primary)" }}>
              {isSetup ? "Encrypt your memory" : "Unlock your memory"}
            </h2>
            <p style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              End-to-end encrypted with AES-256
            </p>
          </div>
        </div>

        <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", lineHeight: 1.6, margin: "0.75rem 0 1.25rem" }}>
          {isSetup
            ? "Choose a PIN to encrypt your financial memory. Your data is encrypted on this device before it reaches the server — we never see your PIN or the encryption key. If you forget it, your encrypted data cannot be recovered."
            : "Enter your PIN to decrypt your memory for this session. The key lives only in this tab and is cleared when you close it."}
        </p>

        {error && (
          <div
            className="animate-scale-in flex items-start gap-2.5 rounded-xl text-sm mb-4"
            style={{ padding: "0.75rem", background: "rgba(239,68,68,0.07)", border: "1px solid rgba(239,68,68,0.2)", color: "#f87171" }}
          >
            <svg className="flex-shrink-0 mt-0.5" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            {error}
          </div>
        )}

        {!isSetup && hint && (
          <div
            className="rounded-xl text-sm mb-4"
            style={{ padding: "0.7rem 0.85rem", background: "rgba(99,102,241,0.07)", border: "1px solid rgba(99,102,241,0.2)", color: "var(--text-secondary)" }}
          >
            <span style={{ color: "var(--text-muted)" }}>Hint: </span>
            {hint}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label style={{ fontSize: "0.6875rem", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)" }}>
              {isSetup ? "Choose a PIN" : "Enter your PIN"}
            </label>
            <input
              type="password"
              inputMode="numeric"
              autoComplete="off"
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              placeholder="••••"
              required
              disabled={isSubmitting}
              className="input-field"
              autoFocus
            />
          </div>

          {isSetup && (
            <>
              <div className="space-y-1.5">
                <label style={{ fontSize: "0.6875rem", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)" }}>
                  Confirm PIN
                </label>
                <input
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  value={confirmPin}
                  onChange={(e) => setConfirmPin(e.target.value)}
                  placeholder="••••"
                  required
                  disabled={isSubmitting}
                  className="input-field"
                />
                {confirmPin && pin !== confirmPin && (
                  <p style={{ fontSize: "0.7rem", color: "#ef4444", marginTop: "0.25rem" }}>PINs don&apos;t match</p>
                )}
              </div>

              <div className="space-y-1.5">
                <label style={{ fontSize: "0.6875rem", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)" }}>
                  Hint <span style={{ textTransform: "none", fontWeight: 400, color: "var(--text-ghost)" }}>(optional)</span>
                </label>
                <input
                  type="text"
                  value={pinHint}
                  onChange={(e) => setPinHint(e.target.value)}
                  placeholder="A reminder to help you remember your PIN"
                  disabled={isSubmitting}
                  maxLength={255}
                  className="input-field"
                />
              </div>
            </>
          )}

          <button type="submit" disabled={isSubmitting} className="btn-primary" style={{ marginTop: "0.25rem" }}>
            {isSubmitting ? (
              <>
                <svg className="animate-spin" width="16" height="16" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="white" strokeWidth="4" />
                  <path className="opacity-75" fill="white" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                {isSetup ? "Encrypting..." : "Unlocking..."}
              </>
            ) : isSetup ? (
              "Enable encryption"
            ) : (
              "Unlock memory"
            )}
          </button>
        </form>

        {isFirstTime && isSetup && onSkip && (
          <button
            type="button"
            onClick={onSkip}
            disabled={isSubmitting}
            className="btn-ghost w-full justify-center"
            style={{ marginTop: "0.75rem" }}
          >
            Skip for now — I&apos;ll set it up later
          </button>
        )}

        <p style={{ fontSize: "0.6875rem", color: "var(--text-ghost)", marginTop: "1rem", textAlign: "center", lineHeight: 1.5 }}>
          {isSetup
            ? "Your PIN is never stored. The key is derived on this device and kept only for this session."
            : "The key is stored only in this tab's session and cleared on close."}
        </p>
      </div>
    </div>
  );
}

