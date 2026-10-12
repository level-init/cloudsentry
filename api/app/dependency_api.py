"""Dependency and dependent lookup for one resource."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.repositories import DependencyRepository, ResourceRepository
from app.schemas import Dependency, DependencyList

router = APIRouter(prefix="/resources", tags=["inventory"])


@router.get(
    "/{resource_id}/dependencies",
    response_model=DependencyList,
    summary="Resources this resource depends on",
    description=(
        "Edges where this resource is the source. Each edge has a source, a target, "
        "and a relationship. Order is relationship, then target. An unknown resource "
        "is 404. A known resource with no edges returns an empty list."
    ),
)
def list_dependencies(resource_id: str, session: Session = Depends(get_session)) -> DependencyList:
    _require_resource(session, resource_id)
    edges = DependencyRepository(session).dependencies_of(resource_id)
    return _list(resource_id, edges)


@router.get(
    "/{resource_id}/dependents",
    response_model=DependencyList,
    summary="Resources that depend on this resource",
    description=(
        "Edges where this resource is the target. Each edge has a source, a target, "
        "and a relationship. Order is relationship, then source. An unknown resource "
        "is 404. A known resource with no edges returns an empty list."
    ),
)
def list_dependents(resource_id: str, session: Session = Depends(get_session)) -> DependencyList:
    _require_resource(session, resource_id)
    edges = DependencyRepository(session).dependents_of(resource_id)
    return _list(resource_id, edges)


def _require_resource(session: Session, resource_id: str) -> None:
    if ResourceRepository(session).get(resource_id) is None:
        raise HTTPException(status_code=404, detail="resource not found")


def _list(resource_id: str, edges: list[Dependency]) -> DependencyList:
    return DependencyList(resource_id=resource_id, items=edges, total=len(edges))
