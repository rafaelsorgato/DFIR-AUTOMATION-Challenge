from typing import Annotated, List, Literal
from pydantic import BaseModel, Field


class AlertCreate(BaseModel):
    """Input schema for creating a new alert (POST /analyze)."""

    source: Literal["SIEM", "EDR", "API"] = Field(
        description="Origin of the alert.",
        examples=["SIEM"],
    )
    severity: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        description="Severity reported by the source.",
        examples=["HIGH"],
    )
    description: str = Field(
        min_length=1,
        max_length=2048,
        description="Free-text description of the alert event.",
        examples=["Suspicious login detected from external IP"],
    )
    artifacts: List[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list,
        max_length=64,
        description="Indicators (IPs, hashes, emails, domains) related to the alert.",
        examples=[["1.2.3.4", "user@example.com"]],
    )

    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
    }


class AnalysisResult(BaseModel):
    """LLM analysis result attached to an alert."""

    risk_assessment: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        description="Risk level inferred by the LLM."
    )
    summary: str = Field(
        min_length=1,
        description="Short one-sentence summary of the alert.",
    )
    recommended_actions: List[str] = Field(
        default_factory=list,
        description="List of concrete actions an analyst should take.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Analysis confidence between 0.0 and 1.0.",
    )


class AlertResponse(BaseModel):
    """Output schema for an alert returned by the API."""

    id: int = Field(description="Auto-incremented alert ID.")
    source: str
    severity: str
    description: str
    artifacts: List[str]
    status: Literal["PENDING", "PROCESSING", "COMPLETE", "ERROR"]
    analysis_result: AnalysisResult | None = None
    queue_position: int | None = Field(
        default=None,
        description="Position in the processing queue (PENDING only).",
    )
    created_at: str
    updated_at: str
