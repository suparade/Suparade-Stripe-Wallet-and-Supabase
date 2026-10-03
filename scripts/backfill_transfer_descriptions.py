"""Give already paid tips' Stripe transfers a readable description and metadata (the agent's reason).

New transfers get these when they are created; this updates older ones. Safe to run again.

    set -a; source .env; set +a
    python -m scripts.backfill_transfer_descriptions
"""
import sys

from app.db import get_supabase
from app.services.tips import transfer_details
from app.stripe_utils import StripeError, get_stripe


def main() -> int:
    st = get_stripe()
    tips = (
        get_supabase().table("tips").select("*").eq("status", "paid").not_.is_("stripe_transfer_id", "null")
        .order("created_at").limit(200).execute().data
    )
    failed = 0
    for tip in tips:
        details = transfer_details(tip)
        try:
            st.Transfer.modify(tip["stripe_transfer_id"], description=details["description"],
                               metadata=details["metadata"])
            print(f"  {tip['stripe_transfer_id']}  {details['description'][:90]}")
        except StripeError as e:
            failed += 1
            print(f"  {tip['stripe_transfer_id']}  FAILED: {e}")
    print(f"updated {len(tips) - failed} of {len(tips)} transfers")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
