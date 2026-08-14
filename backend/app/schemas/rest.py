from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class JoinRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=24)
    identity_id: UUID

    @field_validator("display_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Имя не может быть пустым")
        return normalized


class JoinResponse(BaseModel):
    player_id: UUID
    reconnect_token: str


class HostRoomResponse(BaseModel):
    room_code: str
    host_token: str
    host_url: str
    player_url: str
