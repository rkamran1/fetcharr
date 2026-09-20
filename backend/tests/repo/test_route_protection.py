"""The long-lived guard for "every non-public endpoint requires a session" (M1 AC5).

The routes are enumerated from the app, so routes added by later plans are covered
automatically. Making a route public means changing PUBLIC_ROUTES on purpose.
"""

import re
from collections.abc import Iterator

import httpx
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import RouteContext, iter_route_contexts

from app.auth.dependencies import require_auth

PUBLIC_ROUTES = {
    ("GET", "/api/auth/state"),
    ("POST", "/api/auth/setup"),
    ("POST", "/api/auth/login"),
}


def _api_routes(app: FastAPI) -> Iterator[tuple[str, str, RouteContext]]:
    # iter_route_contexts flattens included routers, with their router-level dependencies.
    for route in iter_route_contexts(app.routes):
        if route.path and route.path.startswith("/api/"):
            for method in sorted(route.methods or ()):
                yield method, route.path, route


def _requires_auth(dependant: Dependant) -> bool:
    return dependant.call is require_auth or any(_requires_auth(d) for d in dependant.dependencies)


async def test_every_non_public_api_route_requires_auth(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    checked = []
    for method, path, _route in _api_routes(app):
        if (method, path) in PUBLIC_ROUTES:
            continue
        url = re.sub(r"\{[^}]+\}", "x", path)
        response = await client.request(method, url)
        assert response.status_code == 401, (method, path, response.status_code)
        checked.append((method, path))

    assert ("GET", "/api/auth/me") in checked
    assert ("POST", "/api/auth/api-key") in checked
    assert ("GET", "/api/{path:path}") in checked
    # M5a's endpoints, named so a router that stops being included is noticed.
    for route in (
        ("POST", "/api/requests"),
        ("GET", "/api/requests/{request_id}"),
        ("POST", "/api/preview"),
        ("GET", "/api/jobs"),
        ("GET", "/api/jobs/{job_id}"),
        ("GET", "/api/jobs/{job_id}/log"),
        ("POST", "/api/jobs/{job_id}/cancel"),
        ("POST", "/api/jobs/{job_id}/retry"),
        ("DELETE", "/api/jobs/{job_id}"),
        ("GET", "/api/events"),
        ("GET", "/api/system/status"),
    ):
        assert route in checked, route


def test_public_routes_are_the_expected_set(app: FastAPI) -> None:
    public = {
        (method, path)
        for method, path, route in _api_routes(app)
        if not _requires_auth(route.dependant)
    }

    assert public == PUBLIC_ROUTES
