FROM debian:bookworm-slim

LABEL maintainer="modbus-mock-iec104"
LABEL description="Web UI for visualizing and writing a remote GGW3 Modbus TCP register map"

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -u 1000 -s /bin/bash appuser

WORKDIR /app

# Create a virtual environment
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Install Python dependencies (as root, into the venv)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY config/ ./config/

# Fix ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose Web UI port
EXPOSE 8005

# Environment defaults (overridable via docker-compose or -e)
ENV MODBUS_HOST=localhost
ENV MODBUS_PORT=5020
ENV WEB_HOST=0.0.0.0
ENV WEB_PORT=8005
ENV UNIT_ID=1
ENV ENFORCE_ACCESS_CONTROL=false
ENV REGISTER_CSV_PATH=/app/config/registers.csv

CMD ["python", "-m", "app.main"]
