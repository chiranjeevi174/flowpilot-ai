"""Health check response schema."""

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Schema representing the service health status response."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        default="healthy",
        description="Operational health indicator of the service",
        examples=["healthy"],
    )
    service: str = Field(
        description="Identifier of the reporting service",
        examples=["flowpilot-api"],
    )
    version: str = Field(
        description="Semantic version of the application",
        examples=["1.0.0"],
    )
