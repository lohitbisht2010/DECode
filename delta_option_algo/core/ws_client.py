"""WebSocket client for Delta Exchange India real-time market/account data.

The REST API is polling-based and rate-limited, which is too slow for
tracking option premiums and open-position P&L tick by tick. Delta's
WebSocket feed pushes ticker and (once authenticated) order/position
updates over a single persistent connection, which is what the strategy
loop actually watches. REST is still used for one-shot actions (placing
orders, reading balances) since it's simpler for request/response calls.

Reconnects automatically with backoff and re-subscribes to whatever
channels were active before the drop.
"""
import json
import threading
import time
from typing import Callable, Dict, List, Optional

import websocket

from delta_option_algo.core.auth import generate_signature
from delta_option_algo.core.logger import get_logger

log = get_logger(__name__)

# Auth handshake path per Delta's documented websocket signing convention:
# signature = HMAC-SHA256(secret, "GET" + timestamp + "/live")
_WS_AUTH_METHOD = "GET"
_WS_AUTH_PATH = "/live"


class DeltaWebSocketClient:
    def __init__(self, ws_url: str, api_key: str = "", api_secret: str = ""):
        self.ws_url = ws_url
        self.api_key = api_key
        self.api_secret = api_secret

        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = threading.Event()

        self._subscriptions: Dict[str, List[str]] = {}
        self._on_message_handlers: List[Callable[[dict], None]] = []
        self._reconnect_delay = 1

    # -- public API -------------------------------------------------------------

    def on_message(self, handler: Callable[[dict], None]) -> None:
        self._on_message_handlers.append(handler)

    def subscribe(self, channel: str, symbols: List[str]) -> None:
        self._subscriptions.setdefault(channel, [])
        for s in symbols:
            if s not in self._subscriptions[channel]:
                self._subscriptions[channel].append(s)
        if self._connected.is_set():
            self._send_subscribe(channel, symbols)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            self._ws.close()
        if self._thread:
            self._thread.join(timeout=5)

    def wait_until_connected(self, timeout: float = 10) -> bool:
        return self._connected.wait(timeout)

    # -- internals ----------------------------------------------------------------

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            self._ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._handle_open,
                on_message=self._handle_message,
                on_error=self._handle_error,
                on_close=self._handle_close,
            )
            self._ws.run_forever(ping_interval=25, ping_timeout=10)
            if self._stop.is_set():
                break
            log.warning("WebSocket disconnected, reconnecting in %ss", self._reconnect_delay)
            time.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 30)

    def _handle_open(self, ws) -> None:
        log.info("WebSocket connected to %s", self.ws_url)
        self._reconnect_delay = 1
        self._connected.set()
        if self.api_key and self.api_secret:
            self._authenticate()
        for channel, symbols in self._subscriptions.items():
            self._send_subscribe(channel, symbols)

    def _authenticate(self) -> None:
        timestamp = str(int(time.time()))
        signature = generate_signature(
            self.api_secret, _WS_AUTH_METHOD + timestamp + _WS_AUTH_PATH
        )
        auth_msg = {
            "type": "auth",
            "payload": {"api-key": self.api_key, "signature": signature, "timestamp": timestamp},
        }
        self._ws.send(json.dumps(auth_msg))

    def _send_subscribe(self, channel: str, symbols: List[str]) -> None:
        msg = {
            "type": "subscribe",
            "payload": {"channels": [{"name": channel, "symbols": symbols}]},
        }
        self._ws.send(json.dumps(msg))
        log.info("Subscribed to %s: %s", channel, symbols)

    def _handle_message(self, ws, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            log.warning("Non-JSON WS message: %s", message[:200])
            return
        for handler in self._on_message_handlers:
            try:
                handler(data)
            except Exception:
                log.exception("Error in WS message handler")

    def _handle_error(self, ws, error) -> None:
        log.error("WebSocket error: %s", error)

    def _handle_close(self, ws, status_code, msg) -> None:
        log.warning("WebSocket closed: %s %s", status_code, msg)
        self._connected.clear()
