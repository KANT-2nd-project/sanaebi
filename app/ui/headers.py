"""Streaming-safe cache and indexing policy for the mounted UI."""


class ChatHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == "/chat" or path.startswith("/chat/")
        ):
            return await self.app(scope, receive, send)

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in (b"cache-control", b"expires", b"x-robots-tag")
                ]
                message = {
                    **message,
                    "headers": headers
                    + [
                        (b"cache-control", b"no-store"),
                        (b"x-robots-tag", b"noindex, nofollow"),
                    ],
                }
            await send(message)

        await self.app(scope, receive, with_headers)
