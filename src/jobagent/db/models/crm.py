from models.base import Base, UUIDPk, Timestamp
from sqlachemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, SmallInteger
import uuid


class application(UUIDPk, Base): 
    __tablename__ = "application"

    offer_id : Mapped[uuid.UUID] = mapped_column(ForeignKey("job_offer.id"))
    profile_id : Mapped[uuid.UUID] = mapped_column(ForeignKey("profile.id"))
    status : Mapped[str | None]
    applied_at : Mapped[Timestamp | None]
    next_action_at : Mapped[Timestamp | None]
    notes : Mapped[str | None]

class contact (UUIDPk, Base):
    __tablename__ = "contact"

    company_id : Mapped[uuid.UUID] = mapped_column(ForeignKey("company.id"))
    name : Mapped[str]
    role : Mapped[str | None]
    linkedin_url : Mapped[str | None]
    email : Mapped[str | None]
    source : Mapped[str | None]
    consent_basis : Mapped[str | None] 

class document (UUIDPk, Base):
    __tablename__ = "document"

    application_id : Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id"))
    type : Mapped[str | None] # -- cv|cover_letter|outreach
    content : Mapped[str | None]
    version : Mapped[int | None] = mapped_column(SmallInteger)
    proof_points_id : Mapped[list[uuid.UUID] | None] = mapped_column(ForeignKey("proof_point.id"))
    unanchored_claims : Mapped[list[str] | None]
    generated_by : Mapped[str | None] # -- user|ai
    approved_by_human : Mapped[bool | None] = mapped_column(default=False, server_default="false")