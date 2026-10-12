/**
 * encryptionService.ts
 *
 * Client-side End-to-End Encryption (E2EE) for the GraphMind memory graph.
 *
 * Security model
 * --------------
 * - The user's PIN is NEVER sent to, derived on, or stored by the server.
 * - The AES-256 key is DERIVED locally from the PIN + the user's salt using
 *   PBKDF2-HMAC-SHA256 with 310,000 iterations (identical parameters to the
 *   backend `services/encryption/crypto_service.py` so both sides produce the
 *   exact same key bytes).
 * - The raw key is exported to base64 and sent per-request via the
 *   `X-Encryption-Key` header for /chat. It is kept only in sessionStorage so
 *   it is cleared automatically when the tab closes.
 *
 * IMPORTANT: These constants MUST stay in sync with crypto_service.py.
 */

// --- Constants (keep in sync with backend crypto_service.py) ---
const PBKDF2_ITERATIONS = 310_000;
const KEY_LENGTH_BITS = 256; // 256-bit AES key
const SESSION_STORAGE_KEY = "graphmind_encryption_key";

/**
 * Convert a hex string (e.g. the salt returned by the backend) into a
 * Uint8Array suitable for the Web Crypto API.
 */
function hexToBytes(hex: string): Uint8Array {
  const clean = hex.trim().replace(/^0x/i, "");
  if (clean.length % 2 !== 0) {
    throw new Error("Invalid hex salt: odd length");
  }
  const bytes = new Uint8Array(clean.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(clean.substr(i * 2, 2), 16);
  }
  return bytes;
}

/**
 * Convert an ArrayBuffer to a base64 string (for sending the key in a header).
 */
function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Derive a 256-bit AES-GCM CryptoKey from a PIN and salt using PBKDF2.
 *
 * Parameters are identical to the backend so the derived key bytes match:
 *   PBKDF2-HMAC-SHA256, 310,000 iterations, 32-byte output.
 *
 * @param pin  The user's PIN (plaintext). Never leaves the browser.
 * @param salt Hex-encoded salt string (as returned by the backend).
 * @returns    A non-extractable-by-default CryptoKey (extractable here so it
 *             can be exported to base64 for the X-Encryption-Key header).
 */
export async function deriveKey(pin: string, salt: string): Promise<CryptoKey> {
  if (!pin) throw new Error("PIN is required to derive the encryption key");
  if (!salt) throw new Error("Salt is required to derive the encryption key");

  const enc = new TextEncoder();
  const pinBytes = enc.encode(pin);
  const saltBytes = hexToBytes(salt);

  // Import the PIN as raw key material for PBKDF2.
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    pinBytes,
    "PBKDF2",
    false,
    ["deriveKey", "deriveBits"]
  );

  // Derive the AES-GCM key.
  const key = await crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: saltBytes as unknown as BufferSource,
      iterations: PBKDF2_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: KEY_LENGTH_BITS },
    true, // extractable so we can export it to base64
    ["encrypt", "decrypt"]
  );

  return key;
}

/**
 * Export a CryptoKey to a base64 string (raw key bytes) for the
 * X-Encryption-Key header. The backend base64-decodes this to the same 32 raw
 * bytes it uses for AES-256-GCM.
 */
export async function exportKey(key: CryptoKey): Promise<string> {
  const raw = await crypto.subtle.exportKey("raw", key);
  return arrayBufferToBase64(raw);
}

/**
 * Store the base64 key in sessionStorage. Cleared automatically when the tab
 * or browser window closes (unlike localStorage).
 */
export function storeKeyInSession(key: string): void {
  try {
    sessionStorage.setItem(SESSION_STORAGE_KEY, key);
  } catch (err) {
    console.error("Failed to store encryption key in sessionStorage:", err);
  }
}

/** Retrieve the base64 key from sessionStorage, or null if not present. */
export function getKeyFromSession(): string | null {
  try {
    return sessionStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Remove the key from sessionStorage (e.g. on logout). */
export function clearKeyFromSession(): void {
  try {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Convenience: derive a key from PIN + salt, export it to base64, and store it
 * in sessionStorage. Returns the base64 key so callers can use it immediately.
 */
export async function deriveAndStoreKey(pin: string, salt: string): Promise<string> {
  const key = await deriveKey(pin, salt);
  const exported = await exportKey(key);
  storeKeyInSession(exported);
  return exported;
}
