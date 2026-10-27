"""Search a subtask placement with a genetic algorithm.

    python examples/genetic_partitioning/genetic_partitioning.py

The video analytics application is a service graph, so one request is a pipeline
of seven subtasks. `GeneticPartitioner` searches the node of every subtask: each
chromosome holds one gene per subtask, and its fitness estimates the makespan of
the pipeline plus the cost of transferring results between nodes and the load
imbalance between the nodes actually used. Subtasks that share a node form a
partition.

The plan is static: it is computed once, from the mean task lengths and result
sizes, before any device moves. When the chosen node is not eligible for a
request (a mist device that is now out of range, for example), the subtask falls
back to the default policy. The console prints the estimated fitness and the node
chosen for each subtask. Compare it with the cut found by
`examples/graph_partitioning.py`.
"""
from __future__ import annotations

from pathlib import Path

from pureedgesim import COLUMNS, NodeType, Orchestrator, Simulation, load_parameters, load_settings

from pureedgesim.partitioning import Candidate, GeneticPartitioner, ServiceGraph

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/genetic_partitioning/output"
DEFAULT_SEED = 20261026


class GeneticOrchestrator(Orchestrator):
    """Places every subtask on the node chosen by the genetic algorithm."""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self.placement: dict[int, dict[str, int]] = {}
        self.gene_nodes = []
        self.gene_indices: list[int] = []

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        candidates = []
        seen = set()
        for index, node in enumerate(self.candidates):
            if node.id in seen:
                continue
            seen.add(node.id)
            candidates.append(Candidate(node.id, self._label(node), node.mips_per_core, self._bandwidth(node)))
            self.gene_nodes.append(node)
            self.gene_indices.append(index)

        seed = self.manager.parameters.random_seed
        seed = DEFAULT_SEED if seed is None else seed
        gene_of = {candidate.id: gene for gene, candidate in enumerate(candidates)}
        for application_id, application in enumerate(self.manager.applications):
            if not application.has_subtasks:
                continue
            plan = GeneticPartitioner(seed).partition(ServiceGraph.of(application), candidates)
            self.placement[application_id] = {name: gene_of[candidate.id]
                                              for name, candidate in plan.node_of.items()}
            print(f"{type(self).__name__} - Application {application_id} ({application.type}): "
                  f"{plan.describe()}")

    def orchestrate(self, task, application_id: int = 0):
        destination = super().orchestrate(task, application_id)
        # The plan assigns different subtasks of one request to different nodes, so
        # the placement cache must be cleared before the next subtask arrives.
        task.source_device.application_placed = False
        return destination

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        task = tasks[0]
        genes = self.placement.get(application_id)
        gene = None if genes is None or task.subtask_name is None else genes.get(task.subtask_name)
        if gene is not None:
            index = self.gene_indices[gene]
            if self.offloading_is_possible(self.gene_nodes[gene], task):
                self.history[index] += 1
                return index
        eligible = [(index, node) for index, node in enumerate(self.candidates)
                    if self.offloading_is_possible(node, task)]
        if not eligible:
            return -1
        index = self.trade_off(eligible, task)
        self.history[index] += 1
        return index

    def _label(self, node) -> str:
        if node.type == NodeType.CLOUD:
            return "Cloud"
        if node.type == NodeType.EDGE_DATACENTER:
            return "Edge"
        return "Mist"

    def _bandwidth(self, node) -> float:
        parameters = self.manager.parameters
        if node.type == NodeType.CLOUD:
            return parameters.wan_bandwidth
        if node.type == NodeType.EDGE_DATACENTER:
            return parameters.man_bandwidth
        return parameters.wifi_bandwidth


def main() -> None:
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    simulation = Simulation(SETTINGS, OUTPUT, parameters, load_settings(SETTINGS))
    simulation.set_custom_orchestrator(GeneticOrchestrator)
    row = simulation.launch()[0]
    print(f"\ntasks={row[COLUMNS[7]]:>5} ok={row[COLUMNS[8]]:>5} avg_delay={row[COLUMNS[4]]:<8} "
          f"cloud={row[COLUMNS[15]]:>4} edge={row[COLUMNS[17]]:>4} mist={row[COLUMNS[19]]:>4} "
          f"failed(dependency)={row[COLUMNS[14]]:>4} energy={row[COLUMNS[32]]}")


if __name__ == "__main__":
    main()
