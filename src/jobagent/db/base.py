import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

type Embedding = list[float]   # alias PEP 695, mappé sur vector(1024)
type Timestamp = datetime  # alias PEP 695, mappé sur TIMESTAMP(timezone=True)

class Base(DeclarativeBase):
    type_annotation_map = {
        uuid.UUID: UUID(as_uuid=True),
        Timestamp: TIMESTAMP(timezone=True),
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
        Embedding: Vector(1024),
    }

class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

__all__ = ["Base", "UUIDPk", "Embedding", "Timestamp"]