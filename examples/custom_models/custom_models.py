"""Four custom models that change the scenario: fleet, workload, backbone, audit.

    python examples/custom_models/custom_models.py

Port of the Java `Example23`. This example registers no orchestrator and adds no
placement algorithm. It replaces the four models that every other example leaves
at their default, so the scenario is assembled almost entirely from custom code:

``TypeGuaranteeGenerator``      keeps a rare device type in the fleet
``BurstTaskGenerator``          aligns the requests of the whole fleet on the minute
``FullMeshTopologyCreator``     completes the declared ring of edge data centers
``AuditSimulationManager``      records how each task ended, and why

The four classes take the order in which the framework builds a scenario: the
nodes come first, then the links, then the workload, and the manager runs the
events. Each one extends its default, overrides a single method and delegates
everything else to ``super``, exactly like the Java classes.

``examples/extension_points`` registers the same hooks and changes nothing, which
is the point of that tour. Here the opposite is shown, so the scenario is
launched twice on the same seed, once with the stock models and once with these
four, and the two result rows are printed side by side.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from pureedgesim import (COLUMNS, ComputingNodesGenerator, DefaultTaskGenerator, DefaultTopologyCreator, LinkType,
                         Simulation, SimulationManager, TaskStatus, load_parameters, load_settings)

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/custom_models/output"

# What the audit line knows about the last custom run, kept for the test suite and
# for the printed comparison, like the counters of the extension points example.
AUDIT: dict[str, object] = {}


class TypeGuaranteeGenerator(ComputingNodesGenerator):
    """A fleet that never drops a declared device type.

    The default allocation apportions the fleet with the largest remainder method.
    It is fair to the declared shares, but a share smaller than one device rounds to
    zero: on the settings of this example, the 2 percent wearable type of a 20
    device fleet earns 0.4 of a device and disappears. This generator keeps the
    default split, then reserves one device for every positive share that received
    none, taking it from the type holding the most devices.
    """

    #: The split the last run produced, so the caller can print it.
    last_allocation: tuple[int, ...] = ()

    def _allocate_devices(self, percentages, device_count: int):
        allocation = super()._allocate_devices(percentages, device_count)
        for index, percentage in enumerate(percentages):
            if percentage <= 0 or allocation[index] > 0:
                continue
            donor = self._largest_allocation(allocation)
            if donor < 0:
                break
            allocation[donor] -= 1
            allocation[index] = 1
            print(f"{type(self).__name__} - Device type {index + 1} declares {percentage} % of the "
                  f"fleet, a share that rounds to zero: one device reserved from type {donor + 1}")
        TypeGuaranteeGenerator.last_allocation = tuple(allocation)
        return allocation

    @staticmethod
    def _largest_allocation(allocation) -> int:
        """The type holding the most devices, provided it has more than one to spare."""
        donor = -1
        for index, count in enumerate(allocation):
            if count > 1 and (donor < 0 or count > allocation[donor]):
                donor = index
        return donor


class BurstTaskGenerator(DefaultTaskGenerator):
    """A workload whose bursts start at the same instant on every device.

    The default generator drops each minute's burst inside the first fifteen
    seconds of that minute, at a random offset per device, so the bursts of two
    devices rarely overlap. This generator keeps the same burst of ``rate`` tasks,
    evenly spaced, but anchored on the minute mark: it simply does not draw the
    offset. The scenario then behaves like a fleet that reports on the minute (meter
    readings, clock synchronization, scheduled uploads), where every device contends
    for the network and the servers at the same moment.

    Applications declaring an arrival pattern are not generated per minute, so they
    keep the default behaviour.
    """

    def _generate_for_device(self, device, application, tasks, identifier: int) -> int:
        if application.arrival_distribution is not None:
            return super()._generate_for_device(device, application, tasks, identifier)
        for minute in range(int(self.parameters.simulation_duration / 60)):
            rate = max(0, int(application.rate.sample_int()))
            if rate == 0:
                continue
            time = minute * 60
            spacing = 60 // rate
            for _ in range(rate):
                time += spacing
                generated, identifier = self._create_tasks(device, application, time, identifier)
                tasks.extend(generated)
        return identifier


class FullMeshTopologyCreator(DefaultTopologyCreator):
    """A backbone completed into a full mesh, one hop between any two data centers.

    The topology file declares a ring: each edge data center is linked to its two
    neighbours, so a task served by a remote data center crosses two hops of MAN
    latency to reach the opposite corner. This creator keeps those links and adds a
    MAN link in both directions between every pair that is not already directly
    connected, which also gives the backbone a redundant route. The graph drops its
    cached shortest paths as soon as a link is added, so no recompute step follows.
    """

    def create(self) -> None:
        super().create()
        nodes = self.generator.edge_data_centers
        added = self._connect_all_pairs(nodes)
        print(f"{type(self).__name__} - Added {added} directed MAN links to complete the full mesh "
              f"of {len(nodes)} edge data centers")

    def _connect_all_pairs(self, nodes) -> int:
        """Links every pair of data centers in both directions, skipping existing edges."""
        linked = {(link.source.id, link.destination.id) for link in self.graph.links
                  if link.type == LinkType.MAN}
        added = 0
        for index, origin in enumerate(nodes):
            for other in nodes[index + 1:]:
                for source, destination in ((origin, other), (other, origin)):
                    if (source.id, destination.id) in linked:
                        continue
                    linked.add((source.id, destination.id))
                    self._man(source, destination)
                    added += 1
        return added


class AuditSimulationManager(SimulationManager):
    """A manager that audits the outcome of every task, not only the success rate.

    The default manager reports aggregates. This one keeps them and adds a per task
    ledger: how many tasks returned their results, how many failed and for what
    reason, how many were never sent because their device was already dead, how many
    transfers crossed the MAN backbone, and how crowded the busiest arrival instant
    became. The ledger is printed when the engine notifies its end listeners, so it
    appears after the standard report.
    """

    def __init__(self, *args, **kwargs) -> None:
        # The runner builds the manager with the arguments of SimulationManager, so
        # the subclass only forwards them and adds its own counters.
        super().__init__(*args, **kwargs)
        self.audited: set[int] = set()
        self.audit_succeeded = 0
        self.audit_not_generated = 0
        self.audit_failures: Counter = Counter()

    def task_failed(self, task, phase: int) -> bool:
        failed = super().task_failed(task, phase)
        if failed:
            self._record_failure(task, phase)
        return failed

    def _results_returned(self, task) -> None:
        super()._results_returned(task)
        if task.status == TaskStatus.SUCCESS and task.id not in self.audited:
            self.audited.add(task.id)
            self.audit_succeeded += 1

    def _record_failure(self, task, phase: int) -> None:
        """Books one failed task once, because the manager checks a task at every phase."""
        if task.id in self.audited:
            return
        self.audited.add(task.id)
        if phase == 0:
            self.audit_not_generated += 1
            return
        self.audit_failures[task.status.name] += 1

    def _man_transfers(self) -> int:
        """Transfers whose route contained at least one MAN link."""
        return sum(1 for task in self.tasks for hop in task.network_hops
                   if any(link.type == LinkType.MAN for link in hop.route))

    def on_simulation_end(self) -> None:
        failed = sum(self.audit_failures.values())
        usage = self.network.network_usage
        crossed = self._man_transfers()
        peak_time, peak = Counter(task.time for task in self.tasks).most_common(1)[0]
        breakdown = ", ".join(f"{reason} {count}" for reason, count in self.audit_failures.items())
        AUDIT.clear()
        AUDIT.update({
            "generated": self.metrics.generated_tasks,
            "succeeded": self.audit_succeeded,
            "failed": failed,
            "not_generated": self.audit_not_generated,
            "by_reason": dict(self.audit_failures),
            "man_transfers": crossed,
            "man_usage": usage[LinkType.MAN],
            "busiest_instant": (peak_time, peak),
        })
        print(f"{type(self).__name__} - audit: {self.audit_succeeded} succeeded, {failed} failed, "
              f"{self.audit_not_generated} not sent ({breakdown or 'no failures'})")
        print(f"{type(self).__name__} - link usage: WAN {usage[LinkType.WAN]:.2f} s, "
              f"MAN {usage[LinkType.MAN]:.2f} s, LAN {usage[LinkType.LAN]:.2f} s, "
              f"{crossed} transfers crossed a MAN link")
        print(f"{type(self).__name__} - busiest instant: {peak} tasks arrive together at "
              f"t={peak_time:.0f} s over {self.metrics.generated_tasks} generated tasks")


def simulate(custom: bool, devices: int, duration: float, seed: int, output: str | Path) -> dict:
    """Runs the scenario once, with the stock models or with the four custom ones."""
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    parameters.simulation_duration = duration
    parameters.min_number_of_devices = parameters.max_number_of_devices = devices
    parameters.devices_increment = 1
    parameters.random_seed = seed
    parameters.save_log_file = False
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    if not custom:
        return simulation.launch()[0]
    return (simulation.set_custom_computing_nodes_generator(TypeGuaranteeGenerator)
            .set_custom_task_generator(BurstTaskGenerator)
            .set_custom_topology_creator(FullMeshTopologyCreator)
            .set_custom_simulation_manager(AuditSimulationManager)
            .launch()[0])


# The columns the comparison prints, by name so a reader can find them in the CSV.
METRICS = ("Number of generated tasks", "Tasks successfully executed", "Tasks failed (delay)",
           "Task not executed (No resources available or long waiting time)",
           "Average execution delay (s)", "Average waiting time (s)", "Network usage (s)",
           "Wan usage (s)", "MAN energy consumption (Wh)", "Total network traffic (MBytes)",
           "Average CPU usage (%)", "Energy consumption of computing nodes (Wh)", "Dead devices count")


def compare(stock: dict, custom: dict) -> None:
    print(f"\n{'metric':<58} {'stock models':>16} {'custom models':>16}")
    for metric in METRICS:
        print(f"{metric:<58} {str(stock[metric]):>16} {str(custom[metric]):>16}")


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> tuple[dict, dict]:
    """Launches the scenario twice and returns the stock row next to the custom one."""
    settings = load_parameters(SETTINGS / "simulation_parameters.properties")
    devices = devices if devices is not None else settings.min_number_of_devices
    duration = duration if duration is not None else settings.simulation_duration
    seed = seed if seed is not None else settings.random_seed
    TypeGuaranteeGenerator.last_allocation = ()
    AUDIT.clear()

    # The settings clear the output folder before a launch, so the two runs are kept
    # apart: the custom row owns the timestamped folder under output/, the stock row
    # goes to output/stock/. The custom run comes first because clearing output/
    # would otherwise delete the stock results.
    print("custom models: the four classes registered on the Simulation")
    custom = simulate(True, devices, duration, seed, output)
    print(f"\nstock models: the same scenario, {devices} devices, {duration:.0f} s, seed {seed}")
    stock = simulate(False, devices, duration, seed, Path(output) / "stock")

    # The default allocation, computed the way the framework computes it, is printed
    # next to the one the custom generator settled on, so the fleet change is visible.
    shares = [spec.percentage for spec in load_settings(SETTINGS).devices]
    stock_split = "/".join(str(count) for count in ComputingNodesGenerator._allocate_devices(shares, devices))
    custom_split = "/".join(str(count) for count in TypeGuaranteeGenerator.last_allocation)
    print(f"\nfleet split, one slot per declared device type ({', '.join(str(share) for share in shares)} %)")
    print(f"  stock models    {stock_split}")
    print(f"  custom models   {custom_split}")
    compare(stock, custom)
    print(f"\n{'stock models':<20} tasks={stock[COLUMNS[7]]:>5} ok={stock[COLUMNS[8]]:>5} "
          f"avg_delay={stock[COLUMNS[4]]:<8} energy={stock[COLUMNS[32]]:<8} cpu={stock[COLUMNS[28]]}%")
    print(f"{'four custom models':<20} tasks={custom[COLUMNS[7]]:>5} ok={custom[COLUMNS[8]]:>5} "
          f"avg_delay={custom[COLUMNS[4]]:<8} energy={custom[COLUMNS[32]]:<8} cpu={custom[COLUMNS[28]]}%")
    return stock, custom


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and the root of the
    # output folder, so the four models can be tried on a smaller fleet without
    # editing the settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
