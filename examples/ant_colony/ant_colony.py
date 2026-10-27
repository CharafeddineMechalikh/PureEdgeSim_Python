"""Ant colony orchestration: a pheromone trail per tier, sampled with a delay heuristic.

    python examples/ant_colony/ant_colony.py

Every tier lays a pheromone trail that grows when the tasks sent there meet their
latency and evaporates when they fail, so the colony converges on the tiers that
work for the current workload. A placement is sampled from a probability that
multiplies the trail by a heuristic desirability, the inverse of the estimated
delay, so a good tier is preferred from the first task while the trail keeps
adapting. Inside the chosen tier, the node with the smallest estimated delay,
including the tasks already pending on it, executes the task.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

from pureedgesim import COLUMNS, Orchestrator, Simulation, TaskStatus, load_parameters, load_settings
from pureedgesim.nodes import ComputingNode, NodeType
from pureedgesim.randomness import Randomness

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/ant_colony/output"
ALGORITHM = "ANT_COLONY"

EVAPORATION = 0.1
ALPHA = 1.0
BETA = 2.0
INITIAL_PHEROMONE = 0.5
# A trail never reaches zero, so no tier becomes unreachable, and it never
# saturates, so one early success cannot lock the choice.
MIN_PHEROMONE = 0.05
MAX_PHEROMONE = 5.0

TIERS = ("Mist", "Edge", "Cloud")
TIER_OF_TYPE = {NodeType.EDGE_DEVICE: "Mist", NodeType.EDGE_DATACENTER: "Edge", NodeType.CLOUD: "Cloud"}


def _tier_of(node: ComputingNode) -> str:
    return TIER_OF_TYPE.get(node.type, "Unknown")


class Candidate(NamedTuple):
    tier: str
    node: int
    weight: float


class Decision(NamedTuple):
    tier: str
    node: int


class AntColonyOrchestrator(Orchestrator):
    """Pheromone over the three tiers, sampled against a delay heuristic."""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        if manager.scenario.orchestration_algorithm != ALGORITHM:
            raise ValueError(f"{type(self).__name__} - Unknown orchestration algorithm "
                             f"'{manager.scenario.orchestration_algorithm}', expected {ALGORITHM}.")
        self.random = Randomness.get_random()
        self.pheromone = {tier: INITIAL_PHEROMONE for tier in TIERS}
        self.decisions: dict[int, Decision] = {}
        self.pending_per_node: list[int] = []

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        self.pending_per_node = [0] * len(self.candidates)

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        if not self.architecture_layers:
            return -1
        task = tasks[0]

        candidates: list[Candidate] = []
        total = 0.0
        for tier in TIERS:
            index = self._best_node(tier, task)
            if index < 0:
                continue
            delay = self.estimated_delay(task, self.candidates[index]) * (1 + self.pending_per_node[index])
            weight = (self.pheromone[tier] ** ALPHA) / ((1 + delay) ** BETA)
            candidates.append(Candidate(tier, index, weight))
            total += weight
        if not candidates:
            return -1

        chosen = self._sample(candidates, total)
        self.pending_per_node[chosen.node] += 1
        self.history[chosen.node] += 1
        self.decisions[task.id] = Decision(chosen.tier, chosen.node)
        return chosen.node

    def results_returned(self, task) -> None:
        decision = self.decisions.pop(task.id, None)
        if decision is None:
            return
        if self.pending_per_node[decision.node] > 0:
            self.pending_per_node[decision.node] -= 1

        if task.status == TaskStatus.SUCCESS:
            quality = task.max_latency / (task.max_latency + task.total_delay)
        else:
            quality = 0.0
        trail = (1 - EVAPORATION) * self.pheromone[decision.tier] + EVAPORATION * quality
        self.pheromone[decision.tier] = max(MIN_PHEROMONE, min(MAX_PHEROMONE, trail))

    def estimated_delay(self, task, node: ComputingNode) -> float:
        """The delay the colony expects when a task runs on the given node."""
        capacity = max(1.0, node.mips_per_core * node.cores)
        compute = task.length / capacity
        link = task.source_device.up_link
        access = link.delay if link is not None else 0.0
        if node.type == NodeType.CLOUD:
            access += self.manager.parameters.wan_delay
        return compute + access

    def pheromone_of(self, tier: str) -> float:
        """The current trail of a tier, for the example test and the reports."""
        return self.pheromone.get(tier, INITIAL_PHEROMONE)

    def _sample(self, candidates: list[Candidate], total: float) -> Candidate:
        draw = self.random.random() * total
        # The last candidate is the fallback when rounding eats the whole draw.
        chosen = candidates[-1]
        for candidate in candidates:
            draw -= candidate.weight
            if draw <= 0:
                chosen = candidate
                break
        return chosen

    def _best_node(self, tier: str, task) -> int:
        """The eligible node of a tier with the smallest estimated delay."""
        best, best_delay = -1, float("inf")
        for index, node in enumerate(self.candidates):
            if _tier_of(node) != tier or not self.offloading_is_possible(node, task):
                continue
            delay = self.estimated_delay(task, node) * (1 + self.pending_per_node[index])
            if delay < best_delay:
                best_delay, best = delay, index
        return best


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
    simulation.set_custom_orchestrator(AntColonyOrchestrator)
    row = simulation.launch()[0]
    print(f"{row[COLUMNS[1]]:<24} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} "
          f"ok={row[COLUMNS[8]]:>6} avg_delay={row[COLUMNS[4]]:<8} cloud={row[COLUMNS[15]]:>5} "
          f"edge={row[COLUMNS[17]]:>5} mist={row[COLUMNS[19]]:>5} energy={row[COLUMNS[32]]}")
    return row


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the trail can be watched on a small map without editing the
    # settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
