from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import health, chat, auth, memory, documents, sidebar
from config.settings import settings
from services.graph.memory_decay import MemoryDecayService
from services.graph.community_refresh import CommunityRefreshService
from services.graph.schema_bootstrap import SchemaBootstrapService

openapi_tags = [
    {
        "name": "health",
        "description": "Service health and readiness endpoints."
    },
    {
        "name": "authentication",
        "description": "User signup, login, and token-based user profile endpoints."
    },
    {
        "name": "chat",
        "description": "Unified chat, session management, and conversation history endpoints."
    },
    {
        "name": "memory",
        "description": "Knowledge graph visualization and memory graph endpoints."
    }
]

app = FastAPI(
    title=settings.API_TITLE,
    description=(
        f"{settings.API_DESCRIPTION}\n\n"
        "Authentication uses a Bearer JWT token in the `Authorization` header.\n\n"
        "Interactive docs are available at `/docs` and OpenAPI JSON at `/openapi.json`."
    ),
    version=settings.API_VERSION,
    openapi_tags=openapi_tags,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

memory_decay_service = MemoryDecayService()
community_refresh_service = CommunityRefreshService()
schema_bootstrap_service = SchemaBootstrapService()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validate settings on startup
@app.on_event("startup")
async def startup_event():
    """Validate configuration on startup."""
    settings.validate()
    print(f"🚀 {settings.API_TITLE} v{settings.API_VERSION} starting...")
    index_count = schema_bootstrap_service.ensure_indexes()
    if index_count > 0:
        print(f"[SchemaBootstrap] Index statements processed: {index_count}")
    await memory_decay_service.start()
    await community_refresh_service.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Close background workers and external connections."""
    await memory_decay_service.stop()
    await community_refresh_service.stop()
    schema_bootstrap_service.close()

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/auth", tags=["authentication"])
app.include_router(memory.router, prefix="/memory", tags=["memory"])
app.include_router(documents.router, tags=["documents"])
app.include_router(chat.router, tags=["chat"])
app.include_router(sidebar.router, tags=["sidebar"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": f"Welcome to {settings.API_TITLE}",
        "version": settings.API_VERSION,
        "docs": "/docs",
        "health": "/health",
        "chat": "/chat"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=True)