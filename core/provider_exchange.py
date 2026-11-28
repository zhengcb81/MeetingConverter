"""Describe the provider exchange before decoding its content."""

from __future__ import annotations

from contextlib import suppress
import json
from logging import Logger
from urllib.error import HTTPError

from core.local_diagnostics import record_event, record_failure


class ProviderExchange:
    def __init__(self, stage: str, attempt: int) -> None:
        self.stage = stage
        self.attempt = attempt
        self.response_received = False
        self.http_status = None
        self._explicit_rejection = False

    @property
    def may_retry(self) -> bool:
        """Keep legacy retries before evidence of an accepted response."""
        return not self.response_received or self._explicit_rejection

    def _receive_headers(self, status) -> None:
        self.response_received = True
        self.http_status = status if type(status) is int and 100 <= status <= 599 else None
        record_event(self.stage, "response_headers", request_attempt=self.attempt, http_status=self.http_status)

    def record_failure(self, error: BaseException, *, notice: tuple[Logger, str] | None = None) -> None:
        record_failure(
            self.stage, error, notice=notice, request_attempt=self.attempt,
            response_received=self.response_received, http_status=self.http_status,
        )

    def read_json(self, opener, request, timeout: float):
        record_event(self.stage, "dispatch_started", request_attempt=self.attempt)
        try:
            response = opener(request, timeout=timeout)
        except HTTPError as rejection:
            self._explicit_rejection = True
            try:
                self._receive_headers(rejection.code)
            finally:
                with suppress(OSError):
                    rejection.close()
            raise
        self._receive_headers(getattr(response, "status", None))
        with response as stream:
            body = stream.read()
        return json.loads(body.decode("utf-8"))
