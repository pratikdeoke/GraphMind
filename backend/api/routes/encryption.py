"""
Encryption Routes - End-to-End Encryption (E2EE) of the memory graph.

Endpoints (all require a Bearer JWT):
- POST   /encryption/setup       Enable encryption (generate salt, encrypt nodes)
- POST   /encryption/verify-pin  Return the salt so the client derives the key
- POST   /encryption/change-pin  Verify old PIN, re-encrypt all nodes with new key
- DELETE /encryption/disable     Decrypt all nodes back to plaintext, clear salt
- GET    /encryption/status      Return { encryption_enabled, hint }

Security model:
- The PIN is accepted only to derive a key transiently and is never stored.
- The derived AES key is NEVER returned by or sent to the server for storage.
  The client derives it locally from PIN + salt and keeps it in sessionStorage,
  sending it per-request via the X-Encryption-Key header on /chat.
"""

from fastapi import APIRouter, HTTPException, Header, status
from typing import Optional

from api.models_encryption import (
    EncryptionSetupRequest,
    EncryptionSetupResponse,
    VerifyPinRequest,
    VerifyPinResponse,
    ChangePinRequest,
    ChangePinResponse,
    DisableEncryptionResponse,
    EncryptionStatusResponse,
)
from services.auth.auth_service import auth_service
from services.database.user_service import UserService
from services.encryption.encryption_service import get_encryption_service

router = APIRouter()

user_service = UserService()
encryption_service = get_encryption_service()


def _get_user_id(authorization: Optional[str]) -> str:
    """Extract the PostgreSQL user_id from a Bearer JWT token.

    Raises:
        HTTPException: 401 if the token is missing/invalid/expired.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload["user_id"]


def _get_neo4j_user_id(pg_user_id: str) -> str:
    """Fetch the user's neo4j_user_id, raising 404 if the user is missing."""
    user = user_service.get_user_by_id(pg_user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user["neo4j_user_id"]


@router.post(
    "/setup",
    response_model=EncryptionSetupResponse,
    status_code=status.HTTP_200_OK,
    summary="Enable end-to-end encryption",
    description=(
        "Generates a random per-user salt, derives a key from the PIN (to "
        "encrypt existing nodes), stores only the salt + flag, and encrypts any "
        "existing Neo4j nodes. The PIN and derived key are never stored."
    ),
)
async def setup_encryption(
    body: EncryptionSetupRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Enable E2EE for the authenticated user."""
    pg_user_id = _get_user_id(authorization)
    neo4j_user_id = _get_neo4j_user_id(pg_user_id)

    if encryption_service.is_enabled(pg_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encryption is already enabled for this user",
        )

    try:
        result = encryption_service.setup(
            user_id=pg_user_id,
            neo4j_user_id=neo4j_user_id,
            pin=body.pin,
            hint=body.hint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return EncryptionSetupResponse(
        salt=result["salt"],
        success=result.get("success", True),
        nodes_encrypted=result.get("nodes_encrypted", 0),
    )


@router.post(
    "/verify-pin",
    response_model=VerifyPinResponse,
    summary="Verify PIN and return salt",
    description=(
        "Fetches the user's salt so the client can derive the AES key locally "
        "and store it in sessionStorage. Also performs a best-effort server-side "
        "check that the PIN can decrypt existing data. The derived key is never "
        "sent to or stored by the server."
    ),
)
async def verify_pin(
    body: VerifyPinRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Verify a PIN and return the salt for client-side key derivation."""
    pg_user_id = _get_user_id(authorization)
    neo4j_user_id = _get_neo4j_user_id(pg_user_id)

    if not encryption_service.is_enabled(pg_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encryption is not enabled for this user",
        )

    salt = encryption_service.get_salt(pg_user_id)
    if not salt:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Encryption salt is missing",
        )

    valid = encryption_service.verify_pin(pg_user_id, neo4j_user_id, body.pin)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect PIN",
        )

    return VerifyPinResponse(salt=salt, valid=True)


@router.post(
    "/change-pin",
    response_model=ChangePinResponse,
    summary="Change encryption PIN",
    description=(
        "Verifies the old PIN can decrypt existing data, generates a new salt, "
        "re-encrypts ALL of the user's Neo4j nodes with the new key, and updates "
        "the stored salt."
    ),
)
async def change_pin(
    body: ChangePinRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Change the user's encryption PIN and re-encrypt all nodes."""
    pg_user_id = _get_user_id(authorization)
    neo4j_user_id = _get_neo4j_user_id(pg_user_id)

    if not encryption_service.is_enabled(pg_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encryption is not enabled for this user",
        )

    try:
        result = encryption_service.change_pin(
            user_id=pg_user_id,
            neo4j_user_id=neo4j_user_id,
            old_pin=body.old_pin,
            new_pin=body.new_pin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return ChangePinResponse(
        success=result.get("success", True),
        nodes_reencrypted=result.get("nodes_reencrypted", 0),
    )


@router.delete(
    "/disable",
    response_model=DisableEncryptionResponse,
    summary="Disable encryption",
    description=(
        "Decrypts all Neo4j nodes back to plaintext, sets encryption_enabled to "
        "false, and removes the stored salt."
    ),
)
async def disable_encryption(
    body: VerifyPinRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Disable E2EE after decrypting all nodes back to plaintext."""
    pg_user_id = _get_user_id(authorization)
    neo4j_user_id = _get_neo4j_user_id(pg_user_id)

    if not encryption_service.is_enabled(pg_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encryption is not enabled for this user",
        )

    try:
        result = encryption_service.disable(
            user_id=pg_user_id,
            neo4j_user_id=neo4j_user_id,
            pin=body.pin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return DisableEncryptionResponse(
        success=result.get("success", True),
        nodes_decrypted=result.get("nodes_decrypted", 0),
    )


@router.get(
    "/status",
    response_model=EncryptionStatusResponse,
    summary="Get encryption status",
    description="Return whether encryption is enabled and the optional PIN hint.",
)
async def encryption_status(
    authorization: Optional[str] = Header(default=None),
):
    """Return the user's encryption status (never includes the salt)."""
    pg_user_id = _get_user_id(authorization)
    status_data = encryption_service.get_status(pg_user_id)
    return EncryptionStatusResponse(
        encryption_enabled=status_data.get("encryption_enabled", False),
        hint=status_data.get("hint"),
    )

