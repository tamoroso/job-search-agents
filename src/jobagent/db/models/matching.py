from jobagent.db.base import Base, UUIDPk, Timestamp, Embedding
from typing import Any
import uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, SmallInteger, Float, func,UniqueConstraint

class matching(UUIDPk, Base):
    __tablename__ = "matching"

    offer_id : Mapped[uuid.UUID] = mapped_column(ForeignKey("job_offer.id"))
    profile_id : Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.id"))
    stage_reached :  Mapped[int | None] = mapped_column(SmallInteger)
    filter_rejections : Mapped[list[str] | None]
    retrieval_score : Mapped[float | None] = mapped_column(Float)
    coverage : Mapped[dict[str, Any] | None]
    llm_fit_score : Mapped[int | None] = mapped_column(SmallInteger)
    model_version : Mapped[str | None]
    prompt_version : Mapped[str | None]
    scored_at : Mapped[Timestamp | None] = mapped_column(server_default=func.now())
    human_label : Mapped[int | None] = mapped_column(SmallInteger)
    
    __table_args__ = (
        UniqueConstraint("offer_id", "profile_id", name="uq_matching_offer_profile"),
    )