"""ASGI entrypoint for dynamic Django routes and static browser files.

Flow: Uvicorn sends lifespan events here -> API paths go to native async
Django -> other paths use preloaded static bytes -> shutdown closes shared
HTTP and PostgreSQL connection pools.
"""
import mimetypes
import os
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application  # noqa: E402

from chatbot.services.faq import close_async_faq_engine  # noqa: E402
from chatbot.services.http_client import close_async_http_client  # noqa: E402


def _load_static_files(root):
    """Load browser assets once so serving them never blocks the event loop.

    Example: ``static/qa.js`` becomes the preloaded ``/qa.js`` response.
    """
    files = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        files[f"/{relative_path}"] = (content_type, path.read_bytes())
    if "/index.html" in files:
        files["/"] = files["/index.html"]
    return files


django_application = get_asgi_application()
STATIC_FILES = _load_static_files(_repo_root / "static")
_DJANGO_PATHS = {
    "/answer",
    "/feedback",
    "/faq",
    "/health",
    "/github-config",
    "/qa",
}


def _is_django_path(path):
    """Return whether one public path belongs to Django instead of static files."""
    return path in _DJANGO_PATHS or path.startswith("/faq/")


def _static_cors_headers(scope):
    """Return the same permissive CORS headers used by Django APIs."""
    request_headers = dict(scope.get("headers") or [])
    if b"origin" not in request_headers:
        return []
    headers = [(b"vary", b"origin"), (b"access-control-allow-origin", b"*")]
    if scope.get("method") == "OPTIONS":
        headers.extend(
            [
                (
                    b"access-control-allow-headers",
                    b"accept, authorization, content-type, user-agent, x-csrftoken, x-requested-with",
                ),
                (
                    b"access-control-allow-methods",
                    b"DELETE, GET, OPTIONS, PATCH, POST, PUT",
                ),
                (b"access-control-max-age", b"86400"),
            ]
        )
    return headers


async def serve_static(scope, receive, send):
    """Serve one preloaded browser asset through the native ASGI interface."""
    method = scope.get("method", "GET")
    request_headers = dict(scope.get("headers") or [])
    cors_headers = _static_cors_headers(scope)
    if method == "OPTIONS" and b"access-control-request-method" in request_headers:
        headers = cors_headers + [(b"content-length", b"0")]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b""})
        return

    if method not in ("GET", "HEAD"):
        body = b"Method Not Allowed"
        headers = cors_headers + [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
        ]
        await send({"type": "http.response.start", "status": 405, "headers": headers})
        await send({"type": "http.response.body", "body": body})
        return

    item = STATIC_FILES.get(scope.get("path", "/"))
    if item is None:
        content_type = "text/plain; charset=utf-8"
        body = b"Not Found"
        status = 404
    else:
        content_type, body = item
        status = 200
    headers = cors_headers + [
        (b"content-type", content_type.encode()),
        (b"content-length", str(len(body)).encode()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body})


async def _lifespan(receive, send):
    """Acknowledge Uvicorn lifecycle events and close connection pools."""
    while True:
        event = await receive()
        if event["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif event["type"] == "lifespan.shutdown":
            await close_async_http_client()
            await close_async_faq_engine()
            await send({"type": "lifespan.shutdown.complete"})
            return


async def route_application(scope, receive, send):
    """Route APIs without putting a static middleware around Django."""
    if scope["type"] == "lifespan":
        await _lifespan(receive, send)
        return
    if scope["type"] == "http" and _is_django_path(scope.get("path", "")):
        await django_application(scope, receive, send)
        return
    await serve_static(scope, receive, send)


async def application(scope, receive, send):
    """Add the response headers previously supplied by SecurityMiddleware."""
    async def send_with_security_headers(event):
        if event["type"] == "http.response.start":
            headers = list(event.get("headers", []))
            names = {name.lower() for name, _value in headers}
            if b"x-content-type-options" not in names:
                headers.append((b"x-content-type-options", b"nosniff"))
            if b"referrer-policy" not in names:
                headers.append((b"referrer-policy", b"same-origin"))
            if b"cross-origin-opener-policy" not in names:
                headers.append((b"cross-origin-opener-policy", b"same-origin"))
            event = {**event, "headers": headers}
        await send(event)

    await route_application(scope, receive, send_with_security_headers)
