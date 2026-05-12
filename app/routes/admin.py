from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_key, get_session, hash_key, require_admin
from app.models import ApiKey

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class CreateKeyResponse(BaseModel):
    id: int
    name: str
    api_key: str = Field(description="The plaintext API key. Shown once — store it now.")
    created_at: datetime


class KeyInfo(BaseModel):
    id: int
    name: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


@router.post("/keys", response_model=CreateKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: CreateKeyRequest,
    session: AsyncSession = Depends(get_session),
) -> CreateKeyResponse:
    plaintext = generate_key()
    key = ApiKey(name=body.name, key_hash=hash_key(plaintext))
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return CreateKeyResponse(
        id=key.id,
        name=key.name,
        api_key=plaintext,
        created_at=key.created_at,
    )


@router.get("/keys", response_model=list[KeyInfo])
async def list_keys(session: AsyncSession = Depends(get_session)) -> list[KeyInfo]:
    result = await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return [
        KeyInfo(
            id=k.id,
            name=k.name,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            revoked=k.revoked,
        )
        for k in result.scalars().all()
    ]


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: int, session: AsyncSession = Depends(get_session)) -> None:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    key.revoked = True
    await session.commit()
