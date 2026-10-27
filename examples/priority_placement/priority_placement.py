"""Deadline-aware placement: one orchestrator, three task classes, three objectives.

    python examples/priority_placement/priority_placement.py

The application type decides the rule. A hard real-time task goes to the eligible
node whose estimated finish time leaves the largest latency margin, and only falls
back to the fastest node when no node can meet the deadline. A soft real-time task
goes where the estimated delay is the smallest fraction of its latency. A non
real-time task goes where the estimated energy is the lowest, so a long-running
background job does not occupy an edge server that latency-sensitive tasks may
need.

The estimate covers the compute time, the tasks already pending on the node, the
device access latency, and the WAN latency for the cloud. The energy estimate
multiplies the active consumption of the node by the compute time.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pureedgesim import COLUMNS, Orchestrator, Simulation, load_parameters, load_settings
from pureedgesim.nodes import ComputingNode, NodeType

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/priority_placement/output"
ALGORITHM = "PRIORITY_AWARE"

# A miss is scored above every feasible node, so a feasible destination always wins.
DEADLINE_MISS_PENALTY = 1e6


class PriorityOrchestrator(Orchestrator):
    """Placement by task class: latency margin, normalised delay, or energy."""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        if manager.scenario.orchestration_algorithm != ALGORITHM:
            raise ValueError(f"{type(self).__name__} - Unknown orchestration algorithm "
                             f"'{manager.scenario.orchestration_algorithm}', expected {ALGORITHM}.")
        self.pending_per_node: list[int] = []
        self.decisions: dict[int, int] = {}

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        self.pending_per_node = [0] * len(self.candidates)

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        if not self.architecture_layers:
            return -1
        task = tasks[0]
        hard = task.type == "Hard Real-time"
        soft = task.type == "Soft Real-time"

        best, best_score = -1, float("inf")
        for index, node in enumerate(self.candidates):
            if not self.offloading_is_possible(node, task):
                continue
            delay = self._estimated_delay(task, node, index)
            if hard:
                slack = task.max_latency - delay
                score = -slack if slack >= 0 else DEADLINE_MISS_PENALTY + delay
            elif soft:
                score = delay / max(task.max_latency, 1e-9)
            else:
                score = self.estimated_energy(task, node) + delay * 1e-9
            if score < best_score:
                best_score, best = score, index

        if best >= 0:
            self.pending_per_node[best] += 1
            self.history[best] += 1
            self.decisions[task.id] = best
        return best

    def results_returned(self, task) -> None:
        node = self.decisions.pop(task.id, None)
        if node is not None and self.pending_per_node[node] > 0:
            self.pending_per_node[node] -= 1

    def estimated_delay(self, task, node: ComputingNode) -> float:
        """The estimated delay of a task on a node, exposed for the example test."""
        index = self.candidates.index(node) if node in self.candidates else 0
        return self._estimated_delay(task, node, index)

    def estimated_energy(self, task, node: ComputingNode) -> float:
        """The estimated energy of a task on a node, in watt-hours."""
        return node.energy_model.max_consumption * self._compute_time(task, node) / 3600.0

    def _estimated_delay(self, task, node: ComputingNode, index: int) -> float:
        delay = self._compute_time(task, node) * (1 + self.pending_per_node[index])
        link = task.source_device.up_link
        delay += link.delay if link is not None else 0.0
        if node.type == NodeType.CLOUD:
            delay += self.manager.parameters.wan_delay
        return delay

    @staticmethod
    def _compute_time(task, node: ComputingNode) -> float:
        capacity = node.mips_per_core * node.cores
        return task.length / max(1.0, capacity)


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str = OUTPUT) -> dict:
    """Run the scenario; the three arguments shrink it for the test suite."""
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    if devices is not None:
        parameters.min_number_of_devices = parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration is not None:
        parameters.simulation_duration = duration
    if seed is not None:
        parameters.random_seed = seed
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    simulation.set_custom_orchestrator(PriorityOrchestrator)
    row = simulation.launch()[0]
    print(f"{row[COLUMNS[1]]:<24} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} "
          f"ok={row[COLUMNS[8]]:>6} avg_delay={row[COLUMNS[4]]:<8} cloud={row[COLUMNS[15]]:>5} "
          f"edge={row[COLUMNS[17]]:>5} mist={row[COLUMNS[19]]:>5} energy={row[COLUMNS[32]]}")
    return row


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the three rules can be watched on a small map without editing
    # the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
