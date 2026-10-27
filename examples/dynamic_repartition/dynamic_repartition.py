"""Repartitioning a service graph while the simulation runs.

    PYTHONPATH=src python examples/dynamic_repartition/dynamic_repartition.py

Port of the Java `Example24`. The scenario runs a seven-stage video analytics
pipeline (capture -> preprocess -> detect -> classify -> track -> aggregate ->
notify, declared as `<subtask>` elements in `settings/applications.xml`) on 200
devices served by four edge data centers and the cloud. The whole architecture is
`ALL`, so every stage may run at the mist, edge or cloud tier.

`DynamicRepartitionOrchestrator` assigns a *tier* to every subtask of a graph and
refreshes that plan every `REPLAN_INTERVAL` seconds from the state of the nodes at
that moment - their pending queues, current CPU use and reachability - instead of
deciding once at the start. It replans immediately when a planned tier loses every
available node, and counts the subtasks that changed tier on each refresh: that
migration count, together with the before/after tier of every moved stage, is
printed while the run goes on, proving the graph is repartitioned live.

Run it like the Java example to compare the two modes:

    PYTHONPATH=src python examples/dynamic_repartition/dynamic_repartition.py
    PYTHONPATH=src python examples/dynamic_repartition/dynamic_repartition.py --frozen

The first refreshes the plan periodically, the second computes it once on the first
request and never updates it: the frozen run is the static baseline, and its
migrations are zero.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pureedgesim import (COLUMNS, DefaultOrchestrator, NodeType, Orchestrator, SimEntity, Simulation,
                         load_parameters, load_settings)

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/dynamic_repartition/output"

REPLAN_INTERVAL = 30.0
# The tier weight mirrors the trade-off policy: cloud pays for distance, mist for
# its weaker capacity, edge is the cheapest tier per unit of work.
TIER_WEIGHT = {NodeType.CLOUD: 1.8, NodeType.EDGE_DEVICE: 1.3, NodeType.EDGE_DATACENTER: 1.2}
TIER_NAME = {NodeType.CLOUD: "Cloud", NodeType.EDGE_DATACENTER: "Edge", NodeType.EDGE_DEVICE: "Mist"}


class DynamicRepartitionOrchestrator(DefaultOrchestrator, SimEntity):
    """Assigns a tier per subtask and recomputes that plan during the run."""

    def __init__(self, manager, frozen_plan: bool = False) -> None:
        SimEntity.__init__(self, manager.engine)
        Orchestrator.__init__(self, manager)
        self.frozen_plan = frozen_plan
        self.plans: dict[int, dict[str, NodeType]] = {}
        self.last_plan_time: dict[int, float] = {}
        self.migrations = 0
        self.replans = 0

    def orchestrate(self, task, application_id: int = 0):
        destination = super().orchestrate(task, application_id)
        # A plan that changes over time cannot survive the manager's per-device
        # placement cache, so it is cleared after every decision.
        task.source_device.application_placed = False
        return destination

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        task = tasks[0]
        if task.subtask_name is None:
            return super().find_computing_node(tasks, algorithm, application_id)
        plan = self.plans.get(application_id)
        if plan is None or (not self.frozen_plan and self._should_replan(application_id, plan)):
            next_plan = self._compute_plan(task)
            if not next_plan:
                return super().find_computing_node(tasks, algorithm, application_id)
            moved = self._count_migrations(plan, next_plan) if plan else 0
            if plan:
                self.migrations += moved
                self._report_migration(application_id, plan, next_plan, moved)
            self.plans[application_id] = next_plan
            self.last_plan_time[application_id] = self.clock
            self.replans += 1
            plan = next_plan
        tier = plan.get(task.subtask_name)
        index = -1 if tier is None else self._node_of_tier(task, tier)
        return index if index >= 0 else super().find_computing_node(tasks, algorithm, application_id)

    def _should_replan(self, application: int, plan: dict[str, NodeType]) -> bool:
        if self.clock - self.last_plan_time.get(application, 0.0) >= REPLAN_INTERVAL:
            return True
        return any(not self._has_available_node(tier) for tier in set(plan.values()))

    def _has_available_node(self, tier: NodeType) -> bool:
        return any(node.type is tier and not node.is_dead() and not node.is_sensor
                   for node in self.candidates)

    def _compute_plan(self, origin) -> dict[str, NodeType]:
        application = origin.application_id
        if application < 0 or application >= len(self.manager.applications):
            return {}
        profile = self.manager.applications[application]
        if not profile.has_subtasks:
            return {}
        tiers = [tier for tier in self.architecture_layers if self._has_available_node(tier)]
        plan: dict[str, NodeType] = {}
        assigned: dict[NodeType, int] = {}
        for subtask in profile.subtasks:
            best, best_score = None, float("inf")
            for tier in tiers:
                score = self._tier_score(origin, subtask, tier, assigned.get(tier, 0))
                if score < best_score:
                    best, best_score = tier, score
            if best is not None:
                plan[subtask.name] = best
                assigned[best] = assigned.get(best, 0) + 1
        return plan

    def _tier_score(self, origin, subtask, tier: NodeType, virtual_load: int) -> float:
        best = float("inf")
        mean_length = subtask.task_length.mean()
        for node in self.candidates:
            if node.type is not tier or not self.offloading_is_possible(node, origin):
                continue
            load = len(node.task_queue) + virtual_load + 1
            cpu = 1 + node.get_cpu_usage_current() / 100.0
            cost = load * TIER_WEIGHT[tier] * cpu * mean_length / max(1.0, node.mips_per_core)
            best = min(best, cost)
        return best

    def _node_of_tier(self, task, tier: NodeType) -> int:
        selected, least_loaded = -1, float("inf")
        for index, node in enumerate(self.candidates):
            if node.type is not tier or not self.offloading_is_possible(node, task):
                continue
            if not node.is_ram_available(task) or not node.is_storage_available(task):
                continue
            load = len(node.task_queue) + 0.01 * node.get_cpu_usage_current() + 0.5 * self.history[index]
            if load < least_loaded:
                least_loaded, selected = load, index
        if selected != -1:
            self.history[selected] += 1
        return selected

    @staticmethod
    def _count_migrations(previous: dict[str, NodeType], next_plan: dict[str, NodeType]) -> int:
        return sum(1 for name, tier in next_plan.items()
                   if name in previous and previous[name] is not tier)

    def _report_migration(self, application: int, previous, next_plan, moved: int) -> None:
        if not moved:
            return
        moves = [f"{name}: {TIER_NAME[previous[name]]} -> {TIER_NAME[next_plan[name]]}"
                 for name in next_plan
                 if name in previous and previous[name] is not next_plan[name]]
        print(f"{type(self).__name__} - {self.clock:.1f} s: application {application} repartitioned, "
              f"{moved} subtask(s) moved, {self.migrations} so far")
        for move in moves:
            print(f"    {move}")

    def on_simulation_end(self) -> None:
        mode = "frozen plan" if self.frozen_plan else "dynamic plan"
        print(f"{type(self).__name__} - {mode}: {self.replans} replans, {self.migrations} subtasks moved")


def run(label: str | None = None, devices: int | None = None, duration: float | None = None,
        frozen: bool = False, seed: int | None = None, output: str | Path = OUTPUT) -> dict:
    """Runs the sweep of the settings folder and prints one line per scenario."""

    class _Orchestrator(DynamicRepartitionOrchestrator):
        def __init__(self, manager) -> None:
            super().__init__(manager, frozen_plan=frozen)

    _Orchestrator.__name__ = "DynamicRepartitionOrchestrator"

    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    if devices is not None:
        parameters.min_number_of_devices = parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration is not None:
        parameters.simulation_duration = duration
    if seed is not None:
        parameters.random_seed = seed
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    simulation.set_custom_orchestrator(_Orchestrator)
    rows = simulation.launch()
    if not rows:
        raise ValueError(f"{SETTINGS}: the settings declare no scenario, nothing to run")
    for row in rows:
        tag = label or ("frozen" if frozen else "dynamic")
        print(f"{tag:<8} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} ok={row[COLUMNS[8]]:>6} "
              f"requests_ok={row[COLUMNS[54]]:>5}/{row[COLUMNS[53]]:<5} "
              f"avg_makespan={row[COLUMNS[55]]:<8} cloud={row[COLUMNS[15]]:>5} "
              f"edge={row[COLUMNS[17]]:>5} mist={row[COLUMNS[19]]:>5} "
              f"failed(delay)={row[COLUMNS[10]]:>5} energy={row[COLUMNS[32]]}")
    return rows[-1]


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT, frozen: bool = False) -> dict:
    """Runs the scenario; the three arguments shrink it for the test suite."""
    return run(devices=devices, duration=duration, seed=seed, output=output, frozen=frozen)


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the live repartitioning can be watched on a small map without
    # editing the settings. ``--frozen`` keeps the static baseline.
    positional = [argument for argument in sys.argv[1:] if not argument.startswith("--")]
    main(devices=int(positional[0]) if positional else None,
         output=positional[1] if len(positional) > 1 else OUTPUT,
         frozen="--frozen" in sys.argv)
