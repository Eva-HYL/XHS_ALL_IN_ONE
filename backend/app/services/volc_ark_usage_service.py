from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
from typing import Any
from urllib.parse import urlencode

import requests


class VolcArkUsageError(RuntimeError):
    """Raised when Ark's control-plane usage API cannot be queried."""


class VolcArkUsageClient:
    """Read account-level inference usage from Ark's public control-plane API."""

    _HOST = "open.volcengineapi.com"
    _REGION = "cn-beijing"
    _SERVICE = "ark"
    _VERSION = "2024-01-01"

    def __init__(self, access_key: str | None = None, secret_key: str | None = None) -> None:
        self._access_key = access_key or os.getenv("VOLC_ACCESS_KEY", "")
        self._secret_key = secret_key or os.getenv("VOLC_SECRET_KEY", "")
        if not self._access_key or not self._secret_key:
            raise VolcArkUsageError("Volcano Ark usage sync is not configured")

    @staticmethod
    def _sign(key: bytes, value: str) -> bytes:
        return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()

    def _headers(self, query: str, body: bytes) -> dict[str, str]:
        now = dt.datetime.now(dt.timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        headers = {
            "content-type": "application/json; charset=utf-8",
            "host": self._HOST,
            "x-content-sha256": payload_hash,
            "x-date": timestamp,
        }
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in sorted(headers))
        canonical_request = f"POST\n/\n{query}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        scope = f"{date}/{self._REGION}/{self._SERVICE}/request"
        string_to_sign = "HMAC-SHA256\n" + timestamp + "\n" + scope + "\n" + hashlib.sha256(
            canonical_request.encode("utf-8")
        ).hexdigest()
        signing_key = self._sign(
            self._sign(
                self._sign(self._sign(self._secret_key.encode("utf-8"), date), self._REGION),
                self._SERVICE,
            ),
            "request",
        )
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            **headers,
            "Authorization": (
                f"HMAC-SHA256 Credential={self._access_key}/{scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            ),
        }

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def fetch_inference_usage(self, *, days: int = 30) -> dict[str, Any]:
        if not 1 <= days <= 90:
            raise ValueError("days must be between 1 and 90")
        end = dt.date.today()
        payload = {
            "QueryInterval": "Day",
            "StartTime": (end - dt.timedelta(days=days)).isoformat(),
            "EndTime": end.isoformat(),
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        query = urlencode(sorted({"Action": "GetInferenceUsage", "Version": self._VERSION}.items()))
        response = requests.post(
            f"https://{self._HOST}/?{query}",
            data=body,
            headers=self._headers(query, body),
            timeout=20,
        )
        try:
            document = response.json()
        except ValueError as exc:
            raise VolcArkUsageError("Volcano Ark usage service returned an invalid response") from exc
        error = (document.get("ResponseMetadata") or {}).get("Error") or document.get("error")
        if response.status_code >= 400 or error:
            message = (error or {}).get("Message") or (error or {}).get("message") or "request failed"
            raise VolcArkUsageError(f"Volcano Ark usage sync failed: {message}")

        result = document.get("Result") or {}
        names = [field.get("Name") for field in result.get("Fields", []) if field.get("Name")]
        items: list[dict[str, int | str]] = []
        for row in result.get("Data", []):
            values = dict(zip(names, row))
            items.append({
                "day": str(values.get("Day", "")),
                "input_tokens": self._as_int(values.get("InputTokens")),
                "output_tokens": self._as_int(values.get("OutputTokens")),
                "image_count": self._as_int(values.get("ImageCount")),
                "request_count": self._as_int(values.get("ReqCnt")),
            })
        totals = {
            key: sum(int(item[key]) for item in items)
            for key in ("input_tokens", "output_tokens", "image_count", "request_count")
        }
        return {
            "source": "volc_ark",
            "interval_days": days,
            "items": items,
            "totals": totals,
        }
