from collections import Counter

from fastapi.routing import APIRoute

from app.main import create_app


def _routes() -> list[APIRoute]:
    return [route for route in create_app().routes if isinstance(route, APIRoute)]


def test_route_registry_has_no_duplicate_method_and_path() -> None:
    keys = [(method, route.path) for route in _routes() for method in route.methods]
    assert [key for key, count in Counter(keys).items() if count > 1] == []


def test_core_and_visual_review_routes_remain_registered() -> None:
    registered = {(method, route.path) for route in _routes() for method in route.methods}
    expected = {
        ("GET", "/api/ready"),
        ("GET", "/api/projects/{project_id}"),
        ("POST", "/api/shots/{shot_id}/keyframe/generate"),
        ("POST", "/api/shots/{shot_id}/video/generate"),
        ("GET", "/api/media/{asset_id}"),
        ("GET", "/api/provider-verification-runs/{run_id}"),
        ("GET", "/api/provider-verification-runs/{run_id}/visual-reviews"),
        ("POST", "/api/provider-verification-runs/{run_id}/visual-reviews"),
    }
    assert expected <= registered


def test_static_routes_precede_overlapping_dynamic_routes() -> None:
    routes = _routes()
    for static_index, static in enumerate(routes):
        static_parts = static.path.split("/")
        if any(part.startswith("{") for part in static_parts):
            continue
        for dynamic_index, dynamic in enumerate(routes):
            dynamic_parts = dynamic.path.split("/")
            if len(static_parts) != len(dynamic_parts) or not (static.methods & dynamic.methods):
                continue
            overlaps = all(
                left == right or right.startswith("{")
                for left, right in zip(static_parts, dynamic_parts, strict=True)
            )
            if overlaps and static.path != dynamic.path:
                assert static_index < dynamic_index, f"{static.path} is shadowed by {dynamic.path}"
