# Corpus-powered MCP SSE server for OfficeQA Arena.
# Mount the corpus TXT files at /app/corpus.

FROM python:3.12-slim-bookworm

WORKDIR /app

COPY deploy/mcp-server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY deploy/mcp-server/mcp_sse_server.py /app/mcp_sse_server.py
COPY deploy/mcp-server/cpi_monthly.csv /app/cpi_monthly.csv

ENV PYTHONUNBUFFERED=1
ENV OFFICEQA_CORPUS_DIR=/app/corpus

EXPOSE 8081

CMD ["python3", "/app/mcp_sse_server.py", "--corpus", "/app/corpus", "--port", "8081"]
