
import requests
from datetime import datetime, timezone
import os
import time

import pathlib
import sys

sys.path.insert(0, pathlib.Path(__file__).parent.as_posix())

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

import db_api


BASE_URL = 'https://f4bexperience.flutterwave.com'  # Base URL for Flutterwave API
DEBUG_BASE_URL = "https://devel"


class AccessToken:
    def __init__(self):
        self.access_token: str = None
        self.expires_in: int = None
        self.time_created: datetime = None

    def still_valid(self) -> bool:
        if not self.access_token or not self.expires_in or not self.time_created:
            return False
        elapsed = (datetime.now(timezone.utc) - self.time_created).total_seconds()
        return elapsed < self.expires_in - 60  # Consider token expired if within 60 seconds of expiry    # access_token = flw_service._get_access_token()
    # if not access_token:
    #     return jsonify(error="Failed to generate details due to an internal error. It's our fault."), 505


class FlutterwaveService:
    def __init__(self, client_id: str = None, client_secret: str = None):
        self.client_id = client_id or os.getenv("FLUTTERWAVE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("V4_FLUTTERWAVE_CLIENT_SECRET")
        self.access_token_manager = AccessToken()
        self.transfer_status_check_interval_seconds = 5  # Interval to check transfer status
        self.scheduler = BackgroundScheduler(
            jobstores={'default': MemoryJobStore()},
            executors={'default': ThreadPoolExecutor(max_workers=10)},
            job_defaults={'coalesce': False, 'max_instances': 3}
        )
        self.scheduler.start()
        self._active_checkers = {}  # Track active checker jobs by transaction reference

    def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if not self.access_token_manager.still_valid():
            token_url = 'https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token'
            payload = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'client_credentials'
            }
            response = requests.post(
                token_url, 
                data=payload, 
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            if not response.ok:
                print("Error obtaining access token:", response.status_code, response.text)
                return None
            data = response.json()
            self.access_token_manager.access_token = data.get('access_token')
            self.access_token_manager.expires_in = data.get('expires_in')
            self.access_token_manager.time_created = datetime.now(timezone.utc)
        return self.access_token_manager.access_token

    def create_or_get_customer(self, first_name: str, last_name: str, email: str) -> dict:
        """Create a new Flutterwave customer."""
        access_token = self._get_access_token()
        if not access_token:
            print("Failed to get access token for customer creation.")
            return None

        customer_url = f'{BASE_URL}/customers'
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-Idempotency-Key': os.urandom(16).hex(),
            'Authorization': f'Bearer {access_token}'
        }
        print(first_name, last_name, email)
        payload = {
            "name": {
                "first": first_name,
                "last": last_name
            },
            "email": email
        }
        # id_from_db = db_api.get_customer_id(email)
        # First check from database if the customer id exists
        # if id_from_db:
        #     return {"data": {"id":id_from_db}}
        response = requests.post(customer_url, json=payload, headers=headers)
        if not response.ok:
            print("Error creating customer:", response.status_code, response.text)
            if response.status_code == 409:
                print("Searching for existing customer...")
                response2 = requests.post(f'{BASE_URL}/customers/search?page=1&size=10',
                    headers={
                        "Content-Type": "application/json",
                        "x-trace-id": os.urandom(25).hex(),
                        'Authorization': f'Bearer {access_token}'
                    },
                    json={"email": email} 
                )
                if not response2.ok:
                    print("An error occurred while searching.")
                    print(response2.status_code, response2.text)
                    return ""
                return response2.json()["data"][0]["id"]
            return ""

        cid = response.json()["data"]["id"]
        db_api.save_customer_id(email, cid)
        return cid

    def generate_transfer_details(self, recipient_email: str, amount: float, name: str, narration: str) -> dict:
        """Generate virtual account transfer details for a recipient."""
        access_token = self._get_access_token()
        if not access_token:
            print("Failed to get access token for transfer generation.")
            return None

        transfer_url = f'{BASE_URL}/virtual-accounts'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'X-Idempotency-Key': os.urandom(16).hex(),
            'Content-Type': 'application/json'
        }
        transaction_reference = os.urandom(16).hex()

        name_parts = name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[-1] if len(name_parts) > 1 else first_name

        customer_id = self.create_or_get_customer(first_name, last_name, recipient_email)
        if not customer_id:
            print("Failed to create customer for transfer.")
            return None

        payload = {
            "reference": transaction_reference,
            "customer_id": customer_id,
            "expiry": 1800,  # Expiry time in minutes
            "amount": amount,
            "currency": "NGN",
            "account_type": "dynamic",
            "narration": narration,
            "bank_code": "090567"
        }

        response = requests.post(transfer_url, json=payload, headers=headers)
        if not response.ok:
            print("Error generating transfer details:", response.status_code, response.text)
            return None

        data = response.json()["data"]
        print(data)
        return {
            "account_number": data["account_number"],
            "account_bank_name": data["account_bank_name"],
            "amount": data["amount"],
            "currency": data["currency"],
            "reference": data["reference"]
        }

    def _check_transfer_status_once(self, tx_ref: str) -> dict:
        """Check the status of a single transfer. Returns status data or None."""
        access_token = self._get_access_token()
        if not access_token:
            print("Failed to get access token for status check.")
            return None

        status_url = f'{BASE_URL}/virtual-accounts/{tx_ref}'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        response = requests.get(status_url, headers=headers)
        if not response.ok:
            print(f"Error checking transfer status for {tx_ref}:", response.status_code, response.text)
            return None

        return response.json()

    def _transfer_status_checker(self, tx_ref: str, on_complete=None, on_pending=None, max_checks: int = None):
        """Internal method that runs periodically to check transfer status."""
        print(f"[{datetime.now()}] Checking transfer status for: {tx_ref}")

        status_data = self._check_transfer_status_once(tx_ref)
        if not status_data:
            return

        status = status_data.get("data", {}).get("status", "unknown")
        print(f"Transfer {tx_ref} status: {status}")

        # Check if completed or failed (terminal states)
        if status in ("completed", "successful", "paid"):
            print(f"Transfer {tx_ref} is COMPLETED!")
            if on_complete:
                on_complete(tx_ref, status_data)
            self.stop_transfer_status_checker(tx_ref)
            return

        if status in ("failed", "cancelled", "expired"):
            print(f"Transfer {tx_ref} has FAILED with status: {status}")
            if on_complete:
                on_complete(tx_ref, status_data)
            self.stop_transfer_status_checker(tx_ref)
            return

        # Still pending
        if on_pending:
            on_pending(tx_ref, status_data)

        # Track check count for max_checks limit
        job_id = f"transfer_checker_{tx_ref}"
        job = self.scheduler.get_job(job_id)
        if job and max_checks:
            # We can't easily track check count without external state,
            # so we handle max_checks via a simple approach
            pass

    def start_transfer_status_checker(self, tx_ref: str, on_complete=None, on_pending=None, 
                                       interval_seconds: int = None, max_checks: int = None):
        """
        Start a background scheduler job to periodically check transfer status.

        Args:
            tx_ref: Transaction reference to monitor
            on_complete: Callback function(tx_ref, status_data) called when transfer completes
            on_pending: Callback function(tx_ref, status_data) called on each pending check
            interval_seconds: How often to check (defaults to class setting)
            max_checks: Maximum number of checks before auto-stopping (None = unlimited)
        """
        interval = interval_seconds or self.transfer_status_check_interval_seconds
        job_id = f"transfer_checker_{tx_ref}"

        # Stop existing checker for this tx_ref if any
        if job_id in self._active_checkers:
            self.stop_transfer_status_checker(tx_ref)

        # Wrap the checker to support max_checks
        check_count = [0]  # Use list for mutable closure

        def wrapped_checker():
            check_count[0] += 1
            if max_checks and check_count[0] > max_checks:
                print(f"Max checks ({max_checks}) reached for {tx_ref}. Stopping checker.")
                self.stop_transfer_status_checker(tx_ref)
                return
            self._transfer_status_checker(tx_ref, on_complete, on_pending)

        job = self.scheduler.add_job(
            wrapped_checker,
            'interval',
            seconds=interval,
            id=job_id,
            replace_existing=True
        )
        self._active_checkers[tx_ref] = job
        print(f"Started transfer status checker for {tx_ref} (every {interval}s)")

        # Run first check immediately
        wrapped_checker()

        return job

    def stop_transfer_status_checker(self, tx_ref: str):
        """Stop the background checker for a specific transaction."""
        job_id = f"transfer_checker_{tx_ref}"
        try:
            self.scheduler.remove_job(job_id)
            if tx_ref in self._active_checkers:
                del self._active_checkers[tx_ref]
            print(f"Stopped transfer status checker for {tx_ref}")
        except Exception as e:
            print(f"No active checker found for {tx_ref} or error stopping: {e}")

    def stop_all_checkers(self):
        """Stop all active transfer status checkers."""
        for tx_ref in list(self._active_checkers.keys()):
            self.stop_transfer_status_checker(tx_ref)

    def shutdown(self):
        """Shutdown the scheduler and clean up resources."""
        self.stop_all_checkers()
        self.scheduler.shutdown()
        print("FlutterwaveService scheduler shut down.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    # Initialize service with credentials from environment
    service = FlutterwaveService()

    test_email = "beans@food.com"
    test_name = "Bean Food"

    # Generate transfer details
    payment_details = service.generate_transfer_details(
        test_email,
        float(os.environ.get("PAYMENT_AMOUNT_NGN", 200)),
        test_name,
        os.environ.get("NARRATION", "Test payment")
    )
    print("Payment Details:", payment_details)

    if payment_details:
        tx_ref = payment_details["reference"]

        # Define callbacks
        def on_complete(ref, data):
            print(f"\n✅ CALLBACK: Transfer {ref} completed!")
            print(f"Data: {data}")

        def on_pending(ref, data):
            print(f"⏳ CALLBACK: Transfer {ref} still pending...")

        # Start checking status every 20 seconds, max 10 checks
        service.start_transfer_status_checker(
            tx_ref,
            on_complete=on_complete,
            on_pending=on_pending,
            interval_seconds=20,
            max_checks=10
        )

        # Keep main thread alive to let scheduler run
        try:
            print("\nMonitoring transfer status. Press Ctrl+C to stop...")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            service.shutdown()
