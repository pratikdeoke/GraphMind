from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class HealthResponse(BaseModel):
    status: str = Field(..., example="healthy")
    message: str = Field(..., example="API is running")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Simple service health endpoint used for uptime checks."
)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "message": "API is running"
    }