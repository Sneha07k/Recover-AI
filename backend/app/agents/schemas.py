from pydantic import BaseModel, Field

from app.models.enums import RecoveryStrategy


class AgentDecisionResult(BaseModel):

    action: RecoveryStrategy
    confidence: float = Field(ge=0, le=1)
    reason: str
    requires_approval: bool

