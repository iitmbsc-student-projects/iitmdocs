"""ASGI entrypoint for dynamic Django routes and static browser files.

Flow: Uvicorn sends lifespan events here -> API paths go to native async
Django -> other paths use preloaded static bytes -> shutdown closes shared
HTTP and PostgreSQL connection pools.
"""
import gzip
import hashlib
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

# Short TTL plus revalidation: the asset filenames are unversioned, so a long
# max-age would pin stale JS in browsers after a deploy. The ETag does the work.
_STATIC_CACHE_CONTROL = b"public, max-age=300, must-revalidate"


def _make_etag(body):
    """Return a strong ETag for one asset body."""
    return '"%s"' % hashlib.sha256(body).hexdigest()[:32]


def _load_static_files(root):
    """Load browser assets once so serving them never blocks the event loop.

    Example: ``static/qa.js`` becomes the preloaded ``/qa.js`` response.

    Each entry is ``(content_type, body, etag, gzipped_or_None)``. The gzip form
    is computed here, at preload time, so a request never pays for compression.
    """
    files = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        compressed = gzip.compress(body, 9)
        # Only keep the compressed copy when it actually helps; already
        # compressed types (images, fonts) and tiny files can get bigger.
        gzipped = compressed if len(compressed) < len(body) else None
        files[f"/{relative_path}"] = (content_type, body, _make_etag(body), gzipped)
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


def _merged_vary(cors_headers):
    """Return one Vary value covering origin (from CORS) and accept-encoding."""
    tokens = ["accept-encoding"]
    for name, value in cors_headers:
        if name.lower() != b"vary":
            continue
        for token in value.decode("latin-1").split(","):
            token = token.strip()
            if token and token.lower() not in {t.lower() for t in tokens}:
                tokens.append(token)
    return ", ".join(tokens).encode()


def _if_none_match_matches(header, etag):
    """Return whether an If-None-Match header matches etag (weak comparison)."""
    if not header:
        return False
    for candidate in header.decode("latin-1").split(","):
        candidate = candidate.strip()
        if candidate == "*":
            return True
        if candidate.startswith("W/"):
            candidate = candidate[2:].strip()
        if candidate == etag:
            return True
    return False


def _accepts_gzip(request_headers):
    """Return whether the client accepts a gzip encoded response."""
    encoding = request_headers.get(b"accept-encoding")
    if not encoding:
        return False
    return "gzip" in encoding.decode("latin-1").lower()


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
        body = b"Not Found"
        headers = cors_headers + [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
        ]
        await send({"type": "http.response.start", "status": 404, "headers": headers})
        await send({"type": "http.response.body", "body": body})
        return

    content_type, body, etag, gzipped = item
    # One Vary header only: _static_cors_headers already contributes `origin`.
    headers = [header for header in cors_headers if header[0].lower() != b"vary"]
    headers += [
        (b"content-type", content_type.encode()),
        (b"cache-control", _STATIC_CACHE_CONTROL),
        (b"etag", etag.encode()),
        (b"vary", _merged_vary(cors_headers)),
    ]

    if _if_none_match_matches(request_headers.get(b"if-none-match"), etag):
        # A 304 carries the validators and CORS headers, but no body and no
        # content-length for a body that is not being sent.
        await send({"type": "http.response.start", "status": 304, "headers": headers})
        await send({"type": "http.response.body", "body": b""})
        return

    payload = gzipped if (gzipped is not None and _accepts_gzip(request_headers)) else body
    if payload is gzipped:
        headers.append((b"content-encoding", b"gzip"))
    headers.append((b"content-length", str(len(payload)).encode()))
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": b"" if method == "HEAD" else payload})


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
            
