"""A tour of every extension point of the Simulation class.

    python examples/extension_points/extension_points.py

PureEdgeSim builds a scenario from interchangeable models, and `Simulation`
exposes one setter per model. This example registers one class for every point
the Python port offers, so the whole API is visible in one file:

    set_custom_simulation_manager      set_custom_topology_creator
    set_custom_network_model           set_custom_task_generator
    set_custom_computing_nodes_generator   set_custom_computing_node
    set_custom_mobility_model          set_custom_orchestrator

Each registered class only counts its own calls, prints the first one, and then
delegates to the default it extends, so the scenario is not modified. The
simulation is therefore launched twice: once with the stock models, once with the
tour, and the two CSV rows must be identical. That is the point of the example -
injecting a model is a wiring operation, and a model that only observes changes
nothing, exactly like registering a Java default explicitly does nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pureedgesim import (COLUMNS, ComputingNode, ComputingNodesGenerator, DefaultMobilityModel,
                       DefaultNetworkModel, DefaultOrchestrator, DefaultTaskGenerator,
                       DefaultTopologyCreator, NodeType, Simulation, SimulationManager,
                       load_parameters, load_settings)

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/extension_points/output"

# The hooks in the order the framework uses them, so the printed tour reads like
# the construction of a scenario: manager, models, topology, workload, events.
HOOKS = ("simulation manager", "network model", "computing nodes generator", "topology creator",
         "task generator", "mobility model", "orchestrator", "computing node")
USAGE: dict[str, int] = {}
CLASSES: dict[str, str] = {}


def record(hook: str, model: type, detail: str) -> None:
    """Counts one use of an extension point and announces the first one."""
    USAGE[hook] = USAGE.get(hook, 0) + 1
    CLASSES[hook] = model.__name__
    if USAGE[hook] == 1:
        print(f"{hook:<28} {model.__name__:<24} {detail}")


class TourSimulationManager(SimulationManager):
    """The manager itself is a hook: run_scenario builds the scenario with this class."""

    def start_simulation(self) -> None:
        record("simulation manager", type(self), f"scenario {self.scenario}")
        super().start_simulation()


class TourNetworkModel(DefaultNetworkModel):
    """Counts the transfers the network model routes."""

    def send(self, task, size: float, route, callback, description: str) -> None:
        record("network model", type(self), f"first transfer: {description}")
        super().send(task, size, route, callback, description)


class TourNodesGenerator(ComputingNodesGenerator):
    """Counts the fleets this generator built."""

    def generate(self, files, device_count: int) -> None:
        super().generate(files, device_count)
        record("computing nodes generator", type(self),
               f"{len(self.cloud_nodes)} cloud, {len(self.edge_data_centers)} edge, "
               f"{len(self.edge_devices)} devices")


class TourTopologyCreator(DefaultTopologyCreator):
    """Counts the links this creator wired."""

    def create(self) -> None:
        super().create()
        record("topology creator", type(self), f"{len(self.graph.links)} directed links")


class TourTaskGenerator(DefaultTaskGenerator):
    """Counts the pre-generated workload."""

    def generate(self):
        tasks = super().generate()
        record("task generator", type(self), f"{len(tasks)} tasks")
        return tasks


class TourMobilityModel(DefaultMobilityModel):
    """Counts the paths drawn for the devices that have no model of their own."""

    def generate_path(self) -> None:
        record("mobility model", type(self), f"starts at ({self.current_location.x_pos:.0f}, "
                                             f"{self.current_location.y_pos:.0f})")
        super().generate_path()


class TourOrchestrator(DefaultOrchestrator):
    """Counts the placement decisions taken by TRADE_OFF."""

    def orchestrate(self, task, application_id: int = 0):
        record("orchestrator", type(self), f"task {task.id} -> {task.source_device.name}")
        return super().orchestrate(task, application_id)


class TourComputingNode(ComputingNode):
    """The class every node is built from, cloud, edge and device alike."""

    @property
    def type(self) -> NodeType:
        return self._type

    @type.setter
    def type(self, node_type: NodeType) -> None:
        # One class builds every layer, so the generator assigns the type after the
        # constructor; is_peripheral is the flag the built-in edge class derives
        # from it, and the mobile devices need it to find their data centers.
        self._type = node_type
        self.is_peripheral = node_type == NodeType.EDGE_DATACENTER

    def process_event(self, event) -> None:
        record("computing node", type(self), f"{self.name} received its first event")
        super().process_event(event)


def simulation(custom: bool, devices: int | None = None, duration: float | None = None,
               seed: int | None = None, output: str | Path = OUTPUT) -> Simulation:
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    # The settings folder ships the ten minute, seven architecture sweep of the
    # Java example; one short scenario is enough to walk through the API.
    parameters.simulation_duration = duration if duration is not None else 300.0
    count = devices if devices is not None else 20
    parameters.min_number_of_devices = parameters.max_number_of_devices = count
    parameters.devices_increment = 1
    parameters.orchestration_architectures = ["ALL"]
    parameters.orchestration_algorithms = ["TRADE_OFF"]
    parameters.random_seed = seed if seed is not None else 7
    parameters.save_log_file = False
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    if not custom:
        return simulation
    return (simulation.set_custom_simulation_manager(TourSimulationManager)
            .set_custom_network_model(TourNetworkModel)
            .set_custom_computing_nodes_generator(TourNodesGenerator)
            .set_custom_topology_creator(TourTopologyCreator)
            .set_custom_task_generator(TourTaskGenerator)
            .set_custom_mobility_model(TourMobilityModel)
            .set_custom_orchestrator(TourOrchestrator)
            .set_custom_computing_node(TourComputingNode))


def key_metrics(row: dict) -> str:
    return (f"tasks={row[COLUMNS[7]]:>5} ok={row[COLUMNS[8]]:>5} avg_delay={row[COLUMNS[4]]:<8} "
            f"energy={row[COLUMNS[32]]:<8} cpu={row[COLUMNS[28]]}%")


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> tuple[dict, dict]:
    """Launches the scenario twice and returns the stock row next to the toured one."""
    USAGE.clear()
    CLASSES.clear()
    stock = simulation(False, devices, duration, seed, output).launch()[0]
    print("\nextension point                class                      first use")
    toured = simulation(True, devices, duration, seed, output).launch()[0]
    for hook in HOOKS:
        print(f"{hook:<28} {CLASSES.get(hook, 'not used'):<24} {USAGE.get(hook, 0):>6} uses")
    print(f"\n{'stock models':<28} {key_metrics(stock)}")
    print(f"{'eight custom models':<28} {key_metrics(toured)}")
    # Every observer only delegates, so the two runs must agree on every column.
    print(f"\nsame results with and without the custom classes: {stock == toured}")
    return stock, toured


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the tour can be walked through on a small map without editing
    # the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
