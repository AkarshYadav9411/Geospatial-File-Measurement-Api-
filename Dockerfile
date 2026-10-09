# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    APP_ENV=production \
    PORT=8000

# Install system dependencies including GDAL, PROJ, and GEOS for geospatial libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and set up workspace
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/storage/uploads && \
    chown -R appuser:appuser /app

WORKDIR /app

# Copy requirements and install Python dependencies
COPY --chown=appuser:appuser requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code and sample data
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser sample_data/ ./sample_data/
COPY --chown=appuser:appuser pytest.ini ./

# Switch to non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/ || exit 1

# Start the application with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
