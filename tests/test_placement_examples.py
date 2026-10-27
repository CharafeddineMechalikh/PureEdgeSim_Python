"""What the eight placement examples really do, checked on their own settings.

Each example is covered twice. As a script first: its ``main`` entry point is called
on its own settings folder, shrunk to a handful of devices and two simulated
minutes, and the row it returns has to describe the run it claims - the algorithm
and the device count it was given, work generated, successes that really succeeded,
a per-tier breakdown and an energy bill - with a CSV written under the output
folder. As a mechanism second: the orchestrator is built on a real tiny scenario
and its own rule is probed directly, so a policy that quietly stopped learning,
stopped exploring or stopped using the ring still fails here.

The eight examples are the Q-learning family (``q_learning``,
``softmax_orchestrator``, ``mist_only_q_learning``,
``edge_orchestrated_q_learning``), the two orchestrator-entity examples
(``dynamic_repartition``, ``edge_cooperation``) and the two extension-point
examples (``extension_points``, ``custom_computing_node``).
"""
from __future__ import annotations

import csv
import math
import runpy
import sys

import pytest

from examples.custom_computing_node import custom_computing_node as custom_node
from examples.dynamic_repartition import dynamic_repartition as repartition
from examples.edge_cooperation import edge_cooperation as cooperation
from examples.edge_orchestrated_q_learning import edge_orchestrated_q_learning as edge_orchestrated
from examples.extension_points import extension_points as points
from examples.mist_only_q_learning import mist_only_q_learning as mist_only
from examples.q_learning import q_learning as tabular
from examples.softmax_orchestrator import softmax_orchestrator as softmax
from pureedgesim import (COLUMNS, DefaultOrchestrator, Engine, Event, EventType, NodeStatus,
                         NodeType, Randomness, Scenario, SimulationManager, Task, TaskStatus,
                         load_parameters, load_settings)

# Two simulated minutes is the shortest duration that still generates a burst of
# tasks for every one of these settings folders, and the seed fixes both the
# workload and the mobility, so a row can be compared with the next run's.
SHORT_DURATION = 120.0
SEED = 11
Agent = tabular.QLearningOrchestrator

#: id, module, entry point, architecture, algorithm, devices - the scenarios shrunk.
SCRIPTS = (
    ("q_learning", tabular, tabular.main, "ALL", "Q_LEARNING", 6),
    ("softmax", softmax, softmax.main, "ALL", "SOFTMAX", 6),
    ("mist_only", mist_only, mist_only.main, "MIST_ONLY", "Q_LEARNING", 10),
    ("edge_orchestrated", edge_orchestrated, edge_orchestrated.main, "ALL", "Q_LEARNING", 10),
    ("dynamic_repartition", repartition, repartition.main, "ALL", "TRADE_OFF", 6),
    ("edge_cooperation", cooperation, cooperation.main, "EDGE_AND_CLOUD", "TRADE_OFF", 10),
    # The tour returns the stock row and the toured one; the toured one is the
    # interesting row, and the first test below compares the two.
    ("extension_points", points, lambda **kw: points.main(**kw)[1], "ALL", "TRADE_OFF", 6),
    ("custom_computing_node", custom_node, custom_node.main, "ALL", "TRADE_OFF", 6),
)
SCRIPT_IDS = [case[0] for case in SCRIPTS]
SCRIPT_CASES = {case[0]: case for case in SCRIPTS}

ORCHESTRATORS = {
    tabular: Agent,
    softmax: softmax.SoftmaxOrchestrator,
    mist_only: Agent,
    edge_orchestrated: Agent,
    repartition: repartition.DynamicRepartitionOrchestrator,
    cooperation: cooperation.CooperativeEdgeOrchestrator,
}


class _FrozenPlan(repartition.DynamicRepartitionOrchestrator):
    """The static baseline of the repartition example, reached the same way the script does."""

    def __init__(self, manager) -> None:
        super().__init__(manager, frozen_plan=True)


class Draw:
    """A scripted source of randomness, so one branch of an exploration is forced."""

    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value

    def randrange(self, stop: int) -> int:
        return stop - 1


def make_task(device, kind="Non Real-time", length=1000.0, max_latency=1e9, task_id=1):
    """A task shaped like the generated ones, small enough to be placed anywhere."""
    return Task(id=task_id, type=kind, application_id=0, length=length, container_size=8e6,
                request_size=8e3, result_size=8e3, max_latency=max_latency, time=0.0,
                source_device=device, registry=device)


def build(module, devices=6, duration=SHORT_DURATION, seed=SEED, architecture=None,
          algorithm=None, frozen=False, computing_node=None):
    """A real manager on the example's own settings, built but not run."""
    settings = module.SETTINGS
    parameters = load_parameters(settings / "simulation_parameters.properties")
    parameters.simulation_duration = duration
    parameters.min_number_of_devices = parameters.max_number_of_devices = devices
    parameters.devices_increment = 1
    parameters.random_seed = seed
    parameters.save_log_file = False
    arch = architecture or parameters.orchestration_architectures[0]
    algo = algorithm or parameters.orchestration_algorithms[0]
    parameters.orchestration_architectures = [arch]
    parameters.orchestration_algorithms = [algo]
    Randomness.set_seed(seed)
    Randomness.begin_scenario(0)
    engine = Engine(duration)
    manager = SimulationManager(engine, parameters, load_settings(settings), Scenario(arch, algo, devices),
                                custom_orchestrator=(_FrozenPlan if frozen else ORCHESTRATORS.get(module)),
                                custom_computing_node=computing_node)
    manager.start_simulation()
    return engine, manager


def served_device(manager):
    """A compute-capable device wired to an edge data center, so every tier is eligible."""
    manager.parameters.edge_devices_range = manager.parameters.simulation_map_length
    return next(node for node in manager.edge_devices
                if not node.is_sensor and node.serving_edge_data_center is not None)


def place(orchestrator, algorithm, task) -> int:
    """Asks the orchestrator where this task should run, exactly like the manager does."""
    return orchestrator.find_computing_node([task], algorithm, task.application_id)


def succeed(task, delay) -> None:
    """Fills in what the manager would have measured: network time plus execution time."""
    task.status = TaskStatus.SUCCESS
    task.arrival_time = 0.0
    task.execution_start_time = 0.0
    task.execution_finish_time = delay
    task.total_network_time = delay


@pytest.fixture(scope="module")
def script_rows(tmp_path_factory):
    """One shrunk run per example: its result row and the folder it wrote."""
    base = tmp_path_factory.mktemp("placement_runs")
    captured = {}
    for name, _, entry, _, _, devices in SCRIPTS:
        folder = base / name
        row = entry(devices=devices, duration=SHORT_DURATION, seed=SEED, output=folder)
        captured[name] = (row, folder)
    return captured


@pytest.fixture(scope="module")
def tour(tmp_path_factory):
    """The two rows of the extension points example, and the counters its tour filled."""
    folder = tmp_path_factory.mktemp("extension_points") / "tour"
    stock, toured = points.main(devices=6, duration=SHORT_DURATION, seed=SEED, output=folder)
    return stock, toured, dict(points.USAGE), dict(points.CLASSES)


# ---------------------------------------------------------------- the eight scripts

@pytest.mark.parametrize("name", SCRIPT_IDS)
def test_the_script_reports_the_scenario_it_was_asked_to_run(name, script_rows):
    _, _, _, architecture, algorithm, devices = SCRIPT_CASES[name]
    assert script_rows[name][0][COLUMNS[0]] == architecture
    assert script_rows[name][0][COLUMNS[1]] == algorithm
    assert script_rows[name][0][COLUMNS[2]] == devices


@pytest.mark.parametrize("name", SCRIPT_IDS)
def test_the_script_generates_work_and_counts_only_tasks_that_succeeded(name, script_rows):
    row = script_rows[name][0]
    assert row[COLUMNS[7]] > 0
    assert 0 < row[COLUMNS[8]] <= row[COLUMNS[7]]


@pytest.mark.parametrize("name", SCRIPT_IDS)
def test_the_script_tier_counters_agree_with_its_own_row(name, script_rows):
    row = script_rows[name][0]
    for total, success in ((COLUMNS[15], COLUMNS[16]), (COLUMNS[17], COLUMNS[18]),
                           (COLUMNS[19], COLUMNS[20])):
        assert 0 <= row[success] <= row[total]
    assert row[COLUMNS[16]] + row[COLUMNS[18]] + row[COLUMNS[20]] == row[COLUMNS[8]]
    assert row[COLUMNS[15]] + row[COLUMNS[17]] + row[COLUMNS[19]] <= row[COLUMNS[7]]


@pytest.mark.parametrize("name", SCRIPT_IDS)
def test_the_script_bills_a_non_negative_energy(name, script_rows):
    assert script_rows[name][0][COLUMNS[32]] >= 0


@pytest.mark.parametrize("name", SCRIPT_IDS)
def test_the_script_wrote_its_row_to_a_csv_file(name, script_rows):
    row, folder = script_rows[name]
    written = [record for path in folder.rglob("Sequential_simulation.csv")
               for record in csv.DictReader(path.open(encoding="utf-8"))]
    assert written
    assert any(record[COLUMNS[1]] == row[COLUMNS[1]] and int(record[COLUMNS[7]]) == row[COLUMNS[7]]
               for record in written)


@pytest.mark.parametrize("name", SCRIPT_IDS)
def test_the_script_runs_from_its_command_line_entry_point(name, tmp_path, monkeypatch):
    module = SCRIPT_CASES[name][1]
    script = module.SETTINGS.parent / f"{module.__name__.split('.')[-1]}.py"
    folder = tmp_path / name
    # Two devices and the duration of the settings folder: the command line takes
    # the device count and the output folder, exactly as the README says.
    monkeypatch.setattr(sys, "argv", [str(script), "2", str(folder)])
    runpy.run_path(str(script), run_name="__main__")
    written = [record for path in folder.rglob("Sequential_simulation.csv")
               for record in csv.DictReader(path.open(encoding="utf-8"))]
    assert written
    for record in written:
        assert int(record[COLUMNS[2]]) == 2
        assert int(record[COLUMNS[7]]) > 0
        assert 0 < int(record[COLUMNS[8]]) <= int(record[COLUMNS[7]])


# ------------------------------------------------------- what each run must show

def test_the_mist_only_run_keeps_every_task_in_the_mist_layer(script_rows):
    row = script_rows["mist_only"][0]
    assert row[COLUMNS[15]] == 0
    assert row[COLUMNS[17]] == 0
    assert row[COLUMNS[19]] == row[COLUMNS[7]]


def test_the_q_learning_run_and_the_trade_off_run_share_the_same_workload(tmp_path):
    """The learned policy is compared with the hand-written one on the same seed.

    Only the two things the run really shows are asserted: the workload is the same,
    and the tiers are used differently. Nothing here claims a better delay or a
    smaller energy bill - at this size the learned policy is neither.
    """
    plain = tabular.run(tabular.SETTINGS, tmp_path / "trade_off", DefaultOrchestrator, "TRADE_OFF",
                        devices=6, duration=SHORT_DURATION, algorithms=["TRADE_OFF"], seed=SEED)
    learned = tabular.run(tabular.SETTINGS, tmp_path / "q_learning", Agent, "Q_LEARNING",
                          devices=6, duration=SHORT_DURATION, seed=SEED)
    assert learned[COLUMNS[7]] == plain[COLUMNS[7]]
    assert [learned[column] for column in (COLUMNS[15], COLUMNS[17], COLUMNS[19])] != \
           [plain[column] for column in (COLUMNS[15], COLUMNS[17], COLUMNS[19])]


def test_the_extension_points_tour_changes_nothing_in_the_result(tour):
    stock, toured = tour[0], tour[1]
    assert stock == toured


def test_every_extension_point_of_the_tour_is_reached(tour):
    _, _, usage, classes = tour
    assert set(usage) == set(points.HOOKS)
    assert all(count > 0 for count in usage.values())
    assert set(classes) == set(points.HOOKS)
    assert classes == {"simulation manager": "TourSimulationManager", "network model": "TourNetworkModel",
                      "computing nodes generator": "TourNodesGenerator",
                      "topology creator": "TourTopologyCreator", "task generator": "TourTaskGenerator",
                      "mobility model": "TourMobilityModel", "orchestrator": "TourOrchestrator",
                      "computing node": "TourComputingNode"}


def test_the_custom_node_run_reports_its_event_once_per_node(tmp_path):
    custom_node.main(devices=6, duration=SHORT_DURATION, seed=SEED, output=tmp_path / "nodes")
    # One private event per node built from the custom class: the cloud data center,
    # the edge data center and the six devices. Routers stay plain computing nodes.
    assert custom_node.ReportingNode.received == {NodeType.CLOUD: 1, NodeType.EDGE_DATACENTER: 1,
                                                 NodeType.EDGE_DEVICE: 6}


def test_the_custom_node_run_keeps_the_energy_and_cpu_accounting_alive(tmp_path):
    row = custom_node.main(devices=6, duration=SHORT_DURATION, seed=SEED, output=tmp_path / "energy")
    assert row[COLUMNS[32]] > 0
    assert row[COLUMNS[28]] > 0


def test_the_edge_orchestrated_run_never_lets_a_device_decide():
    engine, manager = build(edge_orchestrated, devices=10)
    engine.start()
    placed = [task for task in manager.tasks if task.destination is not None]
    assert placed
    assert {task.orchestrator.type for task in placed} == {NodeType.EDGE_DATACENTER}
    assert sum(1 for task in placed if task.orchestrator is task.source_device) == 0


def test_the_cooperative_run_forwards_tasks_over_the_ring():
    engine, manager = build(cooperation, devices=10)
    engine.start()
    orchestrator = manager.orchestrator
    assert orchestrator.forwarded > 0
    assert orchestrator.local > 0
    assert orchestrator.cloud > 0
    # Every decision came from an edge data center, and several of them took part.
    assert len(orchestrator.orchestrators_used) > 1
    placed = [task for task in manager.tasks if task.destination is not None]
    assert sum(1 for task in placed if task.orchestrator is task.source_device) == 0


def test_the_dynamic_run_replans_while_the_frozen_run_never_does(tmp_path):
    engine, manager = build(repartition, devices=6)
    engine.start()
    assert manager.orchestrator.replans > 1
    assert manager.orchestrator.migrations > 0
    frozen_engine, frozen_manager = build(repartition, devices=6, frozen=True)
    frozen_engine.start()
    assert frozen_manager.orchestrator.replans == 1
    assert frozen_manager.orchestrator.migrations == 0


# ---------------------------------------------------------------- the tabular agent

def test_the_state_is_the_task_type_a_length_bucket_and_a_tier_load_bucket():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    tier = NodeType.CLOUD
    assert orchestrator.state_key(task, tier) == "Non Real-time|1|0"
    assert [tabular.length_bucket(length) for length in (999.0, 1000.0, 5000.0, 20000.0)] == [0, 1, 2, 3]
    # The load bucket is what makes the state change while the tier is busy: the
    # settings put a single cloud node, so one task in flight is one task per node.
    place(orchestrator, "Q_LEARNING", task)
    assert orchestrator.load_bucket(tier) == 1
    assert orchestrator.state_key(task, tier) == "Non Real-time|1|1"


def test_the_actions_are_the_tiers_the_architecture_allows():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device)
    assert orchestrator.layers == [NodeType.CLOUD, NodeType.EDGE_DATACENTER, NodeType.EDGE_DEVICE]
    options = orchestrator.available_nodes(task)
    assert [action for action, _ in options] == list(range(len(orchestrator.layers)))
    assert [orchestrator.candidates[index].type for _, index in options] == orchestrator.layers


def test_a_tier_without_a_reachable_node_leaves_the_action_space():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device)
    # A dead device cannot run anything, not even the task it generated, so the
    # mist action disappears while the cloud and the edge stay.
    for node in orchestrator.candidates:
        if node.type is NodeType.EDGE_DEVICE:
            node.status = NodeStatus.DEAD
    options = orchestrator.available_nodes(task)
    assert [orchestrator.layers[action] for action, _ in options] == [NodeType.CLOUD,
                                                                     NodeType.EDGE_DATACENTER]


def test_the_agent_refuses_a_scenario_it_was_not_declared_for():
    with pytest.raises(ValueError, match="Q_LEARNING"):
        build(tabular, algorithm="TRADE_OFF")


def test_a_greedy_decision_takes_the_tier_with_the_best_value():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    options = orchestrator.available_nodes(task)
    assert len(options) == 3
    orchestrator.q_table[orchestrator.state_key(task, orchestrator.layers[0])] = [0.0, -1.0, -2.0]
    # One draw in ten explores; this one does not.
    orchestrator.random = Draw(0.5)
    assert orchestrator.choose_action(task, options) == options[0]


def test_the_exploration_draw_replaces_the_best_tier():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    options = orchestrator.available_nodes(task)
    orchestrator.q_table[orchestrator.state_key(task, orchestrator.layers[0])] = [0.0, -1.0, -2.0]
    # A draw under EXPLORATION_RATE sends the task to a random tier instead.
    orchestrator.random = Draw(0.0)
    assert orchestrator.choose_action(task, options) == options[-1]


def test_a_failure_is_punished_harder_than_a_slow_success():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    slow = make_task(device, task_id=1)
    succeed(slow, 3.0)
    broken = make_task(device, task_id=2)
    broken.status = TaskStatus.FAILED_DUE_TO_DELAY
    assert orchestrator.reward(slow) == pytest.approx(-slow.total_delay)
    assert orchestrator.reward(broken) == pytest.approx(-Agent.FAILURE_PENALTY)
    assert orchestrator.reward(broken) < orchestrator.reward(slow)


def test_a_state_the_table_never_saw_is_worth_zero():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    assert orchestrator.q_value("Non Real-time|0|0", 0) == 0.0
    assert orchestrator.max_value("Non Real-time|0|0") == 0.0


def test_the_update_uses_the_reward_and_the_discounted_future_of_the_next_state():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    index = place(orchestrator, "Q_LEARNING", task)
    decision = orchestrator.decisions[task.id]
    # An empty table is all zeros, so the greedy choice is the first action: cloud.
    assert decision.tier is NodeType.CLOUD
    orchestrator.q_table[decision.state] = [-0.5] * len(orchestrator.layers)
    succeed(task, 0.2)
    # The next state is the one the tier is in once the results are back, so its
    # load bucket has come down; give it known values to see the discount at work.
    orchestrator.pending_per_tier[decision.tier] -= 1
    next_state = orchestrator.state_key(task, decision.tier)
    orchestrator.pending_per_tier[decision.tier] += 1
    assert next_state != decision.state
    orchestrator.q_table[next_state] = [-1.0, -0.2, -3.0]
    orchestrator.results_returned(task)
    expected = -0.5 + Agent.LEARNING_RATE * (
        orchestrator.reward(task) + Agent.DISCOUNT_RATE * -0.2 - (-0.5))
    assert orchestrator.q_value(decision.state, decision.action) == pytest.approx(expected)
    assert orchestrator.decisions == {}


def test_an_unseen_next_state_contributes_nothing_to_the_update():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    place(orchestrator, "Q_LEARNING", task)
    decision = orchestrator.decisions[task.id]
    orchestrator.q_table[decision.state] = [-0.5] * len(orchestrator.layers)
    succeed(task, 0.2)
    orchestrator.results_returned(task)
    # Q <- Q + LR * (r + gamma * 0 - Q), the whole table of the next state unseen.
    assert orchestrator.q_value(decision.state, decision.action) == pytest.approx(-0.48)


def test_a_task_that_never_returns_is_learned_as_a_failure():
    _, manager = build(tabular)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    place(orchestrator, "Q_LEARNING", task)
    decision = orchestrator.decisions[task.id]
    assert orchestrator.pending_per_tier[decision.tier] == 1
    # The manager never notifies a task that died on the way, so the sweep does.
    task.failed = True
    task.status = TaskStatus.FAILED_DUE_TO_DEVICE_DEATH
    orchestrator.reconcile()
    assert orchestrator.decisions == {}
    assert orchestrator.pending_per_tier[decision.tier] == 0
    assert orchestrator.q_value(decision.state, decision.action) == pytest.approx(
        -Agent.FAILURE_PENALTY * Agent.LEARNING_RATE)


def test_the_least_loaded_node_of_a_tier_gets_its_next_task():
    _, manager = build(tabular, devices=10)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    tier = NodeType.EDGE_DEVICE
    eligible = [index for index, node in enumerate(orchestrator.candidates)
                if node.type is tier and orchestrator.offloading_is_possible(node, task)]
    assert len(eligible) > 1

    def score(index):
        node = orchestrator.candidates[index]
        return (orchestrator.node_load[index] + 1) * task.length / node.mips_per_core

    # The tier picks its node with the trade-off score, load included.
    chosen = orchestrator.node_in_tier(tier, task)
    assert chosen in eligible
    assert score(chosen) == min(score(index) for index in eligible)
    # So a node that has already absorbed its share of the workload loses the next
    # task to a quieter peer.
    orchestrator.node_load[chosen] += 100
    quieter = orchestrator.node_in_tier(tier, task)
    assert quieter != chosen
    assert orchestrator.node_load[quieter] < orchestrator.node_load[chosen]


def test_the_tabular_agent_never_brings_a_node_load_back_down():
    """The counterpart of the Java ``assignments`` array: a node keeps its lifetime count."""
    _, manager = build(tabular, devices=10)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    first = make_task(device)
    index = place(orchestrator, "Q_LEARNING", first)
    # The cloud tier has a single node, so a second task lands on it and the count
    # grows: that is what makes the tier hand the next task to another node.
    assert orchestrator.node_load[index] == 1
    assert place(orchestrator, "Q_LEARNING", make_task(device, task_id=2)) == index
    assert orchestrator.node_load[index] == 2
    succeed(first, 0.2)
    orchestrator.results_returned(first)
    assert orchestrator.pending_per_tier[NodeType.CLOUD] == 1
    assert orchestrator.node_load[index] == 2


# -------------------------------------------------------------------- softmax

def test_the_weight_of_an_option_is_the_exponential_of_its_value():
    _, manager = build(softmax)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    options = orchestrator.available_nodes(task)
    orchestrator.q_table[orchestrator.state_key(task, orchestrator.layers[0])] = [0.0, -0.05, -0.5]
    temperature = softmax.TEMPERATURE
    assert orchestrator.boltzmann_weights(task, options) == pytest.approx(
        [1.0, math.exp(-0.05 / temperature), math.exp(-0.5 / temperature)])


def test_the_probabilities_are_the_weights_divided_by_their_sum():
    _, manager = build(softmax)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    options = orchestrator.available_nodes(task)
    orchestrator.q_table[orchestrator.state_key(task, orchestrator.layers[0])] = [0.0, -0.05, -0.5]
    weights = orchestrator.boltzmann_weights(task, options)
    assert orchestrator.probabilities(task, options) == pytest.approx(
        [weight / sum(weights) for weight in weights])
    assert sum(orchestrator.probabilities(task, options)) == pytest.approx(1.0)


def test_a_cold_softmax_keeps_almost_every_draw_for_the_best_tier():
    _, manager = build(softmax)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    options = orchestrator.available_nodes(task)
    orchestrator.q_table[orchestrator.state_key(task, orchestrator.layers[0])] = [0.0, -0.05, -0.5]
    orchestrator.TEMPERATURE = 1e-6
    try:
        assert orchestrator.probabilities(task, options) == pytest.approx([1.0, 0.0, 0.0])
    finally:
        orchestrator.TEMPERATURE = softmax.SoftmaxOrchestrator.TEMPERATURE


def test_an_untrained_softmax_table_draws_each_tier_equally():
    _, manager = build(softmax)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    options = orchestrator.available_nodes(task)
    orchestrator.q_table[orchestrator.state_key(task, orchestrator.layers[0])] = [0.0, 0.0, 0.0]
    assert orchestrator.probabilities(task, options) == pytest.approx([1 / 3] * 3)


def test_the_softmax_draw_walks_the_distribution_in_order():
    _, manager = build(softmax)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    options = orchestrator.available_nodes(task)
    orchestrator.q_table[orchestrator.state_key(task, orchestrator.layers[0])] = [0.0, -0.05, -0.5]
    probabilities = orchestrator.probabilities(task, options)
    orchestrator.random = Draw(probabilities[0] / 2)
    assert orchestrator.choose_action(task, options) == options[0]
    orchestrator.random = Draw(probabilities[0] + probabilities[1] / 2)
    assert orchestrator.choose_action(task, options) == options[1]
    orchestrator.random = Draw(1.0)
    assert orchestrator.choose_action(task, options) == options[-1]


def test_the_softmax_reward_is_the_delay_divided_by_the_latency_bound():
    _, manager = build(softmax)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager), max_latency=4.0)
    succeed(task, 1.0)
    assert orchestrator.reward(task) == pytest.approx(-task.total_delay / 4.0)
    assert softmax.SoftmaxOrchestrator.FAILURE_PENALTY < Agent.FAILURE_PENALTY


def test_the_softmax_releases_the_node_it_was_using():
    _, manager = build(softmax, devices=10)
    orchestrator = manager.orchestrator
    task = make_task(served_device(manager))
    index = place(orchestrator, "SOFTMAX", task)
    assert orchestrator.node_load[index] == 1
    succeed(task, 0.2)
    orchestrator.results_returned(task)
    assert orchestrator.node_load[index] == 0
    assert sum(orchestrator.pending_per_tier.values()) == 0


# ------------------------------------------------------------------- mist only

def test_the_mist_only_agent_has_a_single_action():
    _, manager = build(mist_only, devices=10)
    orchestrator = manager.orchestrator
    assert orchestrator.layers == [NodeType.EDGE_DEVICE]
    options = orchestrator.available_nodes(make_task(served_device(manager)))
    assert [action for action, _ in options] == [0]


def test_the_mist_only_agent_never_returns_a_cloud_or_edge_node():
    _, manager = build(mist_only, devices=10)
    orchestrator = manager.orchestrator
    placed = 0
    for identifier, origin in enumerate(manager.edge_devices, start=1):
        index = place(orchestrator, "Q_LEARNING", make_task(origin, task_id=identifier))
        if index >= 0:
            placed += 1
            assert orchestrator.candidates[index].type is NodeType.EDGE_DEVICE
    assert placed > 0


def test_an_isolated_mist_device_runs_the_task_itself():
    _, manager = build(mist_only, devices=10)
    orchestrator = manager.orchestrator
    manager.parameters.edge_devices_range = 0.0
    for origin in [node for node in manager.edge_devices if not node.is_sensor][:2]:
        # No peer in range: the only mist node left for this device is itself.
        origin.distance_to = lambda other, node=origin: 0.0 if other is node else 1e9
        index = place(orchestrator, "Q_LEARNING", make_task(origin))
        assert orchestrator.candidates[index] is origin


# ---------------------------------------------------------- edge orchestrated

def test_an_edge_data_center_takes_the_decision_for_the_device():
    _, manager = build(edge_orchestrated, devices=6)
    device = served_device(manager)
    task = make_task(device)
    assert manager.parameters.enable_orchestrators
    selected = manager._select_orchestrator(task)
    assert selected.type is NodeType.EDGE_DATACENTER
    assert selected is device.serving_edge_data_center
    assert selected is not device


def test_switching_the_orchestrators_off_gives_the_decision_back_to_the_device():
    _, manager = build(edge_orchestrated, devices=6)
    manager.parameters.enable_orchestrators = False
    assert manager._select_orchestrator(make_task(served_device(manager))) is served_device(manager)


# ------------------------------------------------------- dynamic repartition

def _subtask_of(manager, identifier=1):
    task = next(t for t in manager.tasks if t.subtask_name)
    task.id = identifier
    return task


def test_the_first_request_establishes_one_tier_per_stage():
    _, manager = build(repartition, devices=6)
    orchestrator = manager.orchestrator
    task = _subtask_of(manager)
    assert place(orchestrator, "TRADE_OFF", task) >= 0
    plan = orchestrator.plans[task.application_id]
    assert set(plan) == {subtask.name for subtask in manager.applications[task.application_id].subtasks}
    assert set(plan.values()) <= set(orchestrator.architecture_layers)
    assert orchestrator.replans == 1
    assert orchestrator.migrations == 0


def test_a_fresh_plan_is_not_replanned_before_the_interval():
    _, manager = build(repartition, devices=6)
    orchestrator = manager.orchestrator
    task = _subtask_of(manager)
    place(orchestrator, "TRADE_OFF", task)
    plan = orchestrator.plans[task.application_id]
    assert orchestrator._should_replan(task.application_id, plan) is False
    place(orchestrator, "TRADE_OFF", _subtask_of(manager, identifier=2))
    assert orchestrator.replans == 1


def test_a_tier_that_loses_every_node_forces_a_replan():
    _, manager = build(repartition, devices=6)
    orchestrator = manager.orchestrator
    task = _subtask_of(manager)
    place(orchestrator, "TRADE_OFF", task)
    plan = dict(orchestrator.plans[task.application_id])
    tiers = {tier: sum(1 for value in plan.values() if value is tier) for tier in set(plan.values())}
    victim = max(tiers, key=tiers.get)
    for node in orchestrator.candidates:
        if node.type is victim:
            node.status = NodeStatus.DEAD
    assert orchestrator._has_available_node(victim) is False
    # The clock has not moved: only the dead tier can trigger the refresh.
    assert orchestrator._should_replan(task.application_id, plan) is True
    place(orchestrator, "TRADE_OFF", _subtask_of(manager, identifier=3))
    assert orchestrator.replans == 2
    assert orchestrator.migrations == tiers[victim]
    assert victim not in set(orchestrator.plans[task.application_id].values())


def test_a_time_dependent_plan_is_not_cached_by_the_device():
    _, manager = build(repartition, devices=6)
    orchestrator = manager.orchestrator
    task = _subtask_of(manager)
    orchestrator.orchestrate(task, task.application_id)
    # The manager marks the device as placed; the example clears it again, so the
    # next task of the same device is decided afresh.
    assert task.source_device.application_placed is False
    assert task.destination is not None


def test_a_frozen_plan_is_computed_once_and_never_touched():
    _, manager = build(repartition, devices=6, frozen=True)
    orchestrator = manager.orchestrator
    task = _subtask_of(manager)
    place(orchestrator, "TRADE_OFF", task)
    plan = dict(orchestrator.plans[task.application_id])
    for node in orchestrator.candidates:
        if node.type in set(plan.values()):
            node.status = NodeStatus.DEAD
    manager.engine.clock = repartition.REPLAN_INTERVAL * 4
    place(orchestrator, "TRADE_OFF", _subtask_of(manager, identifier=4))
    assert orchestrator.replans == 1
    assert orchestrator.migrations == 0
    assert orchestrator.plans[task.application_id] == plan


# --------------------------------------------------------- edge cooperation

def _device_with_a_ring(manager, orchestrator):
    """A device whose MAN ring reaches further than the base rule allows."""
    for origin in manager.edge_devices:
        if origin.is_sensor or origin.serving_edge_data_center is None:
            continue
        task = make_task(origin)
        task.orchestrator = origin.serving_edge_data_center
        data_centers = [node for _, node in orchestrator.eligible_for(task)
                        if node.type is NodeType.EDGE_DATACENTER]
        if len(data_centers) > 1:
            return origin, task, data_centers
    raise AssertionError("no device reaches a second edge data center through the ring")


def test_the_ring_offers_a_data_center_the_base_rule_refuses():
    _, manager = build(cooperation, devices=10)
    orchestrator = manager.orchestrator
    origin, task, data_centers = _device_with_a_ring(manager, orchestrator)
    assert origin.serving_edge_data_center in data_centers
    other = next(node for node in data_centers if node is not origin.serving_edge_data_center)
    # The inherited rule would refuse that one: the device may only use its own DC.
    assert orchestrator.offloading_is_possible(other, task) is False
    assert other.type is NodeType.EDGE_DATACENTER


def test_a_task_sent_to_a_neighbouring_data_center_is_counted_as_forwarded():
    _, manager = build(cooperation, devices=10)
    orchestrator = manager.orchestrator
    _, task, _ = _device_with_a_ring(manager, orchestrator)
    index = place(orchestrator, "TRADE_OFF", task)
    assert orchestrator.candidates[index] is not task.source_device.serving_edge_data_center
    assert orchestrator.forwarded == 1
    assert orchestrator.local == 0
    assert orchestrator.orchestrators_used == {task.orchestrator.id}


def test_a_task_kept_by_its_own_data_center_is_counted_as_local():
    _, manager = build(cooperation, devices=10)
    orchestrator = manager.orchestrator
    for origin in manager.edge_devices:
        if origin.is_sensor or origin.serving_edge_data_center is None:
            continue
        task = make_task(origin)
        task.orchestrator = origin.serving_edge_data_center
        # The device has to be closest to its own server for the local count to move.
        if orchestrator.trade_off(orchestrator.eligible_for(task), task) != \
                orchestrator.candidates.index(origin.serving_edge_data_center):
            continue
        assert place(orchestrator, "TRADE_OFF", task) >= 0
        assert orchestrator.local == 1
        assert orchestrator.forwarded == 0
        return
    raise AssertionError("no device is served by the nearest edge data center")


def test_a_coverage_of_zero_leaves_the_cloud_and_no_ring():
    _, manager = build(cooperation, devices=10)
    orchestrator = manager.orchestrator
    manager.parameters.edge_data_centers_range = 0.0
    task = make_task(manager.edge_devices[0])
    task.orchestrator = manager.edge_devices[0].serving_edge_data_center
    assert [node.type for _, node in orchestrator.eligible_for(task)] == [NodeType.CLOUD]
    index = place(orchestrator, "TRADE_OFF", task)
    assert orchestrator.candidates[index].type is NodeType.CLOUD
    assert orchestrator.cloud == 1
    assert orchestrator.forwarded == 0


# ------------------------------------------------------ the extension points

def test_the_observing_node_keeps_the_flags_the_fleet_needs():
    _, manager = build(points, devices=4, architecture="ALL", algorithm="TRADE_OFF",
                      computing_node=points.TourComputingNode)
    # Every cloud, edge and device node is built from the registered class; only the
    # network routers stay plain computing nodes.
    assert {type(node).__name__ for node in manager.computing_nodes} <= {"TourComputingNode", "Router"}
    assert any(isinstance(node, points.TourComputingNode) for node in manager.computing_nodes)
    # One class builds every layer, so the type setter has to keep the peripheral
    # flag the mobile devices use to list the edge data centers they can reach.
    for node in manager.nodes_generator.edge_data_centers:
        assert node.is_peripheral
    for device in manager.edge_devices:
        assert not device.is_peripheral


# ------------------------------------------------------- the custom node

@pytest.fixture(scope="module")
def custom_manager():
    """A manager whose whole cloud/edge fleet is the example's node class, not run."""
    engine, manager = build(custom_node, devices=4, architecture="ALL", algorithm="TRADE_OFF",
                            computing_node=custom_node.ReportingNode)
    custom_node.ReportingNode.received.clear()
    return engine, manager


def test_the_custom_tag_is_not_one_the_framework_uses():
    framework = {event.value for event in EventType}
    assert custom_node.DO_SOMETHING not in framework
    assert custom_node.DO_SOMETHING > max(framework)


def test_a_node_schedules_its_own_event_when_the_simulation_starts(custom_manager):
    engine, manager = custom_manager
    node = manager.nodes_generator.cloud_nodes[0]
    queued = len(engine.queue)
    node.on_simulation_start()
    assert len(engine.queue) == queued + 1
    assert engine.queue.remove(lambda event: (event.tag == custom_node.DO_SOMETHING
                                              and event.destination is node)) == 1


def test_the_node_counts_its_own_event_and_does_not_forward_it(custom_manager):
    engine, manager = custom_manager
    node = manager.nodes_generator.cloud_nodes[0]
    queued = len(engine.queue)
    before = custom_node.ReportingNode.received[NodeType.CLOUD]
    node.process_event(Event(engine.clock, 0, node, custom_node.DO_SOMETHING))
    assert custom_node.ReportingNode.received[NodeType.CLOUD] == before + 1
    # The node owns this tag, so nothing is handed to the default implementation.
    assert len(engine.queue) == queued


def test_an_event_the_node_does_not_own_is_handed_to_the_framework(custom_manager):
    engine, manager = custom_manager
    node = manager.nodes_generator.cloud_nodes[0]
    queued = len(engine.queue)
    counted = sum(custom_node.ReportingNode.received.values())
    # The status tick is the framework's own: the default node answers it and queues
    # the next one, which is what keeps the energy and CPU columns alive.
    node.process_event(Event(engine.clock, 0, node, EventType.UPDATE_STATUS))
    assert len(engine.queue) == queued + 1
    assert sum(custom_node.ReportingNode.received.values()) == counted
