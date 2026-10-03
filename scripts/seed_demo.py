"""Create a demo brand, campaign, creator and video, then print a Stripe onboarding link.

Run from the repo root with your .env loaded:
    set -a; source .env; set +a
    python -m scripts.seed_demo "https://example.com/some-video.mp4"
"""
import sys

from app.db import get_supabase
from app.services.connect import create_onboarding_link


def main(video_url: str) -> None:
    sb = get_supabase()

    brand = sb.table("brands").insert({"name": "Demo Sports Drink"}).execute().data[0]
    campaign = (
        sb.table("campaigns")
        .insert(
            {
                "brand_id": brand["id"],
                "name": "Demo brand mention campaign",
                "type": "brand_mention",
                "brand_context": "A sports drink. Count it when a creator drinks it, holds it, or says the name on camera.",
                "tipper_instructions": "Tip more for clear on camera use than for a passing mention.",
            }
        )
        .execute()
        .data[0]
    )
    # The handle is the "streamer id" typed in the Gemini detector dashboard (default: demo-streamer).
    taken = sb.table("creators").select("id").ilike("handle", "demo-streamer").execute().data
    creator_row = {"display_name": "Demo Streamer"} if taken else {"display_name": "Demo Streamer", "handle": "demo-streamer"}
    creator = sb.table("creators").insert(creator_row).execute().data[0]
    video = (
        sb.table("videos")
        .insert({"url": video_url, "platform": "demo", "title": "Demo clip", "creator_id": creator["id"]})
        .execute()
        .data[0]
    )

    print("brand_id    ", brand["id"])
    print("campaign_id ", campaign["id"])
    print("creator_id  ", creator["id"])
    print("video_id    ", video["id"])
    print("handle      ", creator.get("handle") or "(demo-streamer already taken; set creators.handle yourself)")
    print()
    print("Open this link in a browser and finish Stripe test onboarding so the creator can be paid:")
    print(create_onboarding_link(creator["id"]))
    print()
    print("Then sync status:  POST /creators/{creator_id}/refresh-status  ")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m scripts.seed_demo <video_url>")
    main(sys.argv[1])
