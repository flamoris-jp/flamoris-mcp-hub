FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 flamoris
USER flamoris

EXPOSE 8765

CMD ["flamoris-mcp-hub", "--host", "0.0.0.0", "--port", "8765", "--mcp-path", "/mcp"]
