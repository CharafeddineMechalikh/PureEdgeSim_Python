"""Multi-objective reinforcement learning: two value tables, one weighted decision.

    python examples/multi_objective/multi_objective.py

The agent learns the delay and the energy of every tier separately, then combines
them with fixed weights when it chooses. Two tables keep the objectives
distinguishable, so the weights can be changed without retraining from scratch,
and the energy table makes the agent aware that a cloud task consumes far more
than a mist one. The delay reward is the negated delay normalized by the task
latency; the energy reward is the negated estimated energy normalized by a
reference of REFERENCE_ENERGY_WH. A failed task applies the same penalty to both
tables.

The state is the application type and the task-length bucket, the actions are the
tiers allowed by the architecture.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

from pureedgesim import COLUMNS, Orchestrator, Simulation, TaskStatus, load_parameters, load_settings
from pureedgesim.nodes import ComputingNode, NodeType
from pureedgesim.randomness import Randomness

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/multi_objective/output"
ALGORITHM = "SCALARIZED_Q"

DELAY_WEIGHT = 1.0
ENERGY_WEIGHT = 1.0
# The energy, in watt-hours, that maps to a reward of minus one.
REFERENCE_ENERGY_WH = 0.01
LEARNING_RATE = 0.2
DISCOUNT_RATE = 0.9
EPSILON = 0.1
FAILURE_PENALTY = 200.0

TIER_OF_TYPE = {NodeType.EDGE_DEVICE: "Mist", NodeType.EDGE_DATACENTER: "Edge", NodeType.CLOUD: "Cloud"}


def _tier_of(node: ComputingNode) -> str:
    return TIER_OF_TYPE.get(node.type, "Unknown")


class Decision(NamedTuple):
    state: str
    action: int
    node: int


class MultiObjectiveOrchestrator(Orchestrator):
    """Q-learning over a delay table and an energy table, scalarized at decision time."""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        if manager.scenario.orchestration_algorithm != ALGORITHM:
            raise ValueError(f"{type(self).__name__} - Unknown orchestration algorithm "
                             f"'{manager.scenario.orchestration_algorithm}', expected {ALGORITHM}.")
        self.random = Randomness.get_random()
        self.delay_values: dict[str, list[float]] = {}
        self.energy_values: dict[str, list[float]] = {}
        self.decisions: dict[int, Decision] = {}
        self.pending_per_node: list[int] = []
        self.actions: tuple[str, ...] = ()

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        self.pending_per_node = [0] * len(self.candidates)
        # One action per tier the architecture allows; the tables keep one value
        # per action, exactly like the Java agent.
        self.actions = tuple(TIER_OF_TYPE[layer] for layer in self.architecture_layers)

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        if not self.architecture_layers:
            return -1
        task = tasks[0]
        state = self.state_key(task)

        if self.random.random() < EPSILON:
            action = self._random_feasible_action(task)
        else:
            action, best_score = -1, float("-inf")
            for index, tier in enumerate(self.actions):
                if self._node_in_tier(tier, task) < 0:
                    continue
                score = (DELAY_WEIGHT * self._value(self.delay_values, state, index)
                         + ENERGY_WEIGHT * self._value(self.energy_values, state, index))
                if score > best_score:
                    best_score, action = score, index
        if action < 0:
            return -1

        index = self._node_in_tier(self.actions[action], task)
        self.pending_per_node[index] += 1
        self.history[index] += 1
        self.decisions[task.id] = Decision(state, action, index)
        return index

    def results_returned(self, task) -> None:
        decision = self.decisions.pop(task.id, None)
        if decision is None:
            return
        if self.pending_per_node[decision.node] > 0:
            self.pending_per_node[decision.node] -= 1

        if task.status == TaskStatus.SUCCESS:
            delay_reward = -task.total_delay / max(task.max_latency, 1e-9)
            energy_reward = -self.estimated_energy(task, decision.node) / REFERENCE_ENERGY_WH
        else:
            delay_reward = -FAILURE_PENALTY
            energy_reward = -FAILURE_PENALTY
        self._update(self.delay_values, decision.state, decision.action, delay_reward)
        self._update(self.energy_values, decision.state, decision.action, energy_reward)

    def delay_value(self, state: str, action: int) -> float:
        """The delay value of a state and action, exposed for the example test."""
        return self._value(self.delay_values, state, action)

    def energy_value(self, state: str, action: int) -> float:
        """The energy value of a state and action, exposed for the example test."""
        return self._value(self.energy_values, state, action)

    def state_key(self, task) -> str:
        """The state shared by both tables: the application type and a length bucket."""
        length = task.length
        bucket = 0 if length < 1000 else 1 if length < 5000 else 2 if length < 20000 else 3
        return f"{task.type}|{bucket}"

    def estimated_energy(self, task, node_index: int) -> float:
        """The estimated energy, in watt-hours, of a task on the node at that index."""
        node = self.candidates[node_index]
        capacity = max(1.0, node.mips_per_core * node.cores)
        return node.energy_model.max_consumption * (task.length / capacity) / 3600.0

    def _update(self, table: dict[str, list[float]], state: str, action: int, reward: float) -> None:
        values = table.setdefault(state, [0.0] * len(self.actions))
        values[action] += LEARNING_RATE * (reward + DISCOUNT_RATE * self._max_value(table, state) - values[action])

    def _random_feasible_action(self, task) -> int:
        """Reservoir sampling over the feasible tiers, as in the Java agent."""
        feasible, chosen = 0, -1
        for index, tier in enumerate(self.actions):
            if self._node_in_tier(tier, task) < 0:
                continue
            feasible += 1
            if self.random.randrange(feasible) == 0:
                chosen = index
        return chosen

    def _node_in_tier(self, tier: str, task) -> int:
        """The least loaded eligible node of a tier, as a candidate index."""
        best, best_pending = -1, len(self.candidates) + 1
        for index, node in enumerate(self.candidates):
            if _tier_of(node) != tier or not self.offloading_is_possible(node, task):
                continue
            if self.pending_per_node[index] < best_pending:
                best_pending, best = self.pending_per_node[index], index
        return best

    @staticmethod
    def _value(table: dict[str, list[float]], state: str, action: int) -> float:
        values = table.get(state)
        return 0.0 if values is None else values[action]

    @staticmethod
    def _max_value(table: dict[str, list[float]], state: str) -> float:
        values = table.get(state)
        # An unseen state has no value to bootstrap from, so the target is just
        # the immediate reward.
        return 0.0 if not values else max(values)


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
    simulation.set_custom_orchestrator(MultiObjectiveOrchestrator)
    row = simulation.launch()[0]
    print(f"{row[COLUMNS[1]]:<24} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} "
          f"ok={row[COLUMNS[8]]:>6} avg_delay={row[COLUMNS[4]]:<8} cloud={row[COLUMNS[15]]:>5} "
          f"edge={row[COLUMNS[17]]:>5} mist={row[COLUMNS[19]]:>5} energy={row[COLUMNS[32]]}")
    return row


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the two tables can be watched on a small map without editing
    # the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
