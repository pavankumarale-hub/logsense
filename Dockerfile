FROM python:3.11-slim

WORKDIR /app

# Install build deps then clean up in the same layer
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir ".[test]"

COPY . .
RUN pip install --no-cache-dir -e .

# Default: run the FastAPI server
CMD ["python", "-m", "uvicorn", "logsense.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
