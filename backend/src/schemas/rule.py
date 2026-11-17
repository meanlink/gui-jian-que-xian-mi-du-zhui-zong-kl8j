from pydantic import BaseModel, Field


class RuleCreateInput(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r'^[A-Za-z0-9._-]+$')
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default='', max_length=1000)
    engine_key: str = Field(min_length=2, max_length=60)
    config: dict = Field(default_factory=dict)
    job_ids: list[int] = Field(default_factory=list)


class ReplayInput(BaseModel):
    job_ids: list[int] = Field(min_length=1)
