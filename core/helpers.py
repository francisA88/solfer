import requests


def is_valid_flutterwave_webhook(raw_body: str, signature: str, secret_hash: str) -> bool:
    import base64, hmac, hashlib
    # Python's hmac requires byte-strings, so we encode the strings to utf-8
    secret_bytes = secret_hash.encode('utf-8')
    body_bytes = raw_body.encode('utf-8')

    # Create the HMAC SHA256 hash
    computed_hmac = hmac.new(secret_bytes, body_bytes, hashlib.sha256).digest()

    # Base64 encode the result and convert it back to a string for comparison
    computed_signature = base64.b64encode(computed_hmac).decode('utf-8')

    # hmac.compare_digest is used here instead of '==' to prevent timing attacks
    return hmac.compare_digest(computed_signature, signature)


