#!/usr/bin/env python3
"""Write ``SECRETS.local.md``: every credential this project uses, in one file.

Why a script and not a paragraph in the README: a committed file is the wrong
home for live credentials. ``.env`` already holds them, it is git-ignored, and
this script renders a readable inventory from it, so there is one place to look
without ever committing a value.

The output file is git-ignored as well, so it cannot be committed by accident.

Usage:
    python scripts/write_secrets_doc.py            # write/refresh the file
    python scripts/write_secrets_doc.py --show     # also print values to stdout
    python scripts/write_secrets_doc.py --check    # report drift, write nothing

``--check`` exits non-zero when ``.env`` has changed since the file was written,
which makes it usable as a pre-flight check in a deploy pipeline.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
OUT_FILE = ROOT / "SECRETS.local.md"

# Key, what it is, what to do about it. Anything marked secret is never committed.
# Set of the names that really are secrets. CORS_ORIGINS and DATABASE_URL are
# listed below because a deployer needs them, not because they belong here.
SECRET_NAMES: set[str] = {
    "JWT_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "NVIDIA_API_KEY",
    "MARKET_DATA_API_KEY",
    "LOGISTICS_API_KEY",
    "REDIS_URL",
}

SECRETS: list[tuple[str, str, str]] = [
    ("JWT_SECRET_KEY", "Signing key for every access and refresh token.", "openssl rand -hex 32"),
    (
        "POSTGRES_PASSWORD",
        "Password for the PostgreSQL role the API connects as.",
        "openssl rand -base64 18  (then ALTER ROLE inside the database)",
    ),
    ("NVIDIA_API_KEY", "NVIDIA NIM key for the AI assistant. Empty means the rules engine.", "console.nvidia.com"),
    ("MARKET_DATA_API_KEY", "Market data provider key. Unused while MARKET_DATA_PROVIDER=demo.", "provider dashboard"),
    ("LOGISTICS_API_KEY", "Logistics provider key. Unused while LOGISTICS_PROVIDER=demo.", "provider dashboard"),
    ("REDIS_URL", "Redis for caching and rate limiting. Unset means both are off.", "redis://user:pass@host:6379/0"),
    ("CORS_ORIGINS", "Browser origins allowed to call the API. Not a secret; wrong values are a risk.", "comma-separated list"),
    ("DATABASE_URL", "Full database URL. Composed from the POSTGRES_* parts when empty.", "leave empty and set the parts"),
]

DEMO_PASSWORD = "Demo@1234"

# Everything else that shapes a deployment. Not secret, but a deployer needs it.
DEPLOYMENT: list[tuple[str, str]] = [
    ("ENVIRONMENT", "development | test | staging | production. Production refuses to start without a JWT key."),
    ("POSTGRES_USER", "Role the API authenticates as."),
    ("POSTGRES_DB", "Database name."),
    ("FRONTEND_PORT", "Host port nginx is published on. The stack is one origin, so CORS is not consulted."),
    ("DEMO_MODE", "true seeds demo accounts and synthetic prices and shows the demo banner. false for real use."),
    ("SEED_ON_START", "false skips seeding entirely. Only reference data is loaded when DEMO_MODE=false."),
    ("DOCS_ENABLED", "false hides /api/docs and /api/redoc. Turn off on a public deployment."),
    ("RATE_LIMIT_ENABLED", "Declared but unread: there is no limiter in the code. Compose sets it true and nothing acts on it. Limit at the proxy."),
    ("MEDIA_ROOT", "Unused: there is no upload endpoint, so nothing needs a writable media directory."),
    ("VITE_SHOW_DEMO_ACCOUNTS", "Whether the sign-in screen lists the demo accounts. Baked into the bundle."),
    ("VITE_API_BASE_URL", "Not read by the app today: the client is hardcoded to the same origin, /api/v1."),
    ("VITE_BACKEND_ORIGIN", "Dev-server proxy target only. Ignored in a production build."),
]


def parse_env(path: pathlib.Path) -> dict[str, str]:
    """Read a KEY=VALUE file, ignoring comments and blank lines."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def database_url(values: dict[str, str]) -> str:
    """The URL the API actually uses, mirroring core.config.resolved_database_url."""
    explicit = values.get("DATABASE_URL")
    if explicit:
        return explicit
    user = values.get("POSTGRES_USER", "kisan")
    password = values.get("POSTGRES_PASSWORD", "")
    host = values.get("POSTGRES_HOST", "localhost")
    port = values.get("POSTGRES_PORT", "5432")
    name = values.get("POSTGRES_DB", "kisansaathi")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def redact(value: str) -> str:
    """Enough of a value to recognise it, not enough to use it."""
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def render(values: dict[str, str]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out: list[str] = []
    out.append("# Local secrets — git-ignored, never commit or share this file\n")
    out.append(
        f"Generated by `scripts/write_secrets_doc.py` from `.env` at {stamp}.\n\n"
        "This is a convenience copy of the credentials in `.env`, written in readable\n"
        "form because `.env` is not. Refresh it with `make secrets` after changing\n"
        "anything, and delete it when you share a screenshot of your terminal.\n"
    )

    out.append("## Credentials\n")
    out.append("| Variable | Value | What it is |")
    out.append("| --- | --- | --- |")
    for key, what, _ in SECRETS:
        out.append(f"| `{key}` | `{values.get(key) or '(empty)'}` | {what} |")
    out.append(
        f"| `DEMO_PASSWORD` | `{DEMO_PASSWORD}` | Password for all eight seeded demo "
        "accounts. Public by design: the sign-in screen prints it, and only when "
        "`DEMO_MODE=true`.\n"
    )

    out.append("\n## Database\n")
    out.append("```")
    out.append(f"local    {database_url(values)}")
    out.append("docker   postgresql+psycopg://"
               f"{values.get('POSTGRES_USER', 'kisan')}:<password>"
               f"@db:5432/{values.get('POSTGRES_DB', 'kisansaathi')}")
    out.append("         the host is the compose service name, not localhost")
    out.append("```")

    out.append("\n## Deployment settings\n")
    out.append("| Variable | Value | Notes |")
    out.append("| --- | --- | --- |")
    for key, note in DEPLOYMENT:
        out.append(f"| `{key}` | `{values.get(key) or '(unset)'}` | {note} |")

    out.append("\n## Rotating\n")
    for key, what, how in SECRETS:
        out.append(f"- **`{key}`** — {how}")
    out.append(
        "\n  Rotating `JWT_SECRET_KEY` invalidates every issued token, so everyone is\n"
        "  signed out. Changing `POSTGRES_PASSWORD` in `.env` does **not** change the\n"
        "  password inside an existing database: run\n"
        "  `ALTER ROLE kisan WITH PASSWORD '...';` or start from an empty volume.\n"
        "  `make rotate-jwt` regenerates the signing key only.\n"
    )

    out.append(
        "\n## Before a public deployment\n"
        "Run `docs/DEPLOYMENT.md` top to bottom. The short version:\n\n"
        "1. `DEMO_MODE=false` and `SEED_ON_START=false`.\n"
        "2. `DOCS_ENABLED=false`.\n"
        "3. `CORS_ORIGINS` set to your real origin, nothing else.\n"
        "4. A rate limiter at the proxy. `RATE_LIMIT_ENABLED` and `REDIS_URL` are\n"
        "   declared in config but read by nothing, so they do not limit anything.\n"
        "5. Nothing for media: there is no upload endpoint.\n"
        "6. Fresh `JWT_SECRET_KEY` and `POSTGRES_PASSWORD`, both out of this repo.\n"
        "7. TLS terminated in front of nginx.\n"
    )
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="print the values as well")
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        print(f"no {ENV_FILE.name} here. Run `make env` first.", file=sys.stderr)
        return 1

    values = parse_env(ENV_FILE)
    body = render(values)

    if args.check:
        if not OUT_FILE.exists():
            print("SECRETS.local.md is missing. Run `make secrets`.", file=sys.stderr)
            return 1
        if OUT_FILE.read_text() != body:
            print("SECRETS.local.md is out of date. Run `make secrets`.", file=sys.stderr)
            return 1
        print("SECRETS.local.md matches .env")
        return 0

    OUT_FILE.write_text(body)
    if args.show:
        print(body)
    else:
        for key, what, _ in SECRETS:
            value = values.get(key, "")
            shown = redact(value) if key in SECRET_NAMES else (value or "(empty)")
            print(f"  {key:<22} {shown}  {what}")
        print(f"\nwrote {OUT_FILE.name} (git-ignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
