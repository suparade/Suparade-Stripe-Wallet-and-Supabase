# Gemini detector on Supabase Compute. The build context is backend/ ([compute.detector] in supabase/config.toml).
# Deploy with scripts/deploy_detector.sh, which writes .env.compute first.
FROM public.ecr.aws/docker/library/python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY . backend/
# config.py loads backend/.env
RUN mv backend/.env.compute backend/.env
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}
