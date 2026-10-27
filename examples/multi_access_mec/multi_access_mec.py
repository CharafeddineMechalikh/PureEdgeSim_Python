"""Multi-access MEC: the access technology takes part in the placement decision.

    python examples/multi_access_mec/multi_access_mec.py

Port of the Java `Example12AccessAwareOrchestrator`. 300 devices reach four edge
data centers over Wi-Fi or cellular, and every candidate tier is scored from the
transfer delay of the access link, the compute delay on the node, and the tasks
the node already has pending. The lowest score wins, so the same task can prefer
another tier depending on the radio it was generated over.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from pureedgesim import COLUMNS, NodeType, Orchestrator, SimEntity, Simulation, load_parameters, load_settings

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/multi_access_mec/output"
ALGORITHM = "ACCESS_AWARE"
TIER_NAMES = {NodeType.CLOUD: "cloud", NodeType.EDGE_DATACENTER: "edge", NodeType.EDGE_DEVICE: "mist"}


class AccessAwareOrchestrator(SimEntity, Orchestrator):
    """Scores each allowed node from its access link, its speed and its queue."""

    def __init__(self, manager) -> None:
        SimEntity.__init__(self, manager.engine)
        Orchestrator.__init__(self, manager)
        algorithm = manager.scenario.orchestration_algorithm
        if algorithm != ALGORITHM:
            raise ValueError(f"{type(self).__name__} - unknown orchestration algorithm {algorithm!r}, "
                             f"expected {ALGORITHM}.")
        self.pending: dict[int, int] = {}
        self.decisions: dict[int, int] = {}
        self.placements: Counter = Counter()

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        self.pending = {index: 0 for index in range(len(self.candidates))}

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        task = tasks[0]
        best, best_score = -1, float("inf")
        for index, node in enumerate(self.candidates):
            if not self.offloading_is_possible(node, task):
                continue
            score = self.estimate_delay(task, node) + self.queued_delay(task, index)
            if score < best_score:
                best, best_score = index, score
        if best >= 0:
            self.pending[best] += 1
            self.history[best] += 1
            self.decisions[task.id] = best
            self.placements[(task.source_device.energy_model.connectivity,
                             TIER_NAMES[self.candidates[best].type])] += 1
        return best

    def results_returned(self, task) -> None:
        index = self.decisions.pop(task.id, None)
        if index is not None and self.pending[index] > 0:
            self.pending[index] -= 1

    def estimate_delay(self, task, node) -> float:
        """The delay the orchestrator attributes to this node: compute plus access."""
        return self.compute_delay(task, node) + self.access_delay(task, node)

    @staticmethod
    def compute_delay(task, node) -> float:
        return task.length / node.mips_per_core if node.mips_per_core > 0 else float("inf")

    def queued_delay(self, task, index: int) -> float:
        """One task already in the queue delays this one by its share of the cores."""
        node = self.candidates[index]
        cores = max(1, int(node.cores))
        return self.pending[index] * self.compute_delay(task, node) / cores

    def access_delay(self, task, node) -> float:
        parameters = self.manager.parameters
        transfer = task.request_size + task.result_size
        if node.type == NodeType.CLOUD:
            # Cloud candidates pay the access hop and then the WAN hop on top of it.
            return (self.uplink_delay(task, transfer) + parameters.wan_delay
                    + transfer / parameters.wan_bandwidth)
        if node.type == NodeType.EDGE_DATACENTER:
            return self.uplink_delay(task, transfer)
        return parameters.wifi_delay + transfer / parameters.wifi_bandwidth

    def uplink_delay(self, task, transfer: float) -> float:
        parameters = self.manager.parameters
        if task.source_device.energy_model.connectivity == "cellular":
            return parameters.cellular_delay + transfer / parameters.cellular_bandwidth
        return parameters.wifi_delay + transfer / parameters.wifi_bandwidth

    def on_simulation_end(self) -> None:
        print(f"AccessAwareOrchestrator - placements by access technology and tier: "
              f"{', '.join(f'{technology}/{tier}={count}' for (technology, tier), count
                          in sorted(self.placements.items())) or 'none'}")


def run(label: str = "ACCESS_AWARE", devices: int | None = None, duration: float | None = None,
        seed: int | None = None, output: str | Path = OUTPUT) -> dict:
    """One full scenario; the optional arguments shrink it for a quick check."""
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    if devices is not None:
        parameters.min_number_of_devices = parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration is not None:
        parameters.simulation_duration = duration
    if seed is not None:
        parameters.random_seed = seed
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    simulation.set_custom_orchestrator(AccessAwareOrchestrator)
    row = simulation.launch()[0]
    print(f"{label:<16} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} ok={row[COLUMNS[8]]:>6} "
          f"failed(delay)={row[COLUMNS[10]]:>5} avg_delay={row[COLUMNS[4]]:<8} "
          f"cloud={row[COLUMNS[15]]:>4} edge={row[COLUMNS[17]]:>5} mist={row[COLUMNS[19]]:>4} "
          f"wan_usage={row[COLUMNS[22]]:<9} energy={row[COLUMNS[32]]}")
    return row


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the multi-access scenario; the arguments shrink it for a quick check."""
    return run("ACCESS_AWARE", devices, duration, seed, output)


if __name__ == "__main__":
    main()
