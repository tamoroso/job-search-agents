from jobagent.db.base import Base, UUIDPk, Timestamp, Embedding
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import UniqueConstraint, ForeignKey, Numeric, func, SmallInteger, Float, Index
import uuid
from decimal import Decimal

class company(UUIDPk, Base):
    __tablename__ = "company"

    name : Mapped[str]
    slug : Mapped[str] = mapped_column(unique=True)
    domain : Mapped[str | None]
    ats_type : Mapped[str | None] 
    ats_slug : Mapped[str | None] # -- greenhouse | lever | ashby | smartrecruiters | recruitee | personio
    careers_url : Mapped[str | None]
    size_bucket : Mapped[str | None]
    funding_stage : Mapped[str | None]
    sector : Mapped[str | None]
    hq_country : Mapped[str | None]
    is_blocklisted : Mapped[bool] = mapped_column(default=False, server_default="false")
    last_updated : Mapped[Timestamp | None]

    __table_args__ = (
        UniqueConstraint("ats_type", "ats_slug", name="uq_company_ats"),
    )

class job_offer(UUIDPk, Base):
    __tablename__ = "job_offer"

    company_id : Mapped[uuid.UUID] = mapped_column(ForeignKey("company.id"))
    source : Mapped[str]
    source_id : Mapped[str]
    url : Mapped[str]
    title : Mapped[str]
    normalized_title : Mapped[str]
    seniority : Mapped[str | None]
    description_raw : Mapped[str | None]
    description_clean : Mapped[str | None]
    location : Mapped[str | None]
    country : Mapped[str | None]
    remote_policy : Mapped[str | None] # -- onsite | hybrid | remote
    contract_type : Mapped[str | None]
    salary_min : Mapped[Decimal | None] = mapped_column(Numeric)
    salary_max : Mapped[Decimal | None] = mapped_column(Numeric)
    salary_currency : Mapped[str | None]
    salary_is_stated : Mapped[bool] = mapped_column(default=False, server_default="false")
    tech_stack : Mapped[list[str] | None]
    posted_at : Mapped[Timestamp | None]
    first_seen_at : Mapped[Timestamp | None] = mapped_column(server_default=func.now())
    last_seen_at : Mapped[Timestamp | None]
    is_active : Mapped[bool] = mapped_column(default=True, server_default="true")
    repost_count : Mapped[int | None] = mapped_column(SmallInteger, default=0, server_default="0")
    ghost_score : Mapped[float | None] = mapped_column(Float)
    content_hash : Mapped[str | None]
    summary_embedding : Mapped[Embedding | None]

    __table_args__ = (
        UniqueConstraint("source","source_id", name="uq_job_offer_source"),
        Index(
            "ix_job_offer_summary_embedding_hnsw",
            "summary_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"summary_embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64}
        ),
    )

class job_requirement (UUIDPk, Base):
    __tablename__ = "job_requirement"

    offer_id : Mapped[uuid.UUID] = mapped_column(ForeignKey("job_offer.id", ondelete="CASCADE"))
    text : Mapped[str]
    kind : Mapped[str | None] # -- must_have | nice_to_have | responsibility | context
    category : Mapped[str | None] # -- tech | domain | soft | experience | education
    weight : Mapped[float | None] = mapped_column(Float, default=1.0)
    requirement_embedding : Mapped[Embedding | None]

    __table_args__ = (
        Index(
            "ix_job_requirement_embedding_hnsw",
            "requirement_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"requirement_embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64}
        ),
    )
