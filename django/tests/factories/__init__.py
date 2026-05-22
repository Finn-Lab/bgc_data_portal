"""factory_boy index for the v2 discovery schema.

Re-exports the factories from :mod:`discovery_models` so callers can do
``from tests.factories import IntegratedBgcFactory``.
"""

from tests.factories.discovery_models import (
    AssemblySourceFactory,
    ConsensusBgcFactory,
    ContigCdsFactory,
    ContigDomainFactory,
    DashboardAssemblyFactory,
    DashboardContigFactory,
    DashboardDetectorFactory,
    IntegratedBgcFactory,
    SourceBgcPredictionFactory,
)

__all__ = [
    "AssemblySourceFactory",
    "ConsensusBgcFactory",
    "ContigCdsFactory",
    "ContigDomainFactory",
    "DashboardAssemblyFactory",
    "DashboardContigFactory",
    "DashboardDetectorFactory",
    "IntegratedBgcFactory",
    "SourceBgcPredictionFactory",
]
