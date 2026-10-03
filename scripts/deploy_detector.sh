#!/bin/bash
# Deploy the Gemini detector to Supabase Compute: https://pvoesovsparqqzosgwki.supabase.co/compute/v1/detector
#
#   ./scripts/deploy_detector.sh
#
# The container can't read the root .env, and our access token can't set project secrets, so this writes the
# detector's own values to backend/.env.compute (gitignored), which ships in the upload. Never the whole .env.
# DETECTOR_KEY guards the endpoints that start, feed and stop sessions. It is generated once and kept in that file.
# Size, exposure and source are [compute.detector] in supabase/config.toml.
# Needs: `supabase login` (or SUPABASE_ACCESS_TOKEN) and Node for npx. See docs/SETUP.md.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=backend/.env.compute

# backend/.env wins over the root .env, like in backend/config.py
setting() { { cat backend/.env .env 2>/dev/null || true; } | grep "^$1=" | head -1 | cut -d= -f2- | tr -d '[:space:]' || true; }

[ -n "$(setting GEMINI_API_KEY)" ] || { echo "GEMINI_API_KEY is empty in backend/.env and .env"; exit 1; }
KEY=$(grep -m1 '^DETECTOR_KEY=' "$OUT" 2>/dev/null | cut -d= -f2- || true)
{
  for name in GEMINI_API_KEY SUPARADE_CAMPAIGN_ID SUPARADE_AGENT_KEY AGENT_API_KEY CORS_ORIGINS; do
    value=$(setting "$name")
    if [ -n "$value" ]; then echo "$name=$value"; fi
  done
  # localhost can't be reached from the container; without an https URL the detector simulates tips
  url=$(setting SUPARADE_API_URL)
  if [[ "$url" == https://* ]]; then echo "SUPARADE_API_URL=$url"; fi
  echo "DETECTOR_KEY=${KEY:-$(openssl rand -hex 24)}"
} > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

export SUPABASE_EXPERIMENTAL_COMPUTE=1
# An empty SUPABASE_ACCESS_TOKEN must not be exported: the CLI would use it instead of the `supabase login` token.
TOKEN="${SUPABASE_ACCESS_TOKEN:-$(setting SUPABASE_ACCESS_TOKEN)}"
if [ -n "$TOKEN" ]; then export SUPABASE_ACCESS_TOKEN="$TOKEN"; fi
npx -y supabase@latest compute deploy detector --project-ref pvoesovsparqqzosgwki
