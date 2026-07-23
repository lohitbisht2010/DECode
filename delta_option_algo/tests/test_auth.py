import hashlib
import hmac

from delta_option_algo.core.auth import build_query_string, generate_signature, sign_request


def test_generate_signature_matches_manual_hmac():
    secret = "my-secret"
    message = "GET1700000000/v2/orders"
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    assert generate_signature(secret, message) == expected


def test_build_query_string_empty():
    assert build_query_string(None) == ""
    assert build_query_string({}) == ""


def test_build_query_string_with_params():
    qs = build_query_string({"product_id": 27})
    assert qs == "?product_id=27"


def test_sign_request_returns_timestamp_and_signature():
    headers = sign_request("secret", "GET", "/v2/orders", params={"product_id": 27}, body="")
    assert "timestamp" in headers
    assert "signature" in headers
    assert len(headers["signature"]) == 64  # hex-encoded sha256
