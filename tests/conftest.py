"""Shared fixtures: real settings files and a real, un-run simulation manager."""
from __future__ import annotations

from pathlib import Path

import pytest

from pureedgesim import (Engine, Randomness, Scenario, SimulationManager, load_parameters, load_settings)

SETTINGS = Path(__file__).resolve().parents[1] / "examples" / "default_settings"


@pytest.fixture(scope="session")
def settings_folder() -> Path:
    return SETTINGS


@pytest.fixture
def parameters() -> "pureedgesim.SimulationParameters":
    values = load_parameters(SETTINGS / "simulation_parameters.properties")
    # Two full minutes: the default applications generate one burst of tasks per
    # minute, so a shorter simulation would produce no workload at all.
    values.simulation_duration = 120.0
    values.min_number_of_devices = 3
    values.max_number_of_devices = 3
    values.devices_increment = 1
    values.random_seed = 99
    return values


@pytest.fixture
def files() -> "pureedgesim.ScenarioFiles":
    return load_settings(SETTINGS)


def build_manager(parameters, files, architecture="ALL", algorithm="TRADE_OFF", devices=3,
                  seed=99, iteration=0):
    """A real manager with the topology and the workload built, but not yet run."""
    Randomness.set_seed(seed)
    Randomness.begin_scenario(iteration)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, files, Scenario(architecture, algorithm, devices))
    manager.start_simulation()
    return engine, manager


def run_manager(parameters, files, architecture="ALL", algorithm="TRADE_OFF", devices=3,
                seed=99, iteration=0):
    """A real manager, built and run to the end of the simulation."""
    engine, manager = build_manager(parameters, files, architecture, algorithm, devices, seed, iteration)
    engine.start()
    return engine, manager


def run_until(engine, until, limit=1000):
    """Runs real events, in time order, until the condition holds.

    Tests that need one transfer to complete use this instead of running the whole
    scenario: the workload of the built manager starts one second in, so pumping
    the queue stops as soon as the transfer reaches its destination.
    """
    for _ in range(limit):
        if until():
            return
        event = engine.queue.pop()
        if event is None:
            break
        engine.clock = event.time
        event.destination.process_event(event)
    raise AssertionError("the condition was never reached")


@pytest.fixture
def manager(parameters, files):
    engine, simulation_manager = build_manager(parameters, files)
    return engine, simulation_manager
