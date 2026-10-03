from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_user
from app.db import get_supabase
from app.schemas import CreatorIn
from app.services.connect import create_onboarding_link, refresh_creator_status

router = APIRouter(prefix="/creators", tags=["creators"])


def _owned_creator(creator_id: UUID, user: dict) -> dict:
    rows = get_supabase().table("creators").select("*").eq("id", str(creator_id)).limit(1).execute().data
    if not rows:
        raise HTTPException(404, "creator_not_found")
    if rows[0].get("user_id") != user["id"]:
        raise HTTPException(403, "not_your_creator_profile")
    return rows[0]


@router.post("", status_code=201)
def create_creator(body: CreatorIn, user: dict = Depends(require_user)):
    res = get_supabase().table("creators").insert({"user_id": user["id"], "display_name": body.display_name}).execute()
    return res.data[0]


@router.post("/{creator_id}/connect")
def connect(creator_id: UUID, user: dict = Depends(require_user)):
    """Returns a Stripe hosted onboarding URL so the streamer can receive tips."""
    _owned_creator(creator_id, user)
    return {"url": create_onboarding_link(str(creator_id))}


@router.post("/{creator_id}/refresh-status")
def refresh_status(creator_id: UUID, user: dict = Depends(require_user)):
    _owned_creator(creator_id, user)
    return refresh_creator_status(str(creator_id))
