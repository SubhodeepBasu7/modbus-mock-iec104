FROM debian:bookworm-slim

LABEL maintainer="modbus-mock-iec104"
LABEL description="Controllable Modbus TCP server simulating an IEC104 grid-operator interface"

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

# Expose Modbus TCP and Web UI ports
EXPOSE 5020
EXPOSE 8000

# Environment defaults (overridable via docker-compose or -e)
ENV MODBUS_HOST=0.0.0.0
ENV MODBUS_PORT=5020
ENV WEB_HOST=0.0.0.0
ENV WEB_PORT=8000
ENV UNIT_ID=1
ENV ENFORCE_ACCESS_CONTROL=false

CMD ["python", "-m", "app.main"]
