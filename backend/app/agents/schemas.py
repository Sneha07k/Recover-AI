from pydantic import BaseModel, Field

from app.models.enums import RecoveryStrategy


class AgentDecisionResult(BaseModel):
    """
    The structured shape every agent decision must take. Even though the
    tool schema already constrains what the model can send, we validate
    again here in our own code â€” a tool schema is a strong hint to the
    model, not a hard guarantee, so we never trust it blindly.
    """

    action: RecoveryStrategy
    confidence: float = Field(ge=0, le=1)
    reason: str
    requires_approval: bool

