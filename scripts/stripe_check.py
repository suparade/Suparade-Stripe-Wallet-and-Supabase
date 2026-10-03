"""Check the Stripe setup and optionally add test funds to the platform balance.

Run from the repo root with your .env loaded:
    set -a; source .env; set +a
    python -m scripts.stripe_check                         # checks key, balance, and Connect
    python -m scripts.stripe_check --add-test-funds 2000   # also adds 20.00 USD of fake money

Only works with test or sandbox keys (sk_test_...). Live keys are refused by get_stripe().
"""
import argparse
import sys

from app.stripe_utils import StripeError, as_dict, get_stripe


def money(entries) -> str:
    return ", ".join(f"{e['amount'] / 100:.2f} {e['currency'].upper()}" for e in entries) or "0.00"


def show_balance(st) -> None:
    bal = as_dict(st.Balance.retrieve())
    print(f"  available: {money(bal['available'])}   pending: {money(bal['pending'])}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--add-test-funds", type=int, metavar="CENTS", help="add fake money, in cents")
    args = parser.parse_args()

    st = get_stripe()

    print("1. API key")
    try:
        acct = as_dict(st.Account.retrieve())
    except StripeError as e:
        print(f"  FAILED: {e}")
        return 1
    print(f"  ok, account {acct['id']} (country {acct.get('country')})")

    print("2. Platform balance")
    show_balance(st)

    if args.add_test_funds:
        print(f"3. Adding {args.add_test_funds / 100:.2f} USD of test funds")
        try:
            pi = as_dict(st.PaymentIntent.create(
                amount=args.add_test_funds,
                currency="usd",
                payment_method="pm_card_bypassPending",  # test card 4000000000000077, goes straight to available
                confirm=True,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                description="Suparade test funds",
            ))
        except StripeError as e:
            print(f"  FAILED: {e}")
            return 1
        print(f"  payment {pi['id']} status: {pi['status']}")
        show_balance(st)

    print("4. Connect (creates a throwaway recipient account with Accounts v2, then closes it)")
    import stripe

    from app.config import get_settings
    from app.services.connect import recipient_account_params

    client = stripe.StripeClient(get_settings().stripe_secret_key)
    try:
        test_acct = client.v2.core.accounts.create(
            params=recipient_account_params("Connect check", "connect-check", get_settings().creator_country, "connect-check@example.com")
        )
    except StripeError as e:
        print(f"  FAILED: {e}")
        print("  If this mentions liability or acknowledgement, open")
        print("  dashboard.stripe.com/settings/connect/platform-profile in your sandbox, accept the")
        print("  loss liability acknowledgement, then run this again.")
        return 1
    try:
        client.v2.core.accounts.close(test_acct.id)
    except StripeError:
        print(f"  (could not close {test_acct.id}, it is a harmless test account)")
    print("  ok, Connect is enabled and recipient accounts can be created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
