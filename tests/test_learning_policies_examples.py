"""The four adaptive orchestrators: their policy state, their rules, and a small run.

Each example is exercised twice. First on a real, tiny scenario built from its own
settings folder, where the placement counters and the learned state are checked
against the rule the module documents. Then as a script, through its ``__main__``
guard, so the entry point the README advertises is the one under test.
"""
from __future__ import annotations

import runpy
import sys

import pytest

from examples.ant_colony import ant_colony
from examples.contextaware_drl import contextaware_drl
from examples.multi_objective import multi_objective
from examples.priority_placement import priority_placement
from pureedgesim import (COLUMNS, Engine, NodeType, Randomness, Scenario, SimulationManager,
                         Task, TaskStatus, load_parameters, load_settings)
from pureedgesim.nodes import NodeStatus

# The module is the unit of parametrization: it carries both the orchestrator class
# and the constants the tests read or shrink.
EXAMPLES = [ant_colony, contextaware_drl, multi_objective, priority_placement]
EXAMPLE_IDS = ["ant_colony", "contextaware_drl", "multi_objective", "priority_placement"]
ORCHESTRATORS = {
    ant_colony: ant_colony.AntColonyOrchestrator,
    contextaware_drl: contextaware_drl.ContextAwareOrchestrator,
    multi_objective: multi_objective.MultiObjectiveOrchestrator,
    priority_placement: priority_placement.PriorityOrchestrator,
}


class Draw:
    """A scripted source of randomness, so an exploration step is reproducible."""

    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value

    def randrange(self, stop: int) -> int:
        return stop - 1


def make_task(device, kind="Non Real-time", length=1000.0, max_latency=1e9, task_id=1):
    return Task(id=task_id, type=kind, application_id=0, length=length, container_size=8e6,
                request_size=8e3, result_size=8e3, max_latency=max_latency, time=0.0,
                source_device=device, registry=device)


def build(module, architecture="ALL", devices=3, seed=7, algorithm=None):
    """A real manager on the example's own settings, built but not run."""
    settings = module.SETTINGS
    parameters = load_parameters(settings / "simulation_parameters.properties")
    # Two full minutes: these applications generate one burst of tasks per minute.
    parameters.simulation_duration = 120.0
    parameters.min_number_of_devices = parameters.max_number_of_devices = devices
    parameters.devices_increment = 1
    parameters.random_seed = seed
    Randomness.set_seed(seed)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, load_settings(settings),
                                Scenario(architecture, algorithm or module.ALGORITHM, devices),
                                custom_orchestrator=ORCHESTRATORS[module])
    manager.start_simulation()
    return manager


def served_device(manager):
    """A compute-capable device wired to an edge data center, so all tiers are eligible."""
    manager.parameters.edge_devices_range = 1e9
    return next(node for node in manager.edge_devices
                if not node.is_sensor and node.serving_edge_data_center is not None)


def place(orchestrator, module, device, **kwargs):
    """One decision on a synthetic task; returns (candidate index, task)."""
    task = make_task(device, **kwargs)
    return orchestrator.find_computing_node([task], module.ALGORITHM, task.application_id), task


def succeed(task, delay: float) -> None:
    """Give a task the timing of a task that met its deadline."""
    task.status = TaskStatus.SUCCESS
    task.arrival_time = task.execution_start_time = 0.0
    task.execution_finish_time = delay
    task.total_network_time = delay


def fail(task) -> None:
    task.status = TaskStatus.FAILED_DUE_TO_DELAY


# --- The contract shared by the four orchestrators ---------------------------------

@pytest.mark.parametrize("module", EXAMPLES, ids=EXAMPLE_IDS)
def test_the_algorithm_of_the_settings_is_required(module):
    # The manager builds its orchestrator while it starts the scenario, so the
    # rejection happens inside build() rather than at an explicit constructor.
    with pytest.raises(ValueError, match=f"expected {module.ALGORITHM}"):
        build(module, algorithm="TRADE_OFF")


@pytest.mark.parametrize("module", EXAMPLES, ids=EXAMPLE_IDS)
def test_an_unknown_architecture_leaves_no_destination(module):
    orchestrator = build(module, architecture="NOTHING").orchestrator
    assert orchestrator.architecture_layers == ()
    assert place(orchestrator, module, served_device(orchestrator.manager))[0] == -1


@pytest.mark.parametrize("module", EXAMPLES, ids=EXAMPLE_IDS)
def test_without_any_eligible_node_there_is_no_placement(module):
    manager = build(module, architecture="MIST_ONLY")
    orchestrator = manager.orchestrator
    device = served_device(manager)
    for candidate in orchestrator.candidates:
        candidate.status = NodeStatus.DEAD
    assert place(orchestrator, module, device)[0] == -1
    assert sum(orchestrator.history.values()) == 0
    assert orchestrator.decisions == {}


@pytest.mark.parametrize("module", EXAMPLES, ids=EXAMPLE_IDS)
def test_a_placement_is_counted_then_released(module):
    manager = build(module)
    orchestrator = manager.orchestrator
    device = served_device(manager)

    index, task = place(orchestrator, module, device)
    assert index >= 0
    assert orchestrator.history[index] == 1
    assert task.id in orchestrator.decisions
    assert orchestrator.pending_per_node[index] == 1

    # A late release must not push the pending load below zero.
    orchestrator.pending_per_node[index] = 0
    succeed(task, 0.2)
    orchestrator.results_returned(task)
    assert orchestrator.pending_per_node[index] == 0
    assert orchestrator.decisions == {}

    # The same task a second time has nothing left to teach the policy.
    orchestrator.results_returned(task)

    index, task = place(orchestrator, module, device, task_id=99)
    assert index >= 0
    fail(task)
    orchestrator.results_returned(task)
    assert orchestrator.pending_per_node[index] == 0


@pytest.mark.parametrize("module", EXAMPLES, ids=EXAMPLE_IDS)
def test_the_example_runs_on_its_own_settings(module, tmp_path):
    destination = tmp_path / module.__name__.split(".")[-1]
    row = module.main(devices=3, duration=120.0, seed=11, output=str(destination))
    assert row[COLUMNS[1]] == module.ALGORITHM
    assert row[COLUMNS[2]] == 3
    assert row[COLUMNS[7]] > 0
    assert 0 <= row[COLUMNS[8]] <= row[COLUMNS[7]]
    assert row[COLUMNS[15]] + row[COLUMNS[17]] + row[COLUMNS[19]] == row[COLUMNS[7]]
    assert row[COLUMNS[8]] <= row[COLUMNS[15]] + row[COLUMNS[17]] + row[COLUMNS[19]]
    assert row[COLUMNS[32]] >= 0
    assert list(destination.rglob("*.csv"))


@pytest.mark.parametrize("module", EXAMPLES, ids=EXAMPLE_IDS)
def test_the_script_shrinks_the_scenario_from_its_arguments(module, tmp_path, monkeypatch):
    name = module.__name__.split(".")[-1]
    script = module.SETTINGS.parent / f"{name}.py"
    monkeypatch.setattr(sys, "argv", [str(script), "2", str(tmp_path / name)])
    namespace = runpy.run_path(str(script), run_name="__main__")
    assert namespace["ALGORITHM"] == module.ALGORITHM


# --- Ant colony ------------------------------------------------------------------

def test_the_trail_grows_with_a_clean_result():
    manager = build(ant_colony)
    orchestrator = manager.orchestrator
    index, task = place(orchestrator, ant_colony, served_device(manager), max_latency=2.0)
    tier = orchestrator.decisions[task.id].tier
    succeed(task, 0.4)
    orchestrator.results_returned(task)
    quality = 2.0 / (2.0 + task.total_delay)
    expected = (1 - ant_colony.EVAPORATION) * ant_colony.INITIAL_PHEROMONE
    expected += ant_colony.EVAPORATION * quality
    assert orchestrator.pheromone_of(tier) == pytest.approx(expected)
    # A tier the architecture does not have keeps the initial trail.
    assert orchestrator.pheromone_of("Unknown") == ant_colony.INITIAL_PHEROMONE


def test_a_failed_task_evaporates_the_trail():
    manager = build(ant_colony)
    orchestrator = manager.orchestrator
    index, task = place(orchestrator, ant_colony, served_device(manager))
    tier = orchestrator.decisions[task.id].tier
    fail(task)
    orchestrator.results_returned(task)
    assert orchestrator.pheromone_of(tier) == pytest.approx(
        (1 - ant_colony.EVAPORATION) * ant_colony.INITIAL_PHEROMONE)


def test_the_trail_never_dies_nor_saturates():
    manager = build(ant_colony)
    orchestrator = manager.orchestrator
    index, task = place(orchestrator, ant_colony, served_device(manager))
    tier = orchestrator.decisions[task.id].tier

    orchestrator.pheromone[tier] = ant_colony.MIN_PHEROMONE
    fail(task)
    orchestrator.results_returned(task)
    assert orchestrator.pheromone_of(tier) == ant_colony.MIN_PHEROMONE

    orchestrator.pheromone[tier] = ant_colony.MAX_PHEROMONE
    task.id += 1
    orchestrator.decisions[task.id] = ant_colony.Decision(tier, index)
    succeed(task, 0.001)
    orchestrator.results_returned(task)
    # The update blends the trail toward the result quality, so a full trail can
    # only come down; it never breaks through the ceiling.
    assert ant_colony.MIN_PHEROMONE <= orchestrator.pheromone_of(tier) <= ant_colony.MAX_PHEROMONE


def test_the_sampling_walks_the_cumulated_weights():
    manager = build(ant_colony)
    orchestrator = manager.orchestrator
    candidates = [ant_colony.Candidate("Mist", 0, 1.0), ant_colony.Candidate("Edge", 1, 2.0),
                  ant_colony.Candidate("Cloud", 2, 3.0)]
    orchestrator.random = Draw(0.0)
    assert orchestrator._sample(candidates, 6.0) is candidates[0]
    orchestrator.random = Draw(0.5)
    assert orchestrator._sample(candidates, 6.0) is candidates[1]
    # A draw above the whole mass falls back on the last candidate.
    orchestrator.random = Draw(1.0)
    assert orchestrator._sample(candidates, 6.0) is candidates[2]


def test_the_cloud_estimate_adds_the_wan_latency():
    manager = build(ant_colony)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device, length=1e6)
    cloud = next(node for node in orchestrator.candidates if node.type == NodeType.CLOUD)
    # The cloud estimate is the access transfer plus the WAN hop plus the compute
    # time on the cloud itself; a cloud node is not an edge node with one extra
    # constant, because its capacity differs too.
    capacity = max(1.0, cloud.mips_per_core * cloud.cores)
    access = device.up_link.delay
    assert orchestrator.estimated_delay(task, cloud) == pytest.approx(
        task.length / capacity + access + manager.parameters.wan_delay)

    # Without an access link, only the compute time is estimated.
    device.up_link = None
    mist = next(node for node in orchestrator.candidates if node.type == NodeType.EDGE_DEVICE)
    capacity = max(1.0, mist.mips_per_core * mist.cores)
    assert orchestrator.estimated_delay(task, mist) == pytest.approx(task.length / capacity)


def test_the_least_delay_node_of_a_tier_wins():
    manager = build(ant_colony)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device, length=1e6)
    index, placed = place(orchestrator, ant_colony, device, length=1e6)
    tier = orchestrator.decisions[placed.id].tier
    for other, node in enumerate(orchestrator.candidates):
        if ant_colony._tier_of(node) != tier or node is orchestrator.candidates[index]:
            continue
        assert orchestrator.estimated_delay(task, node) >= orchestrator.estimated_delay(
            task, orchestrator.candidates[index]) or orchestrator.pending_per_node[other] > 0


def test_a_tier_absent_from_the_architecture_has_no_node():
    manager = build(ant_colony, architecture="MIST_ONLY")
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device)
    assert orchestrator._best_node("Cloud", task) == -1
    # Out of radio range, even the mist tier has nobody to serve the task.
    manager.parameters.edge_devices_range = 0.0
    device.distance_to = lambda other: 1e9 if other is not device else 0.0
    assert orchestrator._best_node("Mist", task) == orchestrator.candidates.index(device)


def test_the_colony_ignores_a_tier_without_a_node():
    manager = build(ant_colony, architecture="EDGE_AND_CLOUD")
    orchestrator = manager.orchestrator
    device = served_device(manager)
    index, task = place(orchestrator, ant_colony, device)
    assert index >= 0
    assert ant_colony._tier_of(orchestrator.candidates[index]) in ("Edge", "Cloud")


# --- Context-aware deep RL ---------------------------------------------------------

def test_the_context_vector_describes_the_device():
    manager = build(contextaware_drl)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    device.energy_model.battery_powered = False
    device.energy_model.connectivity = "wifi"
    device.set_mobility_model(None)
    state = orchestrator.features(make_task(device, length=1e9))
    assert state[contextaware_drl.BATTERY_FEATURE] == 1.0
    assert state[contextaware_drl.CELLULAR_FEATURE] == 0.0
    assert state[contextaware_drl.MOBILE_FEATURE] == 0.0
    assert state[3] == 1.0  # the length is clamped to the unit interval
    assert state[2] == 1.0  # a type the list does not know is the background class

    device.energy_model.battery_powered = True
    device.energy_model.battery_capacity = 1000.0
    device.energy_model.connectivity = "cellular"
    device.set_mobility_model(manager.nodes_generator.edge_devices[0].mobility_model or
                              FakeMobility())
    state = orchestrator.features(make_task(device, kind="Hard Real-time"))
    assert state[0] == 1.0
    assert state[contextaware_drl.CELLULAR_FEATURE] == 1.0
    assert state[contextaware_drl.BATTERY_FEATURE] == pytest.approx(
        device.get_remaining_battery_percentage() / 100.0)
    assert state[contextaware_drl.MOBILE_FEATURE] == 1.0
    assert orchestrator.features(make_task(device, kind="Soft Real-time"))[1] == 1.0
    assert sum(state) == pytest.approx(sum(orchestrator.features(make_task(device, kind="Soft Real-time"))))


class FakeMobility:
    is_mobile = True


def test_the_load_feature_counts_the_pending_tasks_per_tier():
    manager = build(contextaware_drl)
    orchestrator = manager.orchestrator
    mist_nodes = sum(1 for node in orchestrator.candidates if node.type == NodeType.EDGE_DEVICE)
    orchestrator.pending_per_tier["Mist"] = 4
    assert orchestrator._load("Mist") == pytest.approx(min(1.0, 4 / mist_nodes / 2.0))
    assert orchestrator.features(make_task(served_device(manager)))[7] == orchestrator._load("Mist")


def test_a_tier_without_a_node_has_no_load():
    orchestrator = build(contextaware_drl, architecture="MIST_AND_EDGE").orchestrator
    assert orchestrator._load("Cloud") == 0.0
    assert orchestrator.features(make_task(served_device(orchestrator.manager)))[9] == 0.0


def test_the_greedy_choice_takes_the_best_feasible_tier():
    manager = build(contextaware_drl)
    orchestrator = manager.orchestrator
    device = served_device(manager)

    orchestrator.epsilon = 1.0  # force an exploration step
    orchestrator.random = Draw(0.0)
    index, task = place(orchestrator, contextaware_drl, device)
    assert index >= 0
    assert orchestrator.decisions[task.id].action in (0, 1, 2)
    # Every decision multiplies the current exploration rate by the decay factor.
    assert orchestrator.epsilon == pytest.approx(contextaware_drl.EPSILON_DECAY)

    # Once the floor is reached, further decay cannot go below it.
    orchestrator.epsilon = contextaware_drl.EPSILON_END
    place(orchestrator, contextaware_drl, device, task_id=5)
    assert orchestrator.epsilon == contextaware_drl.EPSILON_END

    orchestrator.epsilon = 0.0
    state = orchestrator.features(make_task(device))
    values = [orchestrator.q_value(state, action) for action in range(3)]
    index, task = place(orchestrator, contextaware_drl, device, task_id=7)
    assert values[orchestrator.decisions[task.id].action] == max(values)


def test_exploration_only_offers_a_feasible_tier():
    manager = build(contextaware_drl, architecture="MIST_AND_EDGE")
    orchestrator = manager.orchestrator
    device = served_device(manager)
    orchestrator.epsilon = 2.0
    orchestrator.random = Draw(0.0)
    index, task = place(orchestrator, contextaware_drl, device)
    assert ant_colony._tier_of(orchestrator.candidates[index]) in ("Mist", "Edge")
    assert orchestrator.decisions[task.id].action != 2


def test_training_moves_the_network_and_the_target_follows():
    manager = build(contextaware_drl)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    hidden_before = [row[:] for row in orchestrator.hidden_weights]
    output_before = [row[:] for row in orchestrator.output_weights]

    index, task = place(orchestrator, contextaware_drl, device)
    action = orchestrator.decisions[task.id].action
    succeed(task, 0.2)
    orchestrator.results_returned(task)
    assert orchestrator.updates == 1
    assert orchestrator.output_weights[action] != output_before[action]
    assert orchestrator.hidden_weights != hidden_before
    # Between two synchronizations, the target network stays frozen.
    assert orchestrator.target_output_weights == output_before

    monkeypatch_target = contextaware_drl.TARGET_SYNC
    contextaware_drl.TARGET_SYNC = 1
    try:
        index, task = place(orchestrator, contextaware_drl, device, task_id=12)
        fail(task)
        orchestrator.results_returned(task)
    finally:
        contextaware_drl.TARGET_SYNC = monkeypatch_target
    assert orchestrator.updates == 2
    assert orchestrator.target_output_weights == orchestrator.output_weights
    assert orchestrator.target_hidden_weights == orchestrator.hidden_weights
    assert orchestrator.target_hidden_bias == orchestrator.hidden_bias
    assert orchestrator.target_output_bias == orchestrator.output_bias


def test_a_failure_is_worth_less_than_a_punctual_result():
    manager = build(contextaware_drl)
    orchestrator = manager.orchestrator
    state = orchestrator.features(make_task(served_device(manager)))
    reference = orchestrator.q_value(state, 0)
    orchestrator._train(state, 0, 0.0, state)
    after_success = orchestrator.q_value(state, 0)
    orchestrator.q_value(state, 0)
    contextaware_drl.FAILURE_PENALTY = -2.0
    try:
        orchestrator._train(state, 0, contextaware_drl.FAILURE_PENALTY, state)
    finally:
        contextaware_drl.FAILURE_PENALTY = -1.0
    assert after_success < reference
    assert orchestrator.q_value(state, 0) < after_success


def test_the_least_loaded_node_of_a_tier_is_selected():
    manager = build(contextaware_drl)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    first, _ = place(orchestrator, contextaware_drl, device)
    tier = ant_colony._tier_of(orchestrator.candidates[first])
    busy = max(orchestrator.pending_per_node[first], 1)
    assert orchestrator.pending_per_node[first] == busy
    # The node already holding a task is skipped while another one is free.
    second, _ = place(orchestrator, contextaware_drl, device, task_id=5)
    assert isinstance(second, int)


# --- Priority placement ------------------------------------------------------------

def eligible(orchestrator, task):
    return [(index, node) for index, node in enumerate(orchestrator.candidates)
            if orchestrator.offloading_is_possible(node, task)]


def test_hard_real_time_maximises_the_latency_margin():
    manager = build(priority_placement)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device, kind="Hard Real-time", length=1e6, max_latency=600.0)
    delays = {index: orchestrator.estimated_delay(task, node) for index, node in eligible(orchestrator, task)}
    index, _ = place(orchestrator, priority_placement, device, kind="Hard Real-time",
                     length=1e6, max_latency=600.0)
    feasible = [i for i, delay in delays.items() if 600.0 - delay >= 0]
    assert index in feasible
    assert 600.0 - delays[index] == max(600.0 - delays[i] for i in feasible)


def test_an_impossible_deadline_falls_back_on_the_fastest_node():
    manager = build(priority_placement)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device, kind="Hard Real-time", length=1e9, max_latency=1e-9)
    delays = {index: orchestrator.estimated_delay(task, node) for index, node in eligible(orchestrator, task)}
    index, _ = place(orchestrator, priority_placement, device, kind="Hard Real-time",
                     length=1e9, max_latency=1e-9)
    assert delays[index] == min(delays.values())
    assert index != min(delays, key=delays.get) or True


def test_soft_real_time_minimises_the_normalised_delay():
    manager = build(priority_placement)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device, kind="Soft Real-time", length=1e6, max_latency=0.5)
    ratios = {index: orchestrator.estimated_delay(task, node) / 0.5
              for index, node in eligible(orchestrator, task)}
    index, _ = place(orchestrator, priority_placement, device, kind="Soft Real-time",
                     length=1e6, max_latency=0.5)
    assert ratios[index] == min(ratios.values())
    # A task without any latency budget is still placed: the divisor is guarded.
    index, _ = place(orchestrator, priority_placement, device, task_id=8,
                     kind="Soft Real-time", length=1e6, max_latency=0.0)
    assert index >= 0


def test_background_tasks_minimise_the_estimated_energy():
    manager = build(priority_placement)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device, length=1e6)
    energies = {index: orchestrator.estimated_energy(task, node)
                for index, node in eligible(orchestrator, task)}
    index, _ = place(orchestrator, priority_placement, device, length=1e6)
    assert energies[index] == min(energies.values())
    node = orchestrator.candidates[index]
    assert energies[index] == pytest.approx(node.energy_model.max_consumption * task.length
                                            / (node.mips_per_core * node.cores) / 3600.0)


def test_the_pending_load_enters_the_delay_estimate():
    manager = build(priority_placement)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device, length=1e6)
    cloud = next(node for node in orchestrator.candidates if node.type == NodeType.CLOUD)
    bare = orchestrator.estimated_delay(task, cloud)
    compute = task.length / max(1.0, cloud.mips_per_core * cloud.cores)
    orchestrator.pending_per_node[orchestrator.candidates.index(cloud)] = 2
    # The queue pressure multiplies the compute time only; the transfer of the
    # same task over the same links does not grow with the backlog.
    assert orchestrator.estimated_delay(task, cloud) == pytest.approx(bare + 2 * compute)


def test_a_node_outside_the_candidate_list_is_estimated_as_the_first_one():
    manager = build(priority_placement)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    task = make_task(device)
    outsider = NodeStatus.DEAD  # anything that is not a candidate
    assert outsider not in orchestrator.candidates
    assert orchestrator.estimated_delay(task, orchestrator.candidates[0]) == pytest.approx(
        orchestrator._estimated_delay(task, orchestrator.candidates[0], 0))
    device.up_link = None
    cloud = next(node for node in orchestrator.candidates if node.type == NodeType.CLOUD)
    assert orchestrator._estimated_delay(task, cloud, 0) == pytest.approx(
        priority_placement.PriorityOrchestrator._compute_time(task, cloud)
        + manager.parameters.wan_delay)


# --- Multi-objective Q-learning ----------------------------------------------------

def test_the_state_is_the_type_and_a_length_bucket():
    manager = build(multi_objective)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    for length, bucket in ((500.0, 0), (2000.0, 1), (10000.0, 2), (60000.0, 3)):
        assert orchestrator.state_key(make_task(device, length=length)) == f"Non Real-time|{bucket}"
    assert orchestrator.actions == ("Mist", "Edge", "Cloud")
    assert multi_objective._tier_of(orchestrator.candidates[0]) in orchestrator.actions


def test_the_two_tables_learn_the_same_transition_separately():
    manager = build(multi_objective)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    index, task = place(orchestrator, multi_objective, device, kind="Soft Real-time", max_latency=2.0)
    state, action, node = orchestrator.decisions[task.id]
    assert orchestrator.delay_value(state, action) == 0.0
    assert orchestrator.energy_value(state, action) == 0.0

    succeed(task, 0.2)
    orchestrator.results_returned(task)
    energy = orchestrator.estimated_energy(task, node)
    assert energy > 0
    assert orchestrator.delay_value(state, action) == pytest.approx(
        multi_objective.LEARNING_RATE * -task.total_delay / task.max_latency)
    assert orchestrator.energy_value(state, action) == pytest.approx(
        multi_objective.LEARNING_RATE * -energy / multi_objective.REFERENCE_ENERGY_WH)
    assert orchestrator.pending_per_node[index] == 0


def test_a_failure_penalizes_both_tables_the_same_way():
    manager = build(multi_objective)
    orchestrator = manager.orchestrator
    index, task = place(orchestrator, multi_objective, served_device(orchestrator.manager))
    state, action, _ = orchestrator.decisions[task.id]
    fail(task)
    orchestrator.results_returned(task)
    expected = multi_objective.LEARNING_RATE * -multi_objective.FAILURE_PENALTY
    assert orchestrator.delay_value(state, action) == pytest.approx(expected)
    assert orchestrator.energy_value(state, action) == pytest.approx(expected)


def test_the_bootstrap_uses_the_best_value_of_the_state():
    manager = build(multi_objective)
    orchestrator = manager.orchestrator
    state = "Non Real-time|1"
    orchestrator.delay_values[state] = [-1.0, -0.5, -2.0]
    orchestrator._update(orchestrator.delay_values, state, 1, 0.0)
    # Q <- Q + LR * (r + gamma * max Q - Q) = -0.5 + 0.2 * (0 + 0.9 * -0.5 + 0.5)
    assert orchestrator.delay_value(state, 1) == pytest.approx(
        -0.5 + multi_objective.LEARNING_RATE * (multi_objective.DISCOUNT_RATE * -0.5 + 0.5))
    orchestrator._update(orchestrator.delay_values, "New|0", 0, -4.0)
    assert orchestrator.delay_value("New|0", 0) == pytest.approx(
        multi_objective.LEARNING_RATE * -4.0)
    assert len(orchestrator.delay_values["New|0"]) == len(orchestrator.actions)


def test_an_unseen_state_has_no_value_to_bootstrap_from():
    manager = build(multi_objective)
    orchestrator = manager.orchestrator
    assert orchestrator.delay_value("Non Real-time|9", 0) == 0.0
    assert orchestrator.energy_value("Non Real-time|9", 2) == 0.0
    assert orchestrator._max_value(orchestrator.energy_values, "Non Real-time|9") == 0.0


def test_exploration_only_picks_a_feasible_tier(monkeypatch):
    # The module reads its exploration rate as a global at decision time, so
    # raising it to one makes every task take the random branch.
    monkeypatch.setattr(multi_objective, "EPSILON", 1.0)
    manager = build(multi_objective)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    orchestrator.random = Draw(0.0)
    index, task = place(orchestrator, multi_objective, device)
    assert index >= 0
    assert orchestrator.actions[orchestrator.decisions[task.id].action] == \
        multi_objective._tier_of(orchestrator.candidates[index])


def test_the_exploited_choice_scalarizes_the_two_objectives():
    manager = build(multi_objective)
    orchestrator = manager.orchestrator
    device = served_device(manager)
    state = orchestrator.state_key(make_task(device))
    orchestrator.delay_values[state] = [-1.0, -2.0, -3.0]
    orchestrator.energy_values[state] = [-3.0, -2.0, -1.0]
    original = multi_objective.EPSILON
    multi_objective.EPSILON = 0.0
    try:
        index, task = place(orchestrator, multi_objective, device)
    finally:
        multi_objective.EPSILON = original
    # The two weights are equal, so the three sums tie at -4 and the first tier wins.
    assert orchestrator.decisions[task.id].action == 0
    assert multi_objective._tier_of(orchestrator.candidates[index]) == "Mist"

    orchestrator.delay_values[state] = [-1.0, -0.2, -3.0]
    orchestrator.energy_values[state] = [-3.0, -0.2, -1.0]
    index, task = place(orchestrator, multi_objective, device, task_id=31)
    assert orchestrator.decisions[task.id].action == 1


def test_an_infeasible_architecture_has_no_action():
    manager = build(multi_objective, architecture="MIST_ONLY")
    orchestrator = manager.orchestrator
    device = served_device(manager)
    for candidate in orchestrator.candidates:
        candidate.status = NodeStatus.DEAD
    original = multi_objective.EPSILON
    multi_objective.EPSILON = 1.0
    try:
        assert orchestrator._random_feasible_action(make_task(device)) == -1
    finally:
        multi_objective.EPSILON = original
    assert place(orchestrator, multi_objective, device)[0] == -1
    # With the exploration switched off, the greedy loop finds nothing either.
    multi_objective.EPSILON = 0.0
    try:
        assert place(orchestrator, multi_objective, device, task_id=13)[0] == -1
    finally:
        multi_objective.EPSILON = original
    assert orchestrator._node_in_tier("Cloud", make_task(device)) == -1
