from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog
from typing import AsyncGenerator

from app.config import settings
from app.api import jobs, videos, trends, discovery, analysis, rendering
from app.core.database import engine, Base

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifecycle management"""
    logger.info("Starting YouTube Shorts Automation API", env=settings.app_env)
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("Database initialized")
    
    yield
    
    logger.info("Shutting down API")


# Initialize FastAPI app
app = FastAPI(
    title="YouTube Shorts Automation API",
    description="AI-powered YouTube Shorts creation system",
    version="1.0.0",
    lifespan=lifespan,
    debug=settings.debug
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", exc_info=exc, path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again later."}
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.app_env,
        "version": "1.0.0"
    }


# Include API routers
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(videos.router, prefix="/api/v1/videos", tags=["Videos"])
app.include_router(trends.router, prefix="/api/v1/trends", tags=["Trends"])
app.include_router(discovery.router, prefix="/api/v1/discovery", tags=["Discovery"])
app.include_router(analysis.router, prefix="/api/v1/analysis", tags=["Analysis"])
app.include_router(rendering.router, prefix="/api/v1/rendering", tags=["Rendering"])


@app.get("/")
async def root():
    return {
        "message": "YouTube Shorts Automation API",
        "docs": "/docs",
        "health": "/health"
    }
