FROM python:3.14-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose game port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/player/status')" || exit 1

# Run with uvicorn
CMD ["uvicorn", "api.app:create_app()", "--host", "0.0.0.0", "--port", "8001", "--factory"]
