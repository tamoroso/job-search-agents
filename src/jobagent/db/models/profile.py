from sqlalchemy import func,  ForeignKey, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from jobagent.db.base import Base, UUIDPk, Timestamp, Embedding
import uuid
from typing import Any

class app_user(UUIDPk, Base): 
    __tablename__="app_user"

    email: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[Timestamp] = mapped_column(server_default=func.now())

class profile(UUIDPk, Base):
    __tablename__="profile"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    headline: Mapped[str]
    seniority: Mapped[str]
    target_titles: Mapped[list[str]] = mapped_column(default=[])
    hard_filters: Mapped[dict[str, Any]] = mapped_column(default={})
    soft_prefs: Mapped[dict[str, Any]] = mapped_column(default={})
    summary_embedding: Mapped[Embedding | None] 

class experience(UUIDPk, Base):
    __tablename__= "experience"

    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.id"))
    company: Mapped[str]
    role: Mapped[str]
    start_date: Mapped[Timestamp]
    end_date: Mapped[Timestamp | None]
    description: Mapped[str | None]

class proof_point (UUIDPk, Base):
    __tablename__= "proof_point"

    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.id"))
    experience_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experience.id"))
    title : Mapped[str]
    context : Mapped[str]
    action: Mapped[str]
    result: Mapped[str]
    metrics: Mapped[dict[str, Any] | None]
    skills : Mapped[list[str] | None]
    strength : Mapped [int | None] = mapped_column(SmallInteger)
    embedding : Mapped[Embedding | None]
    is_verified : Mapped[bool] = mapped_column(default=False, server_default="false")

    profile: Mapped["Profile"] = relationship(back_populates="proof_points") # type: ignore



