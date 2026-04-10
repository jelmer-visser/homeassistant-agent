"""Abstract interface for AI analysis providers."""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from custom_components.ha_energy_agent.models import (
    AnalysisResult,
    GroupHistoryBundle,
    LongTermContext,
    PricingContext,
)


@runtime_checkable
class AnalysisClient(Protocol):
    """Protocol that all AI provider clients must satisfy."""

    async def analyse(
        self,
        bundles: list[GroupHistoryBundle],
        pricing: Optional[PricingContext],
        history_hours: int,
        long_term: Optional[LongTermContext] = None,
    ) -> AnalysisResult:
        """Run one analysis cycle and return a validated AnalysisResult."""
        ...
