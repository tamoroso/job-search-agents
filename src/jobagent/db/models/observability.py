from models.base import Base, UUIDPk, Timestamp
from sqlachemy.orm import Mapped, mapped_column
from sqlalchemy import  Integer, Numeric, func
from decimal import Decimal
import uuid

class llm_call(UUIDPk, Base):
    __tablename__ = "llm_call"

    agent : Mapped[str | None]
    prompt_version : Mapped[str | None]
    model : Mapped[str | None]
    input_tokens : Mapped[int | None] = mapped_column(Integer)
    output_tokens : Mapped[int | None] = mapped_column(Integer)
    cost_usd : Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    latency_ms : Mapped[int | None] = mapped_column(Integer)
    success : Mapped[bool | None]
    created_at : Mapped[Timestamp | None] = mapped_column(server_default=func.now())