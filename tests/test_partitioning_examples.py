"""End-to-end runs of the two partitioning examples, on the real settings."""
from __future__ import annotations

import pytest

from examples.genetic_partitioning.genetic_partitioning import GeneticOrchestrator
from examples.graph_partitioning.graph_partitioning import GraphPartitioningOrchestrator
from examples.graph_partitioning.graph_partitioning import SETTINGS as PARTITIONING_SETTINGS
from pureedgesim import Engine, Randomness, Scenario, SimulationManager, load_parameters, load_settings


def run(orchestrator, seed=42):
    parameters = load_parameters(PARTITIONING_SETTINGS / "simulation_parameters.properties")
    parameters.simulation_duration = 60.0
    parameters.min_number_of_devices = parameters.max_number_of_devices = 40
    parameters.devices_increment = 1
    parameters.random_seed = seed
    Randomness.set_seed(seed)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, load_settings(PARTITIONING_SETTINGS),
                                Scenario("ALL", "TRADE_OFF", 40), custom_orchestrator=orchestrator)
    manager.start_simulation()
    engine.start()
    return manager


@pytest.mark.parametrize("orchestrator", [GraphPartitioningOrchestrator, GeneticOrchestrator])
def test_the_example_runs_every_generated_task(orchestrator):
    manager = run(orchestrator)
    metrics = manager.metrics
    assert metrics.generated_tasks > 0
    # The request deadline can fail a subtask that met its own bound, so the
    # run is judged on reaching a terminal state, not on succeeding everywhere.
    assert len(manager.finished_tasks) == metrics.generated_tasks
    assert metrics.succeeded_tasks > 0
    assert metrics.mist_tasks + metrics.edge_tasks + metrics.cloud_tasks > 0


def test_the_graph_plan_spreads_the_subtasks_over_the_tiers():
    manager = run(GraphPartitioningOrchestrator)
    # The plan maps partition 0 to mist, 1 to edge and 2 to cloud, so a full run
    # exercises the three tiers.
    assert manager.metrics.cloud_tasks > 0
    assert manager.metrics.edge_tasks > 0
    assert manager.metrics.mist_tasks > 0
