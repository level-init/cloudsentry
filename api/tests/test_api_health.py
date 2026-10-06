from app.main import create_app


def test_health_route_is_registered() -> None:
    app = create_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/health" in paths
