"""
GeoMeasure API — FastAPI application entry point.

Configures the FastAPI application with:
- CORS middleware
- Global exception handlers for custom exceptions
- Route registration
- Database initialization on startup
- Structured logging setup
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.core.exceptions import (
    GeoMeasureError,
    FileValidationError,
    UnsupportedFormatError,
    FileSizeExceededError,
    CorruptFileError,
    ShapefileValidationError,
    KMLValidationError,
    AmbiguousDatasetError,
    CRSError,
    MeasurementError,
    GeospatialProcessingError,
    FileNotFoundError_,
)
from app.database.connection import create_tables
from app.api.routes import files, measurements, health

# Initialize logging
setup_logging()
logger = get_logger(__name__)

# Create FastAPI app
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "A REST API that accepts geospatial files (Shapefiles as .zip, KML files), "
        "extracts features, identifies geometry types and properties, calculates "
        "polygon areas and line lengths using CRS-aware measurement strategies, "
        "and returns structured JSON responses."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Global Exception Handlers ---

@app.exception_handler(FileNotFoundError_)
async def file_not_found_handler(request: Request, exc: FileNotFoundError_):
    """Handle file-not-found errors with 404."""
    return JSONResponse(
        status_code=404,
        content={
            "error": "not_found",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(UnsupportedFormatError)
async def unsupported_format_handler(request: Request, exc: UnsupportedFormatError):
    """Handle unsupported file format errors with 415."""
    return JSONResponse(
        status_code=415,
        content={
            "error": "unsupported_format",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(FileSizeExceededError)
async def file_size_handler(request: Request, exc: FileSizeExceededError):
    """Handle file size exceeded errors with 413."""
    return JSONResponse(
        status_code=413,
        content={
            "error": "file_too_large",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(CorruptFileError)
async def corrupt_file_handler(request: Request, exc: CorruptFileError):
    """Handle corrupt file errors with 400."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "corrupt_file",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(AmbiguousDatasetError)
async def ambiguous_dataset_handler(request: Request, exc: AmbiguousDatasetError):
    """Handle ambiguous dataset (multiple Shapefiles in ZIP) with 400."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "ambiguous_dataset",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(ShapefileValidationError)
async def shapefile_validation_handler(request: Request, exc: ShapefileValidationError):
    """Handle Shapefile validation errors with 400."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_shapefile",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(KMLValidationError)
async def kml_validation_handler(request: Request, exc: KMLValidationError):
    """Handle KML validation errors with 400."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_kml",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(FileValidationError)
async def file_validation_handler(request: Request, exc: FileValidationError):
    """Handle general file validation errors with 422."""
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(CRSError)
async def crs_error_handler(request: Request, exc: CRSError):
    """Handle CRS transformation errors with 422."""
    return JSONResponse(
        status_code=422,
        content={
            "error": "crs_error",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(GeospatialProcessingError)
async def geospatial_error_handler(request: Request, exc: GeospatialProcessingError):
    """Handle geospatial processing errors with 422."""
    return JSONResponse(
        status_code=422,
        content={
            "error": "processing_error",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(GeoMeasureError)
async def geomeasure_error_handler(request: Request, exc: GeoMeasureError):
    """Catch-all handler for application errors with 400."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "application_error",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """
    Catch-all handler for unexpected exceptions.

    Logs the full error server-side but returns a safe message to the client
    without exposing stack traces or internal paths.
    """
    logger.error(f"Unhandled exception: {type(exc).__name__}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred while processing your request",
            "details": {},
        },
    )


# --- Startup Event ---

@app.on_event("startup")
async def startup_event():
    """Initialize database tables and log startup."""
    create_tables()
    logger.info(
        f"{settings.app_name} v{settings.app_version} started "
        f"(env={settings.app_env})"
    )


# --- Register Routers ---

app.include_router(health.router)
app.include_router(files.router)
app.include_router(measurements.router)


# --- Root endpoint ---

@app.get("/", tags=["Root"])
def root():
    """Root endpoint with API information."""
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "documentation": "/docs",
        "redoc": "/redoc",
        "health": "/api/health/",
    }
