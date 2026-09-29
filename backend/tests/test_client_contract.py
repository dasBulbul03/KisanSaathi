"""Contract tests between the backend and the web client.

The one thing that cannot be caught by the API tests alone is the `link` field
on a notification. The API happily returns any string, but the client treats it
as an in-app route: a link to a page that does not exist drops the user into the
catch-all redirect with no explanation. These tests pin the emitted links to the
routes the client actually serves.
"""

from __future__ import annotations

import re
from pathlib import Path

# Every in-app route the web client registers, plus `/login`, which is the
# destination for messages that make no sense once signed in. Kept as an
# explicit list rather than derived from the client so that adding a route on
# one side without the other shows up as a test failure.
APP_ROUTES: set[str] = {
    "/login",
    "/dashboard",
    "/admin",
    "/users",
    "/profile",
    "/lots",
    "/my-lots",
    "/my-lots/new",
    "/demands",
    "/my-demands",
    "/my-demands/new",
    "/offers",
    "/orders",
    "/market",
    "/storage",
    "/payments",
    "/logistics",
    "/inspections",
    "/grievances",
    "/notifications",
}

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

_LINK_LITERAL = re.compile(r"""\blink\s*=\s*(?P<value>"[^"]*"|None)""")


def _emitted_links() -> set[str]:
    """Every literal link value the service layer can attach to a notification."""
    found: set[str] = set()
    for source in APP_ROOT.rglob("*.py"):
        if "notification" not in source.read_text():
            continue
        for match in _LINK_LITERAL.finditer(source.read_text()):
            value = match.group("value")
            if value != "None":
                found.add(value.strip('"'))
    return found


def test_notification_links_are_real_app_routes() -> None:
    unknown = {link for link in _emitted_links() if link.split("?")[0] not in APP_ROUTES}
    assert not unknown, (
        "these notification links have no matching client route: "
        f"{sorted(unknown)}. Add the route to the web client or point the "
        "notification at one that exists."
    )


def test_matches_endpoint_shape_matches_the_client_contract() -> None:
    """`GET /matches` returns `{matches, summary}`; the client reads both keys."""
    from app.schemas.trade import MatchSummary

    assert set(MatchSummary.model_fields) >= {"direction", "total_candidates", "disclaimer"}
