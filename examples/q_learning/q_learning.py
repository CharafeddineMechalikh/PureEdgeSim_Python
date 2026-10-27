"""Learn which tier should run each task, with tabular Q-learning.

    PYTHONPATH=src python examples/q_learning/q_learning.py

The placement policy is not written here, it is discovered. A state is the
application type, a coarse bucket of the task length, and a coarse bucket of the
pending load per node of the tier about to be used. An action is one of the tiers
the architecture allows, in the order cloud, edge, mist. The chosen tier executes
the task on its least loaded eligible node.

When the results of a task come back, ``results_returned`` turns the measured
total delay into a reward - the negated delay, or a large penalty when the task
failed - and applies the textbook update to the value of the tier that was chosen:

    value += LEARNING_RATE * (reward + DISCOUNT_RATE * max_value(next_state) - value)

The policy is epsilon-greedy, so one decision in ten explores another tier.

This module is also the shared home of the agent. The mist-only and the
edge-orchestrated examples import ``QLearningOrchestrator`` and only change the
scenario, exactly like their Java counterparts do, and the softmax example derives
its Boltzmann policy from the same class, so the state, the reward bookkeeping and
the update rule exist once.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from pureedgesim import (COLUMNS, DefaultOrchestrator, NodeType, Orchestrator, Simulation, Task,
                         TaskStatus, load_parameters, load_settings)

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/q_learning/output"

# The tiers in the order the Java orchestrator declares them for the ALL
# architecture, so an action index means the same tier in both simulators.
TIERS = (NodeType.CLOUD, NodeType.EDGE_DATACENTER, NodeType.EDGE_DEVICE)
LENGTH_BUCKETS = (1000.0, 5000.0, 20000.0)


def length_bucket(length: float) -> int:
    """The coarse size bucket of the state: under 1000, 5000 and 20000 MI."""
    for bucket, limit in enumerate(LENGTH_BUCKETS):
        if length < limit:
            return bucket
    return len(LENGTH_BUCKETS)


@dataclass
class _Decision:
    """What the agent keeps about a task it has placed, until the results return."""

    task: Task
    state: str
    action: int
    tier: NodeType
    node: int


class QLearningOrchestrator(Orchestrator):
    """Chooses the tier with an epsilon-greedy policy over a table of action values."""

    ALGORITHM = "Q_LEARNING"
    EXPLORATION_RATE = 0.1
    LEARNING_RATE = 0.2
    DISCOUNT_RATE = 0.9
    FAILURE_PENALTY = 1000.0

    def __init__(self, manager) -> None:
        super().__init__(manager)
        algorithm = manager.scenario.orchestration_algorithm
        if algorithm != self.ALGORITHM:
            raise ValueError(f"{type(self).__name__} - Unknown orchestration algorithm {algorithm!r}, "
                             f"expected {self.ALGORITHM}.")
        self.random = manager.random
        self.q_table: dict[str, list[float]] = {}
        self.decisions: dict[int, _Decision] = {}
        self.pending_per_tier: dict[NodeType, int] = {}
        self.layers: list[NodeType] = []
        self.node_load: list[int] = []

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        # The actions are the tiers the architecture allows; an unknown
        # architecture leaves none, and then no task can be placed.
        self.layers = [tier for tier in TIERS if tier in self.architecture_layers]
        self.node_load = [0] * len(self.candidates)

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        task = tasks[0]
        self.reconcile()
        if not self.layers:
            return -1
        options = self.available_nodes(task)
        if not options:
            return -1
        action, index = self.choose_action(task, options)
        tier = self.layers[action]
        self.node_load[index] += 1
        self.pending_per_tier[tier] = self.pending_per_tier.get(tier, 0) + 1
        self.decisions[task.id] = _Decision(task, self.state_key(task, tier), action, tier, index)
        return index

    def available_nodes(self, task) -> list[tuple[int, int]]:
        """The (action, candidate) pairs of the tiers this task can actually reach."""
        options: list[tuple[int, int]] = []
        for action, tier in enumerate(self.layers):
            index = self.node_in_tier(tier, task)
            if index >= 0:
                options.append((action, index))
        return options

    def choose_action(self, task, options: list[tuple[int, int]]) -> tuple[int, int]:
        """Epsilon-greedy: a random tier one decision in ten, the best value otherwise."""
        if self.random.random() < self.EXPLORATION_RATE:
            return options[self.random.randrange(len(options))]
        best, best_value = options[0], self._value(task, options[0][0])
        for option in options:
            value = self._value(task, option[0])
            if value > best_value:
                best, best_value = option, value
        return best

    def node_in_tier(self, tier: NodeType, task) -> int:
        """The least loaded eligible node of a tier, scored like TRADE_OFF.

        ``node_load`` counts the tasks the agent has placed on a candidate and is
        never brought back down, exactly like the Java ``assignments`` array, so a
        node that has already absorbed its share of the workload loses to one that
        has not: the tier spreads its tasks over its fleet instead of stacking them.
        """
        best, best_score = -1, float("inf")
        for index, node in enumerate(self.candidates):
            if node.type != tier or not self.offloading_is_possible(node, task):
                continue
            score = (self.node_load[index] + 1) * task.length / node.mips_per_core
            if score < best_score:
                best, best_score = index, score
        return best

    def results_returned(self, task: Task) -> None:
        """Learns from the delay the manager measured for this task."""
        self.observe(task, task.id)

    def observe(self, task: Task, task_id: int) -> None:
        decision = self.decisions.pop(task_id, None)
        if decision is None:
            return
        self.release(decision)
        reward = self.reward(task)
        values = self.q_table.setdefault(decision.state, [0.0] * len(self.layers))
        current = values[decision.action]
        values[decision.action] = current + self.LEARNING_RATE * (
            reward + self.DISCOUNT_RATE * self.max_value(self.state_key(task, decision.tier)) - current)

    def release(self, decision: _Decision) -> None:
        self.pending_per_tier[decision.tier] -= 1

    def reconcile(self) -> None:
        """Observes the tasks that failed before their results could come back.

        The Python manager notifies ``results_returned`` only when the results
        reach the device, while PureEdgeSim also notifies the orchestrator when a
        task fails on its way to the destination. Without this sweep the agent
        would never see those failures and the tier load would never come down.
        """
        for task_id, decision in list(self.decisions.items()):
            task = decision.task
            if task.failed or task.id in self.manager.finished_tasks:
                self.observe(task, task_id)

    def reward(self, task: Task) -> float:
        return -self.FAILURE_PENALTY if task.status != TaskStatus.SUCCESS else -task.total_delay

    def state_key(self, task: Task, tier: NodeType) -> str:
        return f"{task.type}|{length_bucket(task.length)}|{self.load_bucket(tier)}"

    def load_bucket(self, tier: NodeType) -> int:
        """0, 1 or 2 pending tasks per node of the tier, the third bucket being "more"."""
        nodes = sum(1 for node in self.candidates if node.type == tier)
        per_node = self.pending_per_tier.get(tier, 0) // nodes if nodes else 0
        return 0 if per_node == 0 else 1 if per_node <= 1 else 2

    def q_value(self, state: str, action: int) -> float:
        """The learned value of a state and action, 0 while the pair was never tried."""
        values = self.q_table.get(state)
        return 0.0 if values is None else values[action]

    def max_value(self, state: str) -> float:
        values = self.q_table.get(state)
        return 0.0 if not values else max(values)

    def _value(self, task: Task, action: int) -> float:
        return self.q_value(self.state_key(task, self.layers[action]), action)


def describe(row: dict) -> str:
    """The one-line summary the example prints for a scenario."""
    return (f"tasks={row[COLUMNS[7]]:>6} ok={row[COLUMNS[8]]:>6} avg_delay={row[COLUMNS[4]]:<8} "
            f"cloud={row[COLUMNS[15]]:>5} edge={row[COLUMNS[17]]:>5} mist={row[COLUMNS[19]]:>5} "
            f"failed(delay)={row[COLUMNS[10]]:>5} failed(mobility)={row[COLUMNS[12]]:>4} "
            f"energy={row[COLUMNS[32]]}")


def run(settings: Path, output: str | Path, orchestrator: type[QLearningOrchestrator] = QLearningOrchestrator,
        label: str = "q_learning", devices: int | None = None, duration: float | None = None,
        algorithms: list[str] | None = None, seed: int | None = None) -> dict:
    """Runs the sweep of the settings folder and prints one line per scenario.

    ``devices``, ``duration`` and ``seed`` shrink the scenario; the tests use them
    to keep a run under a second while keeping the real topology and workload
    files.
    """
    parameters = load_parameters(settings / "simulation_parameters.properties")
    if devices is not None:
        parameters.min_number_of_devices = devices
        parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration is not None:
        parameters.simulation_duration = duration
    if algorithms is not None:
        parameters.orchestration_algorithms = algorithms
    if seed is not None:
        parameters.random_seed = seed
    simulation = Simulation(settings, output, parameters, load_settings(settings))
    simulation.set_custom_orchestrator(orchestrator)
    rows = simulation.launch()
    for row in rows:
        print(f"{label:<24} {describe(row)}")
    return rows[-1]


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the learned policy and, on the same seed, the hand-written one to compare."""
    print("orchestration strategy, same seed and same workload:")
    run(SETTINGS, output, DefaultOrchestrator, "TRADE_OFF", devices, duration, ["TRADE_OFF"], seed)
    return run(SETTINGS, output, QLearningOrchestrator, "Q_LEARNING", devices, duration, None, seed)


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the learned table can be watched on a small map without editing
    # the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
