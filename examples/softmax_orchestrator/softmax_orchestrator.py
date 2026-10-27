"""Softmax (Boltzmann) exploration instead of epsilon-greedy tier choice.

    PYTHONPATH=src python examples/softmax_orchestrator/softmax_orchestrator.py

The agent keeps one value per application type, task-length bucket and layer-load
bucket, exactly like the tabular agent of ``examples/q_learning``, and the update
rule is the same. Only the three decisions that Java Example 16 really changes are
overridden here:

- the tier is sampled from a Boltzmann distribution over the values, so better
  tiers are picked more often and exploration fades as the values separate, with
  no exploration rate to tune;
- the reward is the delay divided by the task latency, so a state value means the
  same thing whatever the size of the task, and the failure penalty is 10 instead
  of 1000;
- the tier executes the task on the node carrying the fewest pending tasks, which
  is released again when the results come back.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from pureedgesim import NodeType, Task, TaskStatus

# The scripts are runnable directly and importable as ``examples.<folder>.<module>``,
# which is how the tests reach them, so make the repository root importable here too.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples.q_learning.q_learning import QLearningOrchestrator, run

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/softmax_orchestrator/output"

TEMPERATURE = 0.05


class SoftmaxOrchestrator(QLearningOrchestrator):
    """The same table of tier values, sampled from a Boltzmann distribution."""

    ALGORITHM = "SOFTMAX"
    LEARNING_RATE = 0.2
    DISCOUNT_RATE = 0.9
    FAILURE_PENALTY = 10.0
    TEMPERATURE = TEMPERATURE

    def boltzmann_weights(self, task, options: list[tuple[int, int]]) -> list[float]:
        """The unnormalised Boltzmann weight of each option: exp(value / temperature).

        The values are shifted by their maximum before the exponential, so the best
        option always weighs exactly 1 and a very negative value cannot overflow.
        """
        values = [self._value(task, action) for action, _ in options]
        highest = max(values)
        return [math.exp((value - highest) / self.TEMPERATURE) for value in values]

    def probabilities(self, task, options: list[tuple[int, int]]) -> list[float]:
        """The chance each option is drawn: its weight divided by the sum of weights."""
        weights = self.boltzmann_weights(task, options)
        total = sum(weights)
        return [weight / total for weight in weights]

    def choose_action(self, task, options: list[tuple[int, int]]) -> tuple[int, int]:
        """Draw a tier from the Boltzmann distribution over its value."""
        weights = self.boltzmann_weights(task, options)
        draw = self.random.random() * sum(weights)
        for index in range(len(weights) - 1):
            draw -= weights[index]
            if draw <= 0:
                return options[index]
        return options[-1]

    def node_in_tier(self, tier: NodeType, task) -> int:
        """The eligible node of the tier carrying the fewest tasks still in flight."""
        best, best_pending = -1, None
        for index, node in enumerate(self.candidates):
            if node.type != tier or not self.offloading_is_possible(node, task):
                continue
            if best_pending is None or self.node_load[index] < best_pending:
                best, best_pending = index, self.node_load[index]
        return best

    def release(self, decision) -> None:
        super().release(decision)
        self.node_load[decision.node] -= 1

    def reward(self, task: Task) -> float:
        """The delay relative to the latency bound, so states stay comparable."""
        if task.status != TaskStatus.SUCCESS:
            return -self.FAILURE_PENALTY
        return -task.total_delay / max(task.max_latency, 1e-9)


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the scenario; the three arguments shrink it for the test suite."""
    return run(SETTINGS, output, SoftmaxOrchestrator, "softmax", devices, duration, seed=seed)


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the Boltzmann sampling can be watched on a small map without
    # editing the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
