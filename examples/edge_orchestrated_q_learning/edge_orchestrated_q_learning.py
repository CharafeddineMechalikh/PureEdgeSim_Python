"""Reinforcement placement delegated to an orchestrator on the edge tier.

    PYTHONPATH=src python examples/edge_orchestrated_q_learning/edge_orchestrated_q_learning.py

The agent of ``examples/q_learning`` chooses the layer, and inside that layer a
guided heuristic picks the least loaded eligible node, so the learned part and the
estimate-based part of the policy stay separate. Here that decision no longer
happens on the device: ``enable_orchestrators=true`` with
``deploy_orchestrator=EDGE`` sends every request to the closest edge data center
first, which adds a MAN round trip to the delay the agent is charged for.

The scenario is the neighbourhood-scale version of the Q-learning example: 500
devices, four linked edge data centers on a 2000 by 2000 meters map, and ten
simulated minutes. The orchestrator class is imported, not copied.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The scripts are runnable directly and importable as ``examples.<folder>.<module>``,
# which is how the tests reach them, so make the repository root importable here too.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples.q_learning.q_learning import QLearningOrchestrator, run

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/edge_orchestrated_q_learning/output"


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the scenario; the three arguments shrink it for the test suite."""
    return run(SETTINGS, output, QLearningOrchestrator, "edge orchestrated", devices, duration, seed=seed)


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the delegated decisions can be watched on a small neighbourhood
    # without editing the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
