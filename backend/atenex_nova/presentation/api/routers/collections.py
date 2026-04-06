"""Collections router."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.presentation.api.dto.schemas import (
    CreateCollectionRequest, UpdateCollectionRequest, CollectionResponse,
)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    body: CreateCollectionRequest,
    session: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    repo = SqlCollectionRepository(session)
    entity = Collection(id=new_id(), name=body.name, description=body.description,
                        language_profile=body.language_profile)
    await repo.create(entity)
    return CollectionResponse(**entity.__dict__)


@router.get("", response_model=list[CollectionResponse])
async def list_collections(
    offset: int = 0, limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[CollectionResponse]:
    repo = SqlCollectionRepository(session)
    items = await repo.list_all(offset=offset, limit=limit)
    return [CollectionResponse(**c.__dict__) for c in items]


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: str,
    session: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    repo = SqlCollectionRepository(session)
    entity = await repo.get_by_id(collection_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Collection not found")
    return CollectionResponse(**entity.__dict__)


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: str,
    body: UpdateCollectionRequest,
    session: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    repo = SqlCollectionRepository(session)
    entity = await repo.get_by_id(collection_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Collection not found")
    if body.name is not None:
        entity.rename(body.name)
    if body.description is not None:
        entity.description = body.description
    entity.update_profiles(body.generation_profile, body.retrieval_profile)
    await repo.update(entity)
    return CollectionResponse(**entity.__dict__)


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    repo = SqlCollectionRepository(session)
    deleted = await repo.delete(collection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection not found")
