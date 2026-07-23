"""HMAC-SHA256 request signing for the Delta Exchange India REST API.

Per Delta's documented scheme, the signature payload is:
    method + timestamp + request_path + query_string + body
where query_string includes a leading "?" when parameters are present
(empty string otherwise) and body is the raw JSON string sent with the
request (empty string for requests with no body). Signatures are only
valid for a few seconds, so the timestamp must be generated immediately
before the request is sent.
"""
import hashlib
import hmac
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode


def generate_signature(secret: str, message: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def build_query_string(params: Optional[Dict[str, Any]]) -> str:
    if not params:
        return ""
    return "?" + urlencode(params)


def sign_request(
    api_secret: str,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: str = "",
) -> Dict[str, str]:
    """Return the timestamp + signature headers for a request."""
    timestamp = str(int(time.time()))
    query_string = build_query_string(params)
    message = method.upper() + timestamp + path + query_string + body
    signature = generate_signature(api_secret, message)
    return {"timestamp": timestamp, "signature": signature}
