"""Mist-only reinforcement placement: the Q-learning agent without a tier to choose.

    PYTHONPATH=src python examples/mist_only_q_learning/mist_only_q_learning.py

The ``MIST_ONLY`` architecture removes the cloud and the edge data centers from
the action space, so every task is placed on a nearby device - and the device may
be the one that generated the task. The agent of ``examples/q_learning`` is reused
unchanged, exactly like the Java Example 14 reuses the Java Example 11 class: only
the scenario and this wrapper change. What the agent now learns is which peer of
the fleet gives the lowest delay, and the state keeps just the tier-load bucket
that survives the collapse of the action space to a single action.

The three device types of ``settings/edge_devices.xml`` all generate and execute
tasks, and none of them is a sensor, so every request can stay in the mist layer.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The scripts are runnable directly and importable as ``examples.<folder>.<module>``,
# which is how the tests reach them, so make the repository root importable here too.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples.q_learning.q_learning import QLearningOrchestrator, run

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/mist_only_q_learning/output"


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the scenario; the three arguments shrink it for the test suite."""
    return run(SETTINGS, output, QLearningOrchestrator, "mist only", devices, duration, seed=seed)


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the mist-only agent can be watched on a small fleet without
    # editing the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
