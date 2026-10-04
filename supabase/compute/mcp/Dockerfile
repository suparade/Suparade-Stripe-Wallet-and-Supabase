# Suparade MCP server on Supabase Compute: supabase compute push mcp --project-ref <ref>
FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1
# Compute provides $PORT and forwards /compute/v1/mcp/* here with that prefix removed.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
