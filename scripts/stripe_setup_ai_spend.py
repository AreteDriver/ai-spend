#!/usr/bin/env python3
"""Create AI Spend Pro products and prices on Stripe.

Prerequisites:
    pip install stripe
    export STRIPE_SECRET_KEY=sk_test_...  (or sk_live_...)

Usage:
    python scripts/stripe_setup_ai_spend.py           # Creates product + both prices
    python scripts/stripe_setup_ai_spend.py --live     # Confirm live mode

This creates:
    - Product: "AI Spend Pro"
    - Price: $8/month (recurring)
    - Price: $69/year (recurring)
    - Payment Links for both (printed to stdout)

The payment links include metadata.product = "ai-spend" so the shared
license server webhook at cmdf-license.fly.dev routes fulfillment correctly.
"""

import argparse
import os
import sys

try:
    import stripe
except ImportError:
    print("Install stripe: pip install stripe", file=sys.stderr)  # noqa: T201
    sys.exit(1)

PRODUCT_SLUG = "ai-spend"
REDIRECT_URL = "https://github.com/AreteDriver/ai-spend?purchased=true"


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Stripe for AI Spend Pro")
    parser.add_argument("--live", action="store_true", help="Confirm live mode (not test)")
    args = parser.parse_args()

    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        print("Set STRIPE_SECRET_KEY environment variable", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    if key.startswith("sk_live_") and not args.live:
        print(  # noqa: T201
            "Live key detected. Pass --live to confirm.",
            file=sys.stderr,
        )
        sys.exit(1)

    stripe.api_key = key

    # Create product
    product = stripe.Product.create(
        name="AI Spend Pro",
        description=(
            "Premium features for AI Spend: unlimited provider tracking, "
            "CSV/JSON export, and advanced cost analytics."
        ),
        metadata={"app": PRODUCT_SLUG, "product": PRODUCT_SLUG, "tier": "pro"},
    )
    print(f"Product: {product.id}")  # noqa: T201

    # Monthly price
    monthly = stripe.Price.create(
        product=product.id,
        unit_amount=800,  # $8.00
        currency="usd",
        recurring={"interval": "month"},
        metadata={"plan": "monthly"},
    )
    print(f"Monthly price: {monthly.id} ($8/mo)")  # noqa: T201

    # Yearly price
    yearly = stripe.Price.create(
        product=product.id,
        unit_amount=6900,  # $69.00
        currency="usd",
        recurring={"interval": "year"},
        metadata={"plan": "yearly"},
    )
    print(f"Yearly price: {yearly.id} ($69/yr)")  # noqa: T201

    # Payment links — metadata.product is critical for webhook routing
    monthly_link = stripe.PaymentLink.create(
        line_items=[{"price": monthly.id, "quantity": 1}],
        after_completion={
            "type": "redirect",
            "redirect": {"url": REDIRECT_URL},
        },
        metadata={
            "app": PRODUCT_SLUG,
            "product": PRODUCT_SLUG,
            "plan": "monthly",
            "tier": "pro",
        },
    )
    print(f"\nMonthly payment link: {monthly_link.url}")  # noqa: T201

    yearly_link = stripe.PaymentLink.create(
        line_items=[{"price": yearly.id, "quantity": 1}],
        after_completion={
            "type": "redirect",
            "redirect": {"url": REDIRECT_URL},
        },
        metadata={
            "app": PRODUCT_SLUG,
            "product": PRODUCT_SLUG,
            "plan": "yearly",
            "tier": "pro",
        },
    )
    print(f"Yearly payment link: {yearly_link.url}")  # noqa: T201

    print(  # noqa: T201
        "\nDone. Add these payment links to your README or landing page."
        "\nFulfillment is automatic via the webhook at cmdf-license.fly.dev."
        f"\nThe webhook reads metadata.product = '{PRODUCT_SLUG}' to generate"
        "\nan ASPD-prefixed key and email it to the customer."
    )


if __name__ == "__main__":
    main()
