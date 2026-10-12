from app.main import create_app


def test_health_route_is_registered() -> None:
    app = create_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/health" in paths
    assert "/docs" in paths


def test_openapi_documents_health_and_resource_groups() -> None:
    schema = create_app().openapi()
    health = schema["paths"]["/health"]["get"]
    tag_names = {tag["name"] for tag in schema["tags"]}

    assert schema["info"]["title"] == "CloudSentry API"
    assert health["tags"] == ["system"]
    assert health["summary"] == "Liveness check"
    assert schema["paths"]["/resources"]["get"]["tags"] == ["inventory"]
    assert schema["paths"]["/resources/{resource_id}"]["get"]["tags"] == ["inventory"]
    assert schema["paths"]["/resources/{resource_id}/dependencies"]["get"]["tags"] == ["inventory"]
    assert schema["paths"]["/resources/{resource_id}/dependents"]["get"]["tags"] == ["inventory"]
    assert schema["paths"]["/spend/accounts"]["get"]["tags"] == ["inventory"]
    assert schema["paths"]["/spend/environments"]["get"]["tags"] == ["inventory"]
    assert {"system", "inventory", "proposals"} <= tag_names
