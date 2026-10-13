"""
ARIA Neuroscience Module
=========================

Neuroscience-inspired cognitive architecture for ARIA.

This module implements brain-inspired processing:

1. **Memory Consolidation** (consolidation.py)
   - Sharp Wave Ripple simulation for memory replay
   - Systems consolidation (hippocampus -> neocortex transfer)
   - Memory strengthening and decay

2. **Default Mode Network** (dmn.py)
   - mPFC: Self-referential processing, values
   - PCC: Autobiographical memory access
   - Precuneus: Mental imagery

3. **Metacognitive Monitor** (metacognition.py)
   - Confidence assessment
   - Uncertainty detection
   - Strategy suggestion
   - Known limitations awareness

4. **Mind Wandering** (mind_wandering.py)
   - Spontaneous thought generation
   - Current concerns tracking
   - Creative exploration
   - Problem incubation

5. **Unified Architecture** (unified.py)
   - Orchestrates all components
   - Background processing
   - Integration with ARIA

Usage:
    from core.neuroscience import UnifiedMemoryArchitecture

    # Create the unified architecture
    neuro = UnifiedMemoryArchitecture(memory_system=memory)

    # Start background processing
    neuro.start_background_processing()

    # Hook into interactions
    result = neuro.on_interaction("user message", context)

    # Run autonomous cycle
    results = neuro.run_autonomous_cycle()

Created: December 2024
Version: 1.0.0
"""

# Memory Consolidation
from .consolidation import (
    MemoryConsolidator,
    SharpWaveRippleSimulator,
    ConsolidationPhase,
    ConsolidationEvent,
    SWREvent
)

# Default Mode Network
from .dmn import (
    DefaultModeNetwork,
    DMNMode,
    DMNActivation,
    MPFCModule,
    PCCModule,
    PrecuneusModule
)

# Metacognition
from .metacognition import (
    MetacognitiveMonitor,
    MetacognitiveState,
    ConfidenceLevel,
    ConfidenceAssessment,
    MetacognitiveEvent
)

# Mind Wandering
from .mind_wandering import (
    MindWanderingEngine,
    WanderingType,
    WanderingDepth,
    WanderingEpisode,
    CurrentConcern
)

# Unified Architecture (main entry point)
from .unified import (
    UnifiedMemoryArchitecture,
    SystemState,
    ActivityReport
)


__all__ = [
    # Main entry point
    'UnifiedMemoryArchitecture',
    'SystemState',
    'ActivityReport',

    # Consolidation
    'MemoryConsolidator',
    'SharpWaveRippleSimulator',
    'ConsolidationPhase',
    'ConsolidationEvent',
    'SWREvent',

    # DMN
    'DefaultModeNetwork',
    'DMNMode',
    'DMNActivation',
    'MPFCModule',
    'PCCModule',
    'PrecuneusModule',

    # Metacognition
    'MetacognitiveMonitor',
    'MetacognitiveState',
    'ConfidenceLevel',
    'ConfidenceAssessment',
    'MetacognitiveEvent',

    # Mind Wandering
    'MindWanderingEngine',
    'WanderingType',
    'WanderingDepth',
    'WanderingEpisode',
    'CurrentConcern',
]

__version__ = '1.0.0'
