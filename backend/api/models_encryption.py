"""
Encryption Models for GraphMind API - End-to-End Encryption (E2EE).

Request/response schemas for the /encryption endpoints.

Security note: the user's PIN is accepted in request bodies only to derive a
key transiently on the server (setup/change/disable) and is never persisted.
The derived AES key itself is never transmitted to or stored by the server; it
lives on the client in sessionStorage and is sent per-request via the
X-Encryption-Key header for chat operations.
"""

from pydantic import BaseModel, Field
from typing import Optional


class EncryptionSetupRequest(BaseModel):
    """Request to enable encryption for a user."""
    pin: str = Field(..., min_length=4, max_length=64, description="User's chosen PIN (4-64 chars). Never stored.")
    hint: Optional[str] = Field(default=None, max_length=255, description="Optional hint to help remember the PIN.")


class EncryptionSetupResponse(BaseModel):
    """Response after enabling encryption."""
    salt: str = Field(..., description="Hex-encoded PBKDF2 salt the client uses to derive the key.")
    success: bool = Field(default=True, description="Whether setup succeeded.")
    nodes_encrypted: int = Field(default=0, description="Number of existing graph nodes that were encrypted.")


class VerifyPinRequest(BaseModel):
    """Request to verify a PIN before deriving the key client-side."""
    pin: str = Field(..., min_length=4, max_length=64, description="PIN to verify.")


class VerifyPinResponse(BaseModel):
    """Response for PIN verification. Contains the salt so the client can
    derive the AES key locally (the key is never sent to the server)."""
    salt: str = Field(..., description="Hex-encoded PBKDF2 salt for key derivation.")
    valid: bool = Field(default=True, description="Whether the PIN appears valid.")


class ChangePinRequest(BaseModel):
    """Request to change the encryption PIN."""
    old_pin: str = Field(..., min_length=4, max_length=64, description="Current PIN.")
    new_pin: str = Field(..., min_length=4, max_length=64, description="New PIN.")


class ChangePinResponse(BaseModel):
    """Response after changing the PIN."""
    success: bool = Field(default=True, description="Whether the change succeeded.")
    nodes_reencrypted: int = Field(default=0, description="Number of nodes re-encrypted with the new key.")


class DisableEncryptionResponse(BaseModel):
    """Response after disabling encryption."""
    success: bool = Field(default=True, description="Whether disable succeeded.")
    nodes_decrypted: int = Field(default=0, description="Number of nodes decrypted back to plaintext.")


class EncryptionStatusResponse(BaseModel):
    """Current encryption status for the user."""
    encryption_enabled: bool = Field(..., description="Whether encryption is enabled.")
    hint: Optional[str] = Field(default=None, description="User's PIN hint, if set.")
