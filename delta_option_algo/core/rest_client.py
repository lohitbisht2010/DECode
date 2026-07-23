"""Thin, explicit REST wrapper for the Delta Exchange India API.

Only the endpoints the strategy actually needs are implemented, so the
request/response shape stays easy to reason about instead of hiding behind
a generic passthrough.
"""
import json
from typing import Any, Dict, List, Optional

import requests

from delta_option_algo.core.auth import sign_request
from delta_option_algo.core.logger import get_logger

log = get_logger(__name__)


class DeltaApiError(RuntimeError):
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"Delta API error [{status_code}]: {payload}")


class DeltaRestClient:
    def __init__(self, base_url: str, api_key: str, api_secret: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.session = requests.Session()

    # -- core request plumbing -------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        auth: bool = True,
    ) -> Any:
        body = json.dumps(json_body, separators=(",", ":")) if json_body else ""
        headers = {"Content-Type": "application/json", "User-Agent": "delta-option-algo/1.0"}

        if auth:
            if not self.api_key or not self.api_secret:
                raise DeltaApiError(0, "Missing DELTA_API_KEY/DELTA_API_SECRET for an authenticated call")
            headers["api-key"] = self.api_key
            headers.update(sign_request(self.api_secret, method, path, params, body))

        url = self.base_url + path
        response = self.session.request(
            method=method,
            url=url,
            params=params,
            data=body if body else None,
            headers=headers,
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            raise DeltaApiError(response.status_code, response.text)

        if not response.ok or payload.get("success") is False:
            raise DeltaApiError(response.status_code, payload)
        return payload.get("result", payload)

    # -- market data (public) ---------------------------------------------------

    def get_products(self, contract_types: Optional[str] = None, states: str = "live") -> List[Dict]:
        params = {"states": states}
        if contract_types:
            params["contract_types"] = contract_types
        return self._request("GET", "/v2/products", params=params, auth=False)

    def get_option_chain(self, underlying_asset_symbol: str, expiry_date: str) -> List[Dict]:
        """expiry_date format: DD-MM-YYYY (as required by Delta's tickers endpoint)."""
        params = {
            "contract_types": "call_options,put_options",
            "underlying_asset_symbols": underlying_asset_symbol,
            "expiry_date": expiry_date,
        }
        return self._request("GET", "/v2/tickers", params=params, auth=False)

    def get_ticker(self, symbol: str) -> Dict:
        return self._request("GET", f"/v2/tickers/{symbol}", auth=False)

    # -- account (private) -------------------------------------------------------

    def get_balances(self) -> List[Dict]:
        return self._request("GET", "/v2/wallet/balances")

    def get_positions(self, product_id: Optional[int] = None) -> Any:
        params = {"product_id": product_id} if product_id else None
        return self._request("GET", "/v2/positions", params=params)

    def get_live_orders(self, product_id: Optional[int] = None) -> List[Dict]:
        params = {"product_id": product_id} if product_id else None
        return self._request("GET", "/v2/orders", params=params)

    # -- trading (private) --------------------------------------------------------

    def place_order(
        self,
        product_id: int,
        size: int,
        side: str,
        order_type: str = "limit_order",
        limit_price: Optional[str] = None,
        time_in_force: str = "gtc",
        reduce_only: bool = False,
        stop_loss_order: Optional[Dict[str, Any]] = None,
        take_profit_order: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        body: Dict[str, Any] = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "reduce_only": reduce_only,
        }
        if limit_price is not None:
            body["limit_price"] = limit_price
        if stop_loss_order:
            body["stop_loss_order"] = stop_loss_order
        if take_profit_order:
            body["take_profit_order"] = take_profit_order
        return self._request("POST", "/v2/orders", json_body=body)

    def cancel_order(self, product_id: int, order_id: int) -> Dict:
        body = {"product_id": product_id, "id": order_id}
        return self._request("DELETE", "/v2/orders", json_body=body)

    def cancel_all_orders(self, product_id: Optional[int] = None) -> Dict:
        body = {"product_id": product_id} if product_id else {}
        return self._request("DELETE", "/v2/orders/all", json_body=body)

    def close_position(self, product_id: int, size: int, side: str) -> Dict:
        """Square off a position with a reduce-only market order."""
        return self.place_order(
            product_id=product_id,
            size=size,
            side=side,
            order_type="market_order",
            reduce_only=True,
        )
