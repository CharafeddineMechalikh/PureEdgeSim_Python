"""Partition a service graph with graph theory and spread it over the tiers.

    python examples/graph_partitioning/graph_partitioning.py

The video analytics application is a service graph: one request is a pipeline of
seven subtasks, not a single task. This orchestrator reads that graph before the
simulation starts and cuts it into balanced partitions with `GraphPartitioner`,
which separates the weakly connected components, assigns the heaviest steps
first, then exchanges pairs of steps while the exchange removes dependency edges.

Each partition is mapped to a tier in the order mist, edge, cloud, so the stages
of the pipeline run further and further from the device. The console prints the
partitions, their loads and the edge cut, followed by the run summary. Compare
that cut with the plan of `examples/genetic_partitioning.py`, which searches for
a placement instead of deriving it from the graph structure.
"""
from __future__ import annotations

from pathlib import Path

from pureedgesim import COLUMNS, NodeType, Orchestrator, Simulation, load_parameters, load_settings

from pureedgesim.partitioning import GraphPartitioner, ServiceGraph

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/graph_partitioning/output"
PARTITIONS_PER_COMPONENT = 3
TIERS = (("Mist", NodeType.EDGE_DEVICE), ("Edge", NodeType.EDGE_DATACENTER), ("Cloud", NodeType.CLOUD))


class GraphPartitioningOrchestrator(Orchestrator):
    """Places every subtask on the tier assigned to its partition."""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self.plans = {}
        self.cursors = {}
        self.tiers: list[NodeType] = []

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        self.tiers = [node_type for _, node_type in TIERS if node_type in self.architecture_layers]
        for application_id, application in enumerate(self.manager.applications):
            if not application.has_subtasks:
                continue
            plan = GraphPartitioner().partition(ServiceGraph.of(application), PARTITIONS_PER_COMPONENT)
            self.plans[application_id] = plan
            print(f"{type(self).__name__} - Application {application_id} ({application.type}): "
                  f"{plan.describe()}")

    def orchestrate(self, task, application_id: int = 0):
        destination = super().orchestrate(task, application_id)
        # The manager reuses the placement of an application until it is invalidated,
        # so each subtask of one request must clear it to be decided on its own.
        task.source_device.application_placed = False
        return destination

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        task = tasks[0]
        plan = self.plans.get(application_id)
        partition = None if plan is None or task.subtask_name is None \
            else plan.partition_of.get(task.subtask_name)
        if partition is not None:
            index = self._node_of_tier(task, partition)
            if index >= 0:
                return index
        eligible = [(index, node) for index, node in enumerate(self.candidates)
                    if self.offloading_is_possible(node, task)]
        if not eligible:
            return -1
        index = self.trade_off(eligible, task)
        self.history[index] += 1
        return index

    def _node_of_tier(self, task, partition: int) -> int:
        if not self.tiers:
            return -1
        expected = self.tiers[partition % len(self.tiers)]
        eligible = [index for index, node in enumerate(self.candidates)
                    if node.type == expected and self.offloading_is_possible(node, task)]
        if not eligible:
            return -1
        cursor = self.cursors.get(partition, 0)
        index = eligible[cursor % len(eligible)]
        self.cursors[partition] = cursor + 1
        self.history[index] += 1
        return index


def main() -> None:
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    simulation = Simulation(SETTINGS, OUTPUT, parameters, load_settings(SETTINGS))
    simulation.set_custom_orchestrator(GraphPartitioningOrchestrator)
    row = simulation.launch()[0]
    print(f"\ntasks={row[COLUMNS[7]]:>5} ok={row[COLUMNS[8]]:>5} avg_delay={row[COLUMNS[4]]:<8} "
          f"cloud={row[COLUMNS[15]]:>4} edge={row[COLUMNS[17]]:>4} mist={row[COLUMNS[19]]:>4} "
          f"failed(dependency)={row[COLUMNS[14]]:>4} energy={row[COLUMNS[32]]}")


if __name__ == "__main__":
    main()
