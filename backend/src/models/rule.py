from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.config.database import Base


class RuleVersion(Base):
    """计算规则版本。同一时刻至多一个 is_active 版本（部分唯一索引保证）。"""
    __tablename__ = 'rule_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default='')
    engine_key: Mapped[str] = mapped_column(String(60))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='candidate')  # active / candidate / retired
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    activated_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    retired_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    replays: Mapped[list['ShadowReplay']] = relationship(back_populates='rule', cascade='all, delete-orphan')


class ShadowReplay(Base):
    """候选版本对已完成试验的影子回放；结果不进入批准与简报。"""
    __tablename__ = 'shadow_replays'
    __table_args__ = (UniqueConstraint('rule_version_id', 'job_id', name='uq_replay_rule_job'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_version_id: Mapped[int] = mapped_column(ForeignKey('rule_versions.id'))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending / running / completed / failed
    diff_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    point_changes: Mapped[list] = mapped_column(JSON, default=list)
    candidate_result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    rule: Mapped['RuleVersion'] = relationship(back_populates='replays')
