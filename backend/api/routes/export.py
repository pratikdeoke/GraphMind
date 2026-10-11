"""
Export endpoints.

POST /export/response - export a single chat response as PDF/Excel.
GET  /export/memory   - export all of the user's memory (graph + chat
                        history) as a multi-section PDF or multi-sheet Excel.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services.auth.auth_service import auth_service
from services.database.chat_service import ChatService
from services.database.user_service import UserService
from services.export.generators import (
    export_filename,
    generate_memory_excel,
    generate_memory_pdf,
    generate_response_excel,
    generate_response_pdf,
)
from services.graph.mindmap_service import mindmap_service

router = APIRouter()

user_service = UserService()
chat_service = ChatService()


async def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """Extract user ID from JWT token."""
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


class ExportTableData(BaseModel):
    """Tabular data extracted from structured graph nodes."""
    headers: list = Field(default_factory=list)
    rows: list = Field(default_factory=list)
    node_type: Optional[str] = None


class ExportResponseRequest(BaseModel):
    """Request model for exporting a single chat response."""
    response_text: str = Field(..., description="Assistant answer text to export.")
    export_data: Optional[ExportTableData] = Field(
        default=None, description="Optional table data (headers/rows/node_type).")
    format: str = Field(..., description="Export format: 'pdf' or 'excel'.")
    title: str = Field(default="GraphMind Export", description="Document title.")
    user_id: str = Field(..., description="User UUID (accepted for compatibility).")


@router.post(
    "/response",
    summary="Export a chat response",
    description="Generate a downloadable PDF or Excel file for a chat response.",
    responses={
        200: {"description": "Export file.",
              "content": {PDF_MEDIA_TYPE: {}, XLSX_MEDIA_TYPE: {}}},
        401: {"description": "Missing, invalid, or expired token."},
    },
)
async def export_response(
    request: ExportResponseRequest,
    user_id: str = Depends(get_current_user_id)
):
    """Export a single chat response as a formatted PDF or Excel file."""
    fmt = (request.format or "").lower()
    if fmt not in ("pdf", "excel"):
        raise HTTPException(
            status_code=400, detail="Format must be 'pdf' or 'excel'.")

    user = user_service.get_user_by_id(user_id)
    user_name = (user or {}).get("full_name") or \
        (user or {}).get("email") or "User"

    table = request.export_data.model_dump() if request.export_data else None

    try:
        if fmt == "pdf":
            content = generate_response_pdf(
                response_text=request.response_text,
                export_data=table,
                title=request.title,
                user_name=user_name,
            )
            return _download_response(content, PDF_MEDIA_TYPE, "pdf")

        content = generate_response_excel(
            export_data=table or {"headers": [], "rows": [], "node_type": None},
            title=request.title,
        )
        return _download_response(content, XLSX_MEDIA_TYPE, "xlsx")
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Export generation failed: {exc}")


# -- Full memory export --

def _asset_kind(props: dict) -> str:
    return str(props.get("asset_type") or "").lower()


def _build_memory_sections(include: dict) -> list:
    """Build table sections (headers + rows) from graph + chat history."""
    sections = []
    neo4j_user_id = include.get("neo4j_user_id")
    pg_user_id = include.get("pg_user_id")
    graph_nodes, _ = mindmap_service.get_user_graph(
        neo4j_user_id) if neo4j_user_id else ([], [])
    if not graph_nodes and pg_user_id:
        graph_nodes, _ = mindmap_service.get_user_graph(pg_user_id)



PDF_MEDIA_TYPE = "application/pdf"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download_response(content: bytes, media_type: str, ext: str) -> Response:
    """Wrap file bytes in a downloadable Response with correct headers."""
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{export_filename(ext)}"'},
    )
    if include.get("stocks"):
        rows, seen = [], set()
        for node in graph_nodes:
            props = node.get("properties") or {}
            if node.get("type") != "Asset":
                continue
            if "stock" not in _asset_kind(props):
                continue
            name = props.get("name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            rows.append([
                name,
                props.get("shares", props.get("quantity", "")),
                props.get("buy_price", props.get("price", "")),
                props.get("current_value", props.get("value", "")),
            ])
        sections.append({
            "heading": "Stock Holdings",
            "title": "Stock Holdings",
            "headers": ["name", "shares", "buy_price", "current_value"],
            "rows": rows,
        })

    if include.get("funds"):
        rows, seen = [], set()
        for node in graph_nodes:
            props = node.get("properties") or {}
            if node.get("type") != "Asset":
                continue
            kind = _asset_kind(props)
            if "mutual" not in kind and "fund" not in kind and "sip" not in kind:
                continue
            name = props.get("name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            rows.append([
                name,
                props.get("monthly_sip", props.get("sip_amount", "")),
                props.get("units", props.get("quantity", "")),
                props.get("nav", ""),
                props.get("current_value", props.get("value", "")),
            ])
        sections.append({
            "heading": "Mutual Fund Holdings",
            "title": "Mutual Fund Holdings",
            "headers": ["name", "monthly_sip", "units", "nav", "current_value"],
            "rows": rows,
        })

    if include.get("transactions"):
        rows = []
        for node in graph_nodes:
            if node.get("type") != "Transaction":
                continue
            props = node.get("properties") or {}
            rows.append([
                props.get("date", props.get("transaction_date", "")),
                props.get("transaction_type", props.get("type", "")),
                props.get("asset", props.get("asset_name", "")),
                props.get("amount", ""),
                props.get("notes", props.get("description", "")),
            ])
        sections.append({
            "heading": "Transactions",
            "title": "Transactions",
            "headers": ["date", "type", "asset", "amount", "notes"],
            "rows": rows,
        })

    if include.get("chat"):
        messages = ChatService.get_user_recent_messages(
            include["chat"]["user_id"], limit=500)
        rows = []
        for msg in reversed(messages):
            created = msg.get("created_at")
            rows.append([
                created.strftime("%Y-%m-%d %H:%M") if created else "",
                msg.get("role", ""),
                (msg.get("content") or "")[:500],
            ])
        sections.append({
            "heading": "Chat History",
            "title": "Chat History",
            "headers": ["date", "role", "message"],
            "rows": rows,
        })

    return sections



@router.get(
    "/memory",
    summary="Export full memory",
    description=("Export all user memory (stocks, mutual funds, transactions, "
                 "chat history) as a multi-section PDF or multi-sheet Excel."),
    responses={
        200: {"description": "Export file.",
              "content": {PDF_MEDIA_TYPE: {}, XLSX_MEDIA_TYPE: {}}},
        401: {"description": "Missing, invalid, or expired token."},
    },
)
async def export_memory(
    format: str = Query(default="pdf"),
    stocks: bool = Query(default=True),
    funds: bool = Query(default=True),
    transactions: bool = Query(default=True),
    chat: bool = Query(default=True),
    user_id: str = Depends(get_current_user_id)
):
    """Export the authenticated user's full memory to PDF or Excel."""
    fmt = (format or "").lower()
    if fmt not in ("pdf", "excel"):
        raise HTTPException(
            status_code=400, detail="Format must be 'pdf' or 'excel'.")

    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_name = user.get("full_name") or user.get("email") or "User"

    include = {
        "stocks": stocks,
        "funds": funds,
        "transactions": transactions,
        "chat": {"user_id": user_id} if chat else None,
        "neo4j_user_id": user.get("neo4j_user_id"),
        "pg_user_id": user_id,
    }
    sections = _build_memory_sections(include)

    try:
        if fmt == "pdf":
            content = generate_memory_pdf(sections, user_name=user_name)
            return _download_response(content, PDF_MEDIA_TYPE, "pdf")
        sheets = [{"title": s["title"], "headers": s["headers"],
                   "rows": s["rows"]} for s in sections]
        content = generate_memory_excel(sheets)
        return _download_response(content, XLSX_MEDIA_TYPE, "xlsx")
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Memory export failed: {exc}")

