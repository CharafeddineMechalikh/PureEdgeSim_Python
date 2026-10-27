"""Context-aware deep reinforcement offloading over the three tiers.

    python examples/contextaware_drl/contextaware_drl.py

The action value of every layer is approximated by a small neural network whose
inputs describe the task and the device context: the application type, the task
length, the battery level, the access technology, the device mobility, and the
load of each tier. Unlike a table indexed by buckets, a context the agent has
never seen still produces a sensible value, because nearby contexts share the
same weights.

Training is online semi-gradient temporal-difference learning with a target
network refreshed every TARGET_SYNC updates. The reward is the negated delay
normalized by the task latency, and a failed task receives a penalty of one. The
network is written with plain Python lists, so the example keeps the
dependency-free promise of the package.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import NamedTuple

from pureedgesim import COLUMNS, Orchestrator, Simulation, TaskStatus, load_parameters, load_settings
from pureedgesim.nodes import ComputingNode, NodeType
from pureedgesim.randomness import Randomness

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/contextaware_drl/output"
ALGORITHM = "CONTEXT_AWARE"

HIDDEN_UNITS = 12
# Application type one-hot (3), length, battery, cellular, mobile, and 3 tier loads.
FEATURE_COUNT = 10
BATTERY_FEATURE = 4
CELLULAR_FEATURE = 5
MOBILE_FEATURE = 6
TIERS = ("Mist", "Edge", "Cloud")
TIER_OF_TYPE = {NodeType.EDGE_DEVICE: "Mist", NodeType.EDGE_DATACENTER: "Edge", NodeType.CLOUD: "Cloud"}
LENGTH_SCALE = 100_000.0
LEARNING_RATE = 0.02
DISCOUNT_RATE = 0.9
EPSILON_START = 0.3
EPSILON_END = 0.02
EPSILON_DECAY = 0.999
FAILURE_PENALTY = -1.0
TARGET_SYNC = 200


class Decision(NamedTuple):
    """What the agent must remember about a task until its results return."""

    state: list[float]
    action: int
    tier: str
    node: int


def _tier_of(node: ComputingNode) -> str:
    return TIER_OF_TYPE.get(node.type, "Unknown")


class ContextAwareOrchestrator(Orchestrator):
    """One multi-layer perceptron approximating the value of each tier."""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        if manager.scenario.orchestration_algorithm != ALGORITHM:
            raise ValueError(f"{type(self).__name__} - Unknown orchestration algorithm "
                             f"'{manager.scenario.orchestration_algorithm}', expected {ALGORITHM}.")
        self.random = Randomness.get_random()
        self.hidden_weights = [[(self.random.random() - 0.5) * 0.4 for _ in range(FEATURE_COUNT)]
                               for _ in range(HIDDEN_UNITS)]
        self.hidden_bias = [0.0] * HIDDEN_UNITS
        self.output_weights = [[(self.random.random() - 0.5) * 0.2 for _ in range(HIDDEN_UNITS)]
                               for _ in TIERS]
        self.output_bias = [0.0] * len(TIERS)
        self.target_hidden_weights = [row[:] for row in self.hidden_weights]
        self.target_hidden_bias = self.hidden_bias[:]
        self.target_output_weights = [row[:] for row in self.output_weights]
        self.target_output_bias = self.output_bias[:]
        self.pending_per_tier = {tier: 0 for tier in TIERS}
        self.decisions: dict[int, Decision] = {}
        self.pending_per_node: list[int] = []
        self.epsilon = EPSILON_START
        self.updates = 0

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        self.pending_per_node = [0] * len(self.candidates)

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        if not self.architecture_layers:
            return -1
        task = tasks[0]
        state = self.features(task)
        available = [action for action, tier in enumerate(TIERS)
                     if self._node_in_tier(tier, task) >= 0]
        if not available:
            return -1

        action = self._epsilon_greedy(state, available)
        tier = TIERS[action]
        index = self._node_in_tier(tier, task)
        self.pending_per_node[index] += 1
        self.pending_per_tier[tier] += 1
        self.history[index] += 1
        self.decisions[task.id] = Decision(state, action, tier, index)
        self.epsilon = max(EPSILON_END, self.epsilon * EPSILON_DECAY)
        return index

    def results_returned(self, task) -> None:
        decision = self.decisions.pop(task.id, None)
        if decision is None:
            return
        self.pending_per_tier[decision.tier] -= 1
        if self.pending_per_node[decision.node] > 0:
            self.pending_per_node[decision.node] -= 1

        if task.status == TaskStatus.SUCCESS:
            reward = -task.total_delay / max(task.max_latency, 1e-9)
        else:
            reward = FAILURE_PENALTY
        self._train(decision.state, decision.action, reward, self.features(task))

    def features(self, task) -> list[float]:
        """The context vector of a task: the state seen by the network."""
        state = [0.0] * FEATURE_COUNT
        state[{"Hard Real-time": 0, "Soft Real-time": 1}.get(task.type, 2)] = 1.0
        state[3] = min(1.0, task.length / LENGTH_SCALE)

        device = task.source_device
        energy = device.energy_model
        # A device without a battery is treated as full, so the feature never
        # penalises a mains-powered laptop.
        if energy.battery_powered:
            state[BATTERY_FEATURE] = device.get_remaining_battery_percentage() / 100.0
        else:
            state[BATTERY_FEATURE] = 1.0
        state[CELLULAR_FEATURE] = 1.0 if energy.connectivity == "cellular" else 0.0
        model = device.mobility_model
        state[MOBILE_FEATURE] = 1.0 if model is not None and model.is_mobile else 0.0

        for offset, tier in enumerate(TIERS, start=7):
            state[offset] = self._load(tier)
        return state

    def q_value(self, state: list[float], action: int) -> float:
        """The value the online network gives to a state and a canonical tier action."""
        return self._forward(state, self.hidden_weights, self.hidden_bias,
                             self.output_weights, self.output_bias)[action]

    def _epsilon_greedy(self, state: list[float], available: list[int]) -> int:
        if self.random.random() < self.epsilon:
            return available[self.random.randrange(len(available))]
        values = self._forward(state, self.hidden_weights, self.hidden_bias,
                               self.output_weights, self.output_bias)
        best = available[0]
        for action in available:
            if values[action] > values[best]:
                best = action
        return best

    def _train(self, state: list[float], action: int, reward: float, next_state: list[float]) -> None:
        target = reward + DISCOUNT_RATE * self._max_target_value(next_state)

        hidden = self._activation(state, self.hidden_weights, self.hidden_bias)
        output = self._output(hidden, self.output_weights, self.output_bias)
        delta = max(-1.0, min(1.0, target - output[action]))

        for unit in range(HIDDEN_UNITS):
            self.output_weights[action][unit] += LEARNING_RATE * delta * hidden[unit]
        self.output_bias[action] += LEARNING_RATE * delta

        # The hidden gradient uses the output weights of this same step, as the
        # semi-gradient update of the reference implementation does.
        hidden_gradient = [delta * self.output_weights[action][unit] * (1 - hidden[unit] * hidden[unit])
                           for unit in range(HIDDEN_UNITS)]
        for unit in range(HIDDEN_UNITS):
            row = self.hidden_weights[unit]
            gradient = LEARNING_RATE * hidden_gradient[unit]
            for feature in range(FEATURE_COUNT):
                row[feature] += gradient * state[feature]
            self.hidden_bias[unit] += LEARNING_RATE * hidden_gradient[unit]

        self.updates += 1
        if self.updates % TARGET_SYNC == 0:
            self._synchronize_target()

    def _max_target_value(self, state: list[float]) -> float:
        values = self._forward(state, self.target_hidden_weights, self.target_hidden_bias,
                               self.target_output_weights, self.target_output_bias)
        return max(values)

    def _synchronize_target(self) -> None:
        self.target_hidden_weights = [row[:] for row in self.hidden_weights]
        self.target_hidden_bias = self.hidden_bias[:]
        self.target_output_weights = [row[:] for row in self.output_weights]
        self.target_output_bias = self.output_bias[:]

    def _load(self, tier: str) -> float:
        nodes = sum(1 for node in self.candidates if _tier_of(node) == tier)
        average = 0.0 if nodes == 0 else self.pending_per_tier[tier] / nodes
        return min(1.0, average / 2.0)

    def _forward(self, state, hidden_weights, hidden_bias, output_weights, output_bias) -> list[float]:
        return self._output(self._activation(state, hidden_weights, hidden_bias),
                            output_weights, output_bias)

    @staticmethod
    def _activation(state, weights, bias) -> list[float]:
        hidden = []
        for unit in range(HIDDEN_UNITS):
            total = bias[unit]
            row = weights[unit]
            for feature in range(FEATURE_COUNT):
                total += row[feature] * state[feature]
            hidden.append(math.tanh(total))
        return hidden

    @staticmethod
    def _output(hidden, weights, bias) -> list[float]:
        values = []
        for tier in range(len(TIERS)):
            total = bias[tier]
            row = weights[tier]
            for unit in range(HIDDEN_UNITS):
                total += row[unit] * hidden[unit]
            values.append(total)
        return values

    def _node_in_tier(self, tier: str, task) -> int:
        """The least loaded eligible node of a tier, as a candidate index."""
        best, best_pending = -1, len(self.candidates) + 1
        for index, node in enumerate(self.candidates):
            if _tier_of(node) != tier or not self.offloading_is_possible(node, task):
                continue
            if self.pending_per_node[index] < best_pending:
                best_pending, best = self.pending_per_node[index], index
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
    simulation.set_custom_orchestrator(ContextAwareOrchestrator)
    row = simulation.launch()[0]
    print(f"{row[COLUMNS[1]]:<24} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} "
          f"ok={row[COLUMNS[8]]:>6} avg_delay={row[COLUMNS[4]]:<8} cloud={row[COLUMNS[15]]:>5} "
          f"edge={row[COLUMNS[17]]:>5} mist={row[COLUMNS[19]]:>5} energy={row[COLUMNS[32]]}")
    return row


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the behaviour can be watched on a small map without editing the
    # settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
