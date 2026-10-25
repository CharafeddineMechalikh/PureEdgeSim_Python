"""A custom placement policy: give every task to the node closest to its device.

    python examples/custom_orchestrator.py

The TRADE_OFF algorithm of PureEdgeSim balances the load and the CPU speed of each
candidate. This example replaces it by the nearest node, so a mist device wins
whenever one is within radio range and the cloud is only used as a last resort.
"""
from __future__ import annotations

from pathlib import Path

from pureedgesim import (COLUMNS, DefaultOrchestrator, NodeType, Orchestrator, Simulation,
                       load_parameters, load_settings)

SETTINGS = Path(__file__).resolve().parent / "default_settings"
CLOUD_IS_FAR = 1e9


class NearestNodeOrchestrator(Orchestrator):
    """The closest eligible node, the least loaded one breaking the tie."""

    def find_computing_node(self, tasks, algorithm, application_id):
        task = tasks[0]
        device = task.source_device
        eligible = [(index, node) for index, node in enumerate(self.candidates)
                    if self.offloading_is_possible(node, task)]
        if not eligible:
            return -1
        index, _ = min(eligible, key=lambda pair: (CLOUD_IS_FAR if pair[1].type == NodeType.CLOUD
                                                   else device.distance_to(pair[1]),
                                                   self.history[pair[0]]))
        self.history[index] += 1
        return index


def run(label: str, orchestrator: type[Orchestrator] = DefaultOrchestrator) -> dict:
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    parameters.simulation_duration = 300.0
    parameters.min_number_of_devices = parameters.max_number_of_devices = 20
    parameters.devices_increment = 1
    parameters.orchestration_architectures = ["ALL"]
    parameters.orchestration_algorithms = ["TRADE_OFF"]
    parameters.random_seed = 7
    parameters.save_log_file = False
    simulation = Simulation(SETTINGS, "output/examples", parameters, load_settings(SETTINGS))
    simulation.set_custom_orchestrator(orchestrator)
    row = simulation.launch()[0]
    print(f"{label:<24} tasks={row[COLUMNS[7]]:>5} ok={row[COLUMNS[8]]:>5} "
          f"avg_delay={row[COLUMNS[4]]:<8} cloud={row[COLUMNS[14]]:>4} edge={row[COLUMNS[16]]:>4} "
          f"mist={row[COLUMNS[18]]:>4} energy={row[COLUMNS[31]]}")
    return row


if __name__ == "__main__":
    print("orchestration strategy, same seed and same workload:")
    run("TRADE_OFF (default)")
    run("nearest node", NearestNodeOrchestrator)
