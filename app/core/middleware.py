"""Request-ID middleware: attaches a correlation ID to every request and response."""

import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware), so it adds no per-request task overhead."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._incoming_request_id(scope) or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            structlog.contextvars.clear_contextvars()

    @staticmethod
    def _incoming_request_id(scope: Scope) -> str | None:
        # TODO(you): Read the incoming X-Request-ID header from scope["headers"]
        # (a list of (bytes, bytes) tuples, names already lowercased). Return it
        # only if it is a sane value: at most 64 chars, and only letters, digits
        # and hyphens. Otherwise return None so we generate a new ID. Why the
        # validation? Untrusted clients can otherwise inject arbitrary text into
        # your logs (log injection). Hint: a compiled regex or str.isalnum() per
        # character both work.
        return None
