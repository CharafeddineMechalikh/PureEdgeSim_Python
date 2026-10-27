"""Cooperative edge data centers with an orchestrator on each of them.

    PYTHONPATH=src python examples/edge_cooperation/edge_cooperation.py

Port of the Java `Example3`. Four edge data centers sit at the corners of a 2000
by 2000 meters map and are linked in a ring (the MAN, described by the
`network_links` of `settings/edge_datacenters.xml`). With `deploy_orchestrator=EDGE`
every device sends its request to its nearest edge data center, and that data
center decides where the task really runs: locally, on another edge data center
reached through the ring, or in the cloud.

The Java example relies on the default TRADE_OFF orchestrator, which in PureEdgeSim
may forward a task to any edge data center the orchestrator can reach. The Python
core's base policy restricts an edge data center to the one already serving the
device (`Orchestrator.offloading_is_possible`), so no task would ever leave its
own edge server and the ring would stay idle. This example therefore installs a
cooperative orchestrator that relaxes that restriction the way the Java default
does: a task may be forwarded to any edge data center still within
`edge_datacenters_coverage`, scored by the same trade-off rule. The forwarded
count and the MAN traffic it produces are printed at the end of the run, proving
the ring is used.

Run it twice to see the cooperation clearly: leave `deploy_orchestrator=EDGE` for
this run, and set `enable_orchestrators=false` in the settings to make every
device decide for itself - then nothing is forwarded and the MAN stays empty.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pureedgesim import (COLUMNS, ComputingNode, LinkType, NodeType, Orchestrator, SimEntity, Simulation,
                         load_parameters, load_settings)

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/edge_cooperation/output"


class CooperativeEdgeOrchestrator(SimEntity, Orchestrator):
    """Spreads tasks over the edge data centers reachable through the MAN ring."""

    def __init__(self, manager) -> None:
        SimEntity.__init__(self, manager.engine)
        Orchestrator.__init__(self, manager)
        self.forwarded = 0
        self.local = 0
        self.cloud = 0
        self.orchestrators_used: set[int] = set()

    def orchestrate(self, task, application_id: int = 0):
        destination = super().orchestrate(task, application_id)
        # The Python manager caches one placement per device, so a cooperative
        # decision has to be re-taken for every task instead of reusing the first.
        task.source_device.application_placed = False
        return destination

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        task = tasks[0]
        orchestrator = task.get_orchestrator()
        if orchestrator.type == NodeType.EDGE_DATACENTER:
            self.orchestrators_used.add(orchestrator.id)
        eligible = self.eligible_for(task)
        if not eligible:
            return -1
        index = self.trade_off(eligible, task)
        if index >= 0:
            self.history[index] += 1
            chosen = self.candidates[index]
            if chosen.type == NodeType.CLOUD:
                self.cloud += 1
            elif chosen is task.source_device.serving_edge_data_center:
                self.local += 1
            else:
                self.forwarded += 1
        return index

    def eligible_for(self, task) -> list[tuple[int, ComputingNode]]:
        """The destinations the ring opens to this task.

        The base rule restricts an edge data center to the one already serving the
        device, so here any data center the device still reaches through the MAN is
        offered as well - that relaxation is the whole point of the example.
        """
        device = task.source_device
        coverage = self.manager.parameters.edge_data_centers_range
        eligible: list[tuple[int, ComputingNode]] = []
        for index, node in enumerate(self.candidates):
            if node.type == NodeType.EDGE_DATACENTER:
                # Reachable through the ring: still inside the coverage area.
                if device.distance_to(node) <= coverage:
                    eligible.append((index, node))
            elif self.offloading_is_possible(node, task):
                eligible.append((index, node))
        return eligible

    def on_simulation_end(self) -> None:
        man = self.manager.network.network_usage[LinkType.MAN]
        print(f"{type(self).__name__} - served by {len(self.orchestrators_used)} edge orchestrators: "
              f"{self.local} local, {self.forwarded} forwarded over the MAN ring, {self.cloud} to cloud, "
              f"MAN usage {man:.3f} s")


def run(devices: int | None = None, duration: float | None = None, seed: int | None = None,
        output: str | Path = OUTPUT) -> dict:
    """Runs the sweep of the settings folder and prints one line per scenario."""
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    if devices is not None:
        parameters.min_number_of_devices = parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration is not None:
        parameters.simulation_duration = duration
    if seed is not None:
        parameters.random_seed = seed
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    simulation.set_custom_orchestrator(CooperativeEdgeOrchestrator)
    rows = simulation.launch()
    if not rows:
        raise ValueError(f"{SETTINGS}: the settings declare no scenario, nothing to run")
    for row in rows:
        print(f"{row[COLUMNS[0]]:<16} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} "
              f"ok={row[COLUMNS[8]]:>6} avg_delay={row[COLUMNS[4]]:<8} "
              f"cloud={row[COLUMNS[15]]:>5} edge={row[COLUMNS[17]]:>5} mist={row[COLUMNS[19]]:>5} "
              f"failed(delay)={row[COLUMNS[10]]:>5} energy={row[COLUMNS[32]]}")
    return rows[-1]


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the scenario; the three arguments shrink it for the test suite."""
    return run(devices, duration, seed, output)


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the cooperation over the ring can be watched on a small fleet
    # without editing the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
