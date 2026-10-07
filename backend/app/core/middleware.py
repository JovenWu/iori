import json

from starlette.types import ASGIApp, Receive, Scope, Send


class BodySizeLimitMiddleware:
    """Reject JSON request bodies larger than `max_bytes`.

    Content-Length is checked up front; when it's absent or lies (chunked
    transfer) the body is buffered while counting, so the cap is real either
    way. Only bodied methods go through the buffer — GET/HEAD pass through
    untouched and the response path is never intercepted, so SSE streams
    pass through unbuffered.
    """

    _BODIED = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def _too_large(self, send: Send) -> None:
        body = json.dumps({"detail": "Request body too large"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope.get("method") not in self._BODIED:
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > self.max_bytes:
                        await self._too_large(send)
                        return
                except ValueError:
                    pass  # malformed length — the buffer still enforces
                break

        # Buffer the body while counting — chunked requests carry no honest
        # Content-Length, so only the counted total is trustworthy.
        messages: list[dict] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._too_large(send)
                return
            messages.append(message)
            if not message.get("more_body"):
                break

        buffered = iter(messages)

        async def replaying_receive() -> dict:
            try:
                return next(buffered)
            except StopIteration:
                return await receive()

        await self.app(scope, replaying_receive, send)


class SecurityHeadersMiddleware:
    """Standard security headers on every response; HSTS only behind TLS."""

    def __init__(self, app: ASGIApp, hsts: bool = False):
        self.app = app
        self.headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
        ]
        if hsts:
            self.headers.append(
                (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self.headers)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
