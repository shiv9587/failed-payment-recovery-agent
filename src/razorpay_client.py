"""
Razorpay test-mode API client wrapper — Failed Payment Recovery Agent (Track 3).

Wraps the actions our recovery_agent needs to actually execute:
    - create/resend a Payment Link (for: incorrect_otp, upi_collect_expired,
      card_declined_by_bank -> alt method, customer_cancelled nudge)
    - fetch payment link status (to check if customer completed it later)

Uses the official `razorpay` Python SDK. Requires test-mode keys in .env:
    RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
    RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx

Docs referenced: https://razorpay.com/docs/api/payments/payment-links/
"""

import os
import razorpay
from dotenv import load_dotenv

load_dotenv()

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")


class RazorpayClient:
    def __init__(self, key_id: str = None, key_secret: str = None):
        key_id = key_id or RAZORPAY_KEY_ID
        key_secret = key_secret or RAZORPAY_KEY_SECRET
        if not key_id or not key_secret:
            raise EnvironmentError(
                "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set. "
                "Copy .env.example to .env and fill in your test-mode keys."
            )
        if not key_id.startswith("rzp_test_"):
            raise EnvironmentError(
                "This project must only ever run against TEST-mode keys "
                "(rzp_test_...). Refusing to proceed with a live key."
            )
        self.client = razorpay.Client(auth=(key_id, key_secret))

    def create_payment_link(
        self,
        amount_rupees: float,
        customer_name: str,
        customer_contact: str,
        description: str,
        reference_id: str,
    ) -> dict:
        """
        Creates a new Razorpay Payment Link — this is the actual
        "recovery action" the agent executes for reasons like
        incorrect_otp, upi_collect_expired, card_declined_by_bank, etc.

        Returns the Razorpay payment link object (contains 'short_url',
        'id', 'status').
        """
        payload = {
            "amount": int(round(amount_rupees * 100)),  # paise
            "currency": "INR",
            "description": description,
            "customer": {
                "name": customer_name,
                "contact": customer_contact,
            },
            "notify": {"sms": True, "email": False},
            "reminder_enable": True,
            "reference_id": reference_id,
            "notes": {
                "source": "failed_payment_recovery_agent",
            },
        }
        return self.client.payment_link.create(payload)

    def fetch_payment_link_status(self, payment_link_id: str) -> dict:
        """Fetch current status of a payment link ('created', 'paid', 'expired', 'cancelled')."""
        return self.client.payment_link.fetch(payment_link_id)

    def cancel_payment_link(self, payment_link_id: str) -> dict:
        """Cancel a payment link — used when the recovery window expires (stopping rule)."""
        return self.client.payment_link.cancel(payment_link_id)


class MockRazorpayClient:
    """
    Drop-in replacement for RazorpayClient that doesn't hit the network.
    Useful for running the full batch quickly / offline / in CI, and as
    a fallback if API rate limits are hit during the demo.
    Mirrors the same interface so recovery_agent.py doesn't need to care
    which one it's using.
    """

    def __init__(self):
        self._counter = 0

    def create_payment_link(self, amount_rupees, customer_name,
                             customer_contact, description, reference_id):
        self._counter += 1
        return {
            "id": f"plink_mock_{self._counter:06d}",
            "short_url": f"https://rzp.io/i/mock{self._counter:06d}",
            "status": "created",
            "reference_id": reference_id,
            "amount": int(round(amount_rupees * 100)),
        }

    def fetch_payment_link_status(self, payment_link_id):
        return {"id": payment_link_id, "status": "created"}

    def cancel_payment_link(self, payment_link_id):
        return {"id": payment_link_id, "status": "cancelled"}


def get_client(use_mock: bool = False):
    """
    Factory: returns a real RazorpayClient if keys are present and
    use_mock=False, otherwise falls back to MockRazorpayClient.
    Keep this so the demo never breaks on stage due to network/rate limits.
    """
    if use_mock:
        return MockRazorpayClient()
    try:
        return RazorpayClient()
    except EnvironmentError as e:
        print(f"[warn] Falling back to MockRazorpayClient: {e}")
        return MockRazorpayClient()


if __name__ == "__main__":
    # Smoke test — uses mock by default so this never accidentally hits
    # the real API just by running the file.
    client = get_client(use_mock=True)
    link = client.create_payment_link(
        amount_rupees=499.0,
        customer_name="Test Customer",
        customer_contact="+919999999999",
        description="Retry payment - order #TEST123",
        reference_id="txn_test_0001",
    )
    print(link)
