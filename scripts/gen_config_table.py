#!/usr/bin/env python3
"""Generate the README's configuration table from `app/core/config.py`.

The variable list and the defaults in the README are read out of the code, so a
new setting cannot be documented wrong or left out: if it is not in `config.py`
it is not in the table, and the defaults cannot drift from the field definitions.

`NOTES` is the hand-written part: what each setting actually does. The check in
`make check` runs this with `--check`, which fails if the README is out of date.

Usage:
    python scripts/gen_config_table.py            # print the table
    python scripts/gen_config_table.py --check    # fail if the README is stale
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "backend/app/core/config.py"
README = ROOT / "README.md"

BEGIN = "<!-- config-table:begin -->"
END = "<!-- config-table:end -->"

# Grouped in the order a deployer meets them.
GROUPS: list[tuple[str, list[str]]] = [
    (
        "App",
        ["ENVIRONMENT", "LOG_LEVEL", "LOG_JSON", "DEBUG"],
    ),
    (
        "Database",
        [
            "DATABASE_URL",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "SQLITE_PATH",
            "DB_POOL_SIZE",
            "DB_MAX_OVERFLOW",
            "DB_POOL_TIMEOUT",
            "DB_ECHO",
        ],
    ),
    (
        "Security and tokens",
        [
            "JWT_SECRET_KEY",
            "JWT_ALGORITHM",
            "ACCESS_TOKEN_EXPIRE_MINUTES",
            "REFRESH_TOKEN_EXPIRE_DAYS",
            "PASSWORD_MIN_LENGTH",
            "PBKDF2_ITERATIONS",
        ],
    ),
    ("CORS", ["CORS_ORIGINS", "CORS_ALLOW_CREDENTIALS"]),
    (
        "Cache and rate limiting",
        [
            "REDIS_URL",
            "CACHE_TTL_SECONDS",
            "RATE_LIMIT_ENABLED",
            "RATE_LIMIT_REQUESTS",
            "RATE_LIMIT_WINDOW_SECONDS",
        ],
    ),
    (
        "AI assistant",
        [
            "AI_PROVIDER",
            "NVIDIA_API_KEY",
            "NVIDIA_BASE_URL",
            "NVIDIA_MODEL",
            "NVIDIA_EMBEDDING_MODEL",
            "NVIDIA_TIMEOUT_SECONDS",
            "NVIDIA_MAX_RETRIES",
            "AI_ASSISTANT_ENABLED",
            "AI_TEMPERATURE",
            "AI_MAX_TOKENS",
        ],
    ),
    (
        "Integrations",
        [
            "MARKET_DATA_PROVIDER",
            "MARKET_DATA_BASE_URL",
            "MARKET_DATA_API_KEY",
            "LOGISTICS_PROVIDER",
            "LOGISTICS_BASE_URL",
            "LOGISTICS_API_KEY",
            "NOTIFICATION_PROVIDER",
        ],
    ),
    (
        "Media",
        ["MEDIA_ROOT", "MAX_UPLOAD_BYTES", "ALLOWED_IMAGE_TYPES"],
    ),
    ("Demo and seeding", ["DEMO_MODE"]),
    ("API surface", ["DOCS_ENABLED"]),
    # Read by docker-compose.yml or baked into the bundle, not by the API.
    (
        "Compose and build time",
        ["FRONTEND_PORT", "VITE_SHOW_DEMO_ACCOUNTS", "VITE_API_BASE_URL", "VITE_BACKEND_ORIGIN"],
    ),
]

NOTES: dict[str, str] = {
    "ENVIRONMENT": "`development`, `test`, `staging` or `production`. Only `production` enforces the startup checks.",
    "LOG_LEVEL": "Standard Python levels.",
    "LOG_JSON": "One JSON object per line, for a log shipper. Off reads better locally.",
    "DEBUG": "FastAPI debug returns tracebacks. Keep false anywhere public.",
    "DATABASE_URL": "Overrides the `POSTGRES_*` parts. `postgres://` is rewritten to psycopg.",
    "POSTGRES_USER": "Role the API authenticates as.",
    "POSTGRES_PASSWORD": "**Secret.** Required by compose. Changing it here does not change an existing volume: see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).",
    "POSTGRES_DB": "Database name.",
    "POSTGRES_HOST": "`db` in Compose, `localhost` locally.",
    "POSTGRES_PORT": "Postgres port.",
    "SQLITE_PATH": "Only used on the SQLite path, i.e. outside Docker in development.",
    "DB_POOL_SIZE": "Postgres only; SQLite ignores the pool.",
    "DB_MAX_OVERFLOW": "Extra connections above the pool size.",
    "DB_POOL_TIMEOUT": "Seconds to wait for a connection before failing.",
    "DB_ECHO": "Logs every statement and its parameters. Never on in production.",
    "JWT_SECRET_KEY": "**Secret, required in production.** Signs every token. `make rotate-jwt`.",
    "JWT_ALGORITHM": "Symmetric: anyone holding the key can mint tokens.",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "Eight hours, so a field user is not forced to sign in daily.",
    "REFRESH_TOKEN_EXPIRE_DAYS": "Refresh tokens rotate; replaying a rotated token revokes the chain.",
    "PASSWORD_MIN_LENGTH": "Enforced at registration. Raise it for a real deployment.",
    "PBKDF2_ITERATIONS": "Password hash cost. Higher is slower to attack and slower to log in.",
    "CORS_ORIGINS": "Comma-separated. Not consulted in the Compose stack, which is one origin.",
    "CORS_ALLOW_CREDENTIALS": "Never pair with `*`.",
    "REDIS_URL": "**Secret** if it carries a password. Unused: no code reads it yet. Declared for a limiter that is not implemented.",
    "CACHE_TTL_SECONDS": "Unused: no code reads it, and there is no response cache.",
    "RATE_LIMIT_ENABLED": "**Unused: there is no rate limiter in the code.** Compose sets it to `true` and nothing acts on it. Limit at the proxy instead: see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).",
    "RATE_LIMIT_REQUESTS": "Unused, same as `RATE_LIMIT_ENABLED`.",
    "RATE_LIMIT_WINDOW_SECONDS": "Unused, same as `RATE_LIMIT_ENABLED`.",
    "AI_PROVIDER": "Provider name; the adapter is in `app/integrations/`.",
    "NVIDIA_API_KEY": "**Secret.** Empty is not an error: the assistant falls back to the deterministic rules engine.",
    "NVIDIA_BASE_URL": "NVIDIA NIM endpoint.",
    "NVIDIA_MODEL": "Chat model.",
    "NVIDIA_EMBEDDING_MODEL": "Unused: the assistant has no embedding or retrieval path. It reads the database, not a vector store.",
    "NVIDIA_TIMEOUT_SECONDS": "Per-request timeout.",
    "NVIDIA_MAX_RETRIES": "Retries before the rules engine answers instead.",
    "AI_ASSISTANT_ENABLED": "Needs `NVIDIA_API_KEY` too, and gates the model client: `false` pins every answer to the rules engine. It does not remove the route, so `/ai/chat` still answers.",
    "AI_TEMPERATURE": "Low on purpose. The assistant explains, it does not negotiate.",
    "AI_MAX_TOKENS": "Answer cap. See [`docs/AI_BOUNDARY.md`](docs/AI_BOUNDARY.md).",
    "MARKET_DATA_PROVIDER": "`demo` is the seeded synthetic dataset.",
    "MARKET_DATA_BASE_URL": "Required by a real provider.",
    "MARKET_DATA_API_KEY": "**Secret.** Unused while the provider is `demo`.",
    "LOGISTICS_PROVIDER": "Unused: quotes always come from the in-process `DemoLogisticsProvider`. Pass a provider to `LogisticsService` to change that.",
    "LOGISTICS_BASE_URL": "Unused, same as `LOGISTICS_PROVIDER`.",
    "LOGISTICS_API_KEY": "**Secret.** Unused, same as `LOGISTICS_PROVIDER`.",
    "NOTIFICATION_PROVIDER": "Unused: notifications are always written to the database and read back through the API.",
    "MEDIA_ROOT": "Unused: there is no upload endpoint. Grievance evidence is external URLs. Declared for a future media store, so no volume is needed today.",
    "MAX_UPLOAD_BYTES": "Unused, same as `MEDIA_ROOT`.",
    "ALLOWED_IMAGE_TYPES": "Unused, same as `MEDIA_ROOT`. `settings.allowed_image_types` parses it, but no code calls that property.",
    "DEMO_MODE": "Seeds 8 demo accounts, 120 days of synthetic prices and a sample order, and shows the demo banner. `false` loads only reference data.",
    "DOCS_ENABLED": "`false` hides `/api/docs` and `/api/redoc`. Already false in Compose.",
    "FRONTEND_PORT": "Host port for nginx.",
    "VITE_SHOW_DEMO_ACCOUNTS": "Lists the demo accounts on the sign-in screen. Unset means on in dev, and `DEMO_MODE` in Compose. `false` compiles them out of the bundle.",
    "VITE_API_BASE_URL": "**Read by nothing today**: the client is hardcoded to the same origin, `/api/v1`.",
    "VITE_BACKEND_ORIGIN": "Dev-server proxy target only. Ignored in a production build.",
}

# Constants that are not deployment knobs.
SKIP = {"PROJECT_NAME", "PROJECT_DESCRIPTION", "APP_VERSION", "API_V1_PREFIX"}

# Settings that nothing in `backend/app` reads. Verified, not assumed: `check_unused`
# fails if one of these starts being used, so the list cannot quietly go stale. Each
# one's note in NOTES says so, and the README says which features are therefore
# missing. Nine of them are for features that were designed and not built.
UNUSED = {
    "ALLOWED_IMAGE_TYPES",
    "CACHE_TTL_SECONDS",
    "LOGISTICS_API_KEY",
    "LOGISTICS_BASE_URL",
    "LOGISTICS_PROVIDER",
    "MAX_UPLOAD_BYTES",
    "MEDIA_ROOT",
    "NOTIFICATION_PROVIDER",
    "NVIDIA_EMBEDDING_MODEL",
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_WINDOW_SECONDS",
    "REDIS_URL",
}


def check_unused(values: dict[str, str]) -> None:
    """Fail if a setting's used/unused classification no longer matches the code.

    A setting counts as used when app code names it, or when it names a property
    on `Settings` that reads it, such as `resolved_database_url` reading
    `POSTGRES_PASSWORD`.
    """
    config_src = CONFIG.read_text()
    tree = ast.parse(config_src)
    settings = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings"
    )
    helpers: dict[str, set[str]] = {}
    for node in settings.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "__init__":
            helpers[node.name] = {
                t.attr
                for t in ast.walk(node)
                if isinstance(t, ast.Attribute)
                and isinstance(t.value, ast.Name)
                and t.value.id == "self"
            }

    blob = "\n".join(
        p.read_text()
        for p in (ROOT / "backend/app").rglob("*.py")
        if p.resolve() != CONFIG.resolve()
    )
    used = {n for n in values if re.search(rf"\b{n}\b", blob)}
    for helper, attrs in helpers.items():
        if re.search(rf"\b{re.escape(helper)}\b", blob):
            used |= attrs

    actual = set(values) - used
    if actual != UNUSED:
        drift = sorted(actual - UNUSED) + [f"no longer unused: {n}" for n in sorted(UNUSED - actual)]
        raise SystemExit(
            "UNUSED is out of date with the code: " + ", ".join(drift) + ". "
            "Update UNUSED and the note for each of those settings in NOTES."
        )

def render_default(raw: str) -> str:
    """Show a default the way it is written in `.env`, not the way Python spells it."""
    if raw == "None":
        return "unset"
    if raw in ("True", "False"):
        return raw.lower()
    if raw[:1] in "\"'":
        return raw.strip("\"'")
    # Simple arithmetic literals: `60 * 8`, `390_000`, `5 * 1024 * 1024`.
    if re.fullmatch(r"[\d_ *]+", raw):
        try:
            return str(eval(raw.replace("_", "")))  # noqa: S307 - a literal pattern
        except Exception:
            pass
    return raw


def defaults() -> dict[str, str]:
    """Read name and default straight out of the settings class."""
    out: dict[str, str] = {}
    for line in CONFIG.read_text().splitlines():
        m = re.match(r"^    ([A-Z][A-Z0-9_]+): [^=]+$", line)
        if m:
            out[m.group(1)] = "unset"
            continue
        m = re.match(r"^    ([A-Z][A-Z0-9_]+): [^=]+=\s*(.+?)\s*$", line)
        if m and m.group(2) != "(":
            out[m.group(1)] = m.group(2)
    return {k: v for k, v in out.items() if k not in SKIP}


def table() -> str:
    values = defaults()
    check_unused(values)
    lines: list[str] = []
    listed: set[str] = set()
    for title, names in GROUPS:
        lines.append(f"\n**{title}**\n")
        lines.append("| Variable | Default | Notes |")
        lines.append("| --- | --- | --- |")
        for name in names:
            listed.add(name)
            shown = render_default(values.get(name, "None"))
            lines.append(f"| `{name}` | `{shown}` | {NOTES[name]} |")
    missing = set(values) - listed
    if missing:
        raise SystemExit(
            "config.py has settings with no row in GROUPS: "
            + ", ".join(sorted(missing))
            + ". Add them, or add them to SKIP if they are constants."
        )
    unannotated = {n for _, names in GROUPS for n in names} - set(NOTES)
    if unannotated:
        raise SystemExit("NOTES is missing: " + ", ".join(sorted(unannotated)))
    quiet = sorted(n for n in UNUSED if "unused" not in NOTES[n].lower())
    if quiet:
        raise SystemExit(
            "These are in UNUSED, so their note has to say it is unused: "
            + ", ".join(quiet)
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the README is stale")
    args = parser.parse_args()

    body = f"{BEGIN}\n{table()}\n{END}"
    if not args.check:
        print(body)
        return 0

    readme = README.read_text()
    if body not in readme:
        print(
            "README's configuration table is out of date with config.py. "
            "Run: python scripts/gen_config_table.py",
            file=sys.stderr,
        )
        return 1
    print("README configuration table matches config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
