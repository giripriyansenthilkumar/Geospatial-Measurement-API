"""FastAPI application factory, lifespan, exception handlers, and routing."""

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import init_db
from app.api.routes.files import router as files_router
from app.config import settings
from app.core.errors import GeoMeasureException
from app.core.logging import logger, set_request_id, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context for startup and shutdown routines."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("Initializing database schema...")
    init_db()
    logger.info(f"Database initialized. Environment: {settings.ENVIRONMENT}")
    yield
    logger.info("Application shutting down.")


app = FastAPI(
    title="Geospatial File Measurement API",
    description="High-precision geospatial measurement service for Shapefile archives and KML datasets.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_and_logging_middleware(request: Request, call_next):
    """Injects or extracts X-Request-ID and logs latency."""
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    set_request_id(req_id)
    start_time = time.time()

    response = await call_next(request)

    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = req_id
    logger.info(
        f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.2f}ms)"
    )
    return response


# --- Exception Handlers matching the unified error specification ---


@app.exception_handler(GeoMeasureException)
async def handle_geo_measure_exception(request: Request, exc: GeoMeasureException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    code_map = {
        400: "INVALID_FILE",
        404: "FILE_NOT_FOUND",
        409: "NOT_READY",
        413: "FILE_TOO_LARGE",
        415: "UNSUPPORTED_TYPE",
        422: "INCOMPLETE_SHAPEFILE",
        500: "INTERNAL_ERROR",
    }
    err_code = code_map.get(exc.status_code, "HTTP_ERROR")
    msg = str(exc.detail) if isinstance(exc.detail, str) else "HTTP request error"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": err_code, "message": msg}},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    error_msgs = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []))
        msg = err.get("msg", "Invalid value")
        error_msgs.append(f"{loc}: {msg}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "; ".join(error_msgs),
            }
        },
    )


@app.exception_handler(Exception)
async def handle_unhandled_exception(request: Request, exc: Exception):
    logger.error(f"Unhandled exception during {request.method} {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected internal server error occurred.",
            }
        },
    )


# --- Health check endpoint ---


@app.get("/health", tags=["Health"], summary="Health liveness probe")
def health_check():
    """Liveness probe verifying that the API is up and operational."""
    return {"status": "ok", "version": "1.0.0"}


# Register API routers
app.include_router(files_router)
