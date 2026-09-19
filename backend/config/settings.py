"""
Django settings for the IITM BS chatbot backend.

This service replaces the Cloudflare Worker (worker.js) and the FastAPI PG FAQ API.
It is an API + static-hosting service: no Django ORM models, no auth tables, no
sessions. FAQ data is read through the reused SQLAlchemy layer in pg/faq_api, so
Django itself needs no database connection (dummy backend).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Optionally load a local .env when running outside Docker (`manage.py runserver`).
try:
    from dotenv import load_dotenv

    _repo_root_env = Path(__file__).resolve().parent.parent.parent / ".env"
    if _repo_root_env.exists():
        load_dotenv(_repo_root_env)
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass

BASE_DIR = Path(__file__).resolve().parent.parent          # .../backend
REPO_ROOT = BASE_DIR.parent                                 # repo root (has pg/, static/, src/)

# Make `pg.faq_api.*` importable (shared FAQ data layer, also used by embed.py).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# SECRET_KEY intentionally unset: this service signs nothing (no sessions, auth,
# CSRF middleware or django.core.signing), and Django only reads it on use.
# If sessions/auth/CSRF/signing are ever added, restore it with a stable value
# from Secret Manager: SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
DEBUG = _bool_env("DJANGO_DEBUG", False)
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "chatbot.apps.ChatbotConfig",
]

# Every middleware below declares both sync and async support. Static files are
# served outside Django by the ASGI entrypoint so dynamic requests never cross a
# synchronous middleware bridge.
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

# No Django ORM models → no real database use. An inert in-memory SQLite keeps the
# test runner happy (no models ⇒ empty schema) while never touching disk at runtime;
# all FAQ reads go through the reused SQLAlchemy layer, not the Django ORM.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

# The ASGI entrypoint preloads the small existing static/ directory and serves
# its files at the site root without putting a sync middleware around APIs.

# ---- CORS: permissive, matching the Worker's `Access-Control-Allow-Origin: *` ----
CORS_ALLOW_ALL_ORIGINS = True

# ---- DRF: token-free, JSON-first (no browsable API auth machinery) ----
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

# ---- App logging: structured JSON to stdout (Cloud Logging captures it) ----
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    # Keep structured application events and Uvicorn access logs visible, but
    # avoid one plain-text INFO line for every outbound HTTP request.
    "loggers": {
        "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "httpcore": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
