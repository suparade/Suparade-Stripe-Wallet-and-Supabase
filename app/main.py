from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import agent, campaigns, creators, webhooks

app = FastAPI(title="Suparade backend", version="0.1.0")


def _origins() -> list:
    try:
        frontend = get_settings().frontend_url
    except RuntimeError:  # settings not configured (for example during tooling)
        frontend = "http://localhost:3000"
    return list({frontend, "http://localhost:3000"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent.router)
app.include_router(campaigns.router)
app.include_router(creators.router)
app.include_router(webhooks.router)


@app.get("/health")
def health():
    return {"ok": True}
