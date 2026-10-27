"""A three-layer fog: fill the mist, then overflow to the edge, then to the cloud.

    python examples/fog_layers/fog_layers.py

Port of the Java `Example13FogLayersOrchestrator`. 200 sensors and 100 home
gateways share a smart home, one edge data center covers the neighbourhood and
the cloud is the last resort. The policy walks the layers in the order mist,
edge, cloud, stops at the first layer holding a feasible node, and takes the
least loaded node of that layer, so the gateways are filled before a task moves
outward.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from pureedgesim import COLUMNS, NodeType, Orchestrator, SimEntity, Simulation, load_parameters, load_settings

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/fog_layers/output"
ALGORITHM = "FOG_LAYERS"
# The preference order of a multi-layer fog, innermost layer first.
PREFERENCE = (("Mist", NodeType.EDGE_DEVICE), ("Edge", NodeType.EDGE_DATACENTER), ("Cloud", NodeType.CLOUD))
TIER_NAMES = {node_type: name for name, node_type in PREFERENCE}


class FogLayersOrchestrator(SimEntity, Orchestrator):
    """The first layer that has a feasible node keeps the task."""

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
        chosen = -1
        for node_type in (tier_type for _, tier_type in PREFERENCE):
            if node_type not in self.architecture_layers:
                continue
            chosen = self._least_loaded_in(node_type, task)
            if chosen >= 0:
                break
        if chosen >= 0:
            self.pending[chosen] += 1
            self.history[chosen] += 1
            self.decisions[task.id] = chosen
            self.placements[TIER_NAMES[self.candidates[chosen].type]] += 1
        return chosen

    def results_returned(self, task) -> None:
        index = self.decisions.pop(task.id, None)
        if index is not None and self.pending[index] > 0:
            self.pending[index] -= 1

    def pending_on(self, index: int) -> int:
        """The number of tasks still in flight on one candidate, exposed for tests."""
        return self.pending[index]

    def _least_loaded_in(self, node_type: NodeType, task) -> int:
        best, best_load = -1, float("inf")
        for index, node in enumerate(self.candidates):
            if node.type is not node_type or not self.offloading_is_possible(node, task):
                continue
            if self.pending[index] < best_load:
                # A strict comparison keeps the first node of the layer when two
                # are equally idle, like the Java loop.
                best, best_load = index, self.pending[index]
        return best

    def on_simulation_end(self) -> None:
        placements = ", ".join(f"{tier}={count}" for tier, count in sorted(self.placements.items(),
                                                                          key=lambda pair: -pair[1]))
        print(f"FogLayersOrchestrator - placements per layer: {placements or 'none'}")


def run(label: str = "FOG_LAYERS", devices: int | None = None, duration: float | None = None,
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
    simulation.set_custom_orchestrator(FogLayersOrchestrator)
    row = simulation.launch()[0]
    print(f"{label:<16} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} ok={row[COLUMNS[8]]:>6} "
          f"failed(delay)={row[COLUMNS[10]]:>5} avg_delay={row[COLUMNS[4]]:<8} "
          f"cloud={row[COLUMNS[15]]:>4} edge={row[COLUMNS[17]]:>4} mist={row[COLUMNS[19]]:>5} "
          f"energy={row[COLUMNS[32]]}")
    return row


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the fog scenario; the arguments shrink it for a quick check."""
    return run("FOG_LAYERS", devices, duration, seed, output)


if __name__ == "__main__":
    main()
