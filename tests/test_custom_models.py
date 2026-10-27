"""The four custom models of ``examples/custom_models``, checked on a shrunk run.

The example makes four claims, and each is tested on a real launch of the shipped
scenario (six devices, two simulated minutes, seed 11):

* ``TypeGuaranteeGenerator`` reserves the 2 percent device type that the default
  largest-remainder split rounds down to zero devices.
* ``FullMeshTopologyCreator`` turns the declared ring of edge data centers into a
  full mesh, so two opposite data centers are one hop apart instead of two.
* ``BurstTaskGenerator`` keeps the size of the workload but lands every device's
  first minute of requests on the same instant.
* ``AuditSimulationManager`` audits each task once and its ledger equals the
  standard report columns of the same CSV row.

The stock run is launched alongside every custom run, so a hook that quietly
stopped changing anything (the failure mode of ``examples/extension_points``)
would leave the two identical and fail here.
"""
from __future__ import annotations

import csv
from collections import Counter

import pytest

from examples.custom_models import custom_models as models
from pureedgesim import (COLUMNS, ComputingNodesGenerator, Engine, LinkType, Randomness, Scenario,
                         SimulationManager, load_parameters, load_settings)

# Six devices over two minutes is the smallest scenario that still generates a
# burst for every application, reserves a whole device type and keeps the run fast.
SHORT_DURATION = 120.0
SEED = 11
DEVICES = 6

# The four types declared by settings/edge_devices.xml, in order.
SHARES = [39.0, 29.0, 30.0, 2.0]

CUSTOM_MODELS = {
    "custom_nodes_generator": models.TypeGuaranteeGenerator,
    "custom_topology_creator": models.FullMeshTopologyCreator,
    "custom_task_generator": models.BurstTaskGenerator,
}


def _parameters(devices: int, duration: float, seed: int):
    values = load_parameters(models.SETTINGS / "simulation_parameters.properties")
    values.simulation_duration = duration
    values.min_number_of_devices = values.max_number_of_devices = devices
    values.devices_increment = 1
    values.random_seed = seed
    values.save_log_file = False
    return values


def _build(custom: bool, devices: int = DEVICES, duration: float = SHORT_DURATION, seed: int = SEED):
    """A manager with the topology and the workload built, but not yet run."""
    parameters = _parameters(devices, duration, seed)
    files = load_settings(models.SETTINGS)
    architecture = parameters.orchestration_architectures[0]
    algorithm = parameters.orchestration_algorithms[0]
    Randomness.set_seed(seed)
    Randomness.begin_scenario(0)
    engine = Engine(duration)
    manager_class = models.AuditSimulationManager if custom else SimulationManager
    manager = manager_class(engine, parameters, files, Scenario(architecture, algorithm, devices),
                            **(CUSTOM_MODELS if custom else {}))
    manager.start_simulation()
    return engine, manager


def _man_links(manager) -> int:
    return sum(1 for link in manager.network.graph.links if link.type == LinkType.MAN)


def _wearables(manager) -> int:
    return sum(1 for device in manager.edge_devices if device.cores == 2)


def _peak(tasks) -> tuple[float, int]:
    return Counter(task.time for task in tasks).most_common(1)[0]


@pytest.fixture(scope="module")
def managers():
    """The stock and the custom scenario built on the same seed, neither run."""
    models.TypeGuaranteeGenerator.last_allocation = ()
    _, stock = _build(False)
    _, custom = _build(True)
    return stock, custom


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    """The two result rows of one shrunk launch, plus the folder they were written to."""
    folder = tmp_path_factory.mktemp("custom_models_runs")
    models.AUDIT.clear()
    stock, custom = models.main(devices=DEVICES, duration=SHORT_DURATION, seed=SEED, output=folder)
    return stock, custom, folder, dict(models.AUDIT)


# ------------------------------------------------------------------- the fleet hook

def test_the_default_split_drops_the_rare_device_type():
    assert ComputingNodesGenerator._allocate_devices(SHARES, DEVICES) == [2, 2, 2, 0]
    assert ComputingNodesGenerator._allocate_devices(SHARES, 20) == [8, 6, 6, 0]


def test_the_custom_generator_reserves_the_dropped_type(managers):
    reserved = models.TypeGuaranteeGenerator.last_allocation
    assert reserved == (1, 2, 2, 1)
    assert reserved[-1] == 1
    assert min(reserved) >= 1
    assert sum(reserved) == DEVICES


def test_the_reserved_device_type_is_present_only_in_the_custom_fleet(managers):
    stock, custom = managers
    assert _wearables(stock) == 0
    assert _wearables(custom) == 1
    assert len(stock.edge_devices) == len(custom.edge_devices) == DEVICES


# ------------------------------------------------------------------ the topology hook

def test_the_mesh_adds_exactly_the_missing_directions(managers):
    stock, custom = managers
    assert _man_links(stock) == 8
    assert _man_links(custom) == 12


def test_two_opposite_data_centers_are_one_hop_apart_only_after_the_mesh(managers):
    stock, custom = managers
    origin, opposite = custom.nodes_generator.edge_data_centers[0], custom.nodes_generator.edge_data_centers[2]
    assert len(stock.network.graph.shortest_path(origin, opposite)) == 2
    assert stock.network.graph.path_delay(origin, opposite) == pytest.approx(0.02)
    custom_path = custom.network.graph.shortest_path(origin, opposite)
    assert len(custom_path) == 1
    assert custom.network.graph.path_delay(origin, opposite) == pytest.approx(0.01)
    assert all(link.type == LinkType.MAN for link in custom_path)


# --------------------------------------------------------------------- the workload hook

def test_the_burst_keeps_the_size_of_the_workload(managers):
    stock, custom = managers
    assert len(custom.tasks) == len(stock.tasks) > 0


def test_the_burst_synchronises_the_arrivals(managers):
    stock, custom = managers
    stock_instants = len({task.time for task in stock.tasks})
    custom_instants = len({task.time for task in custom.tasks})
    assert custom_instants < stock_instants
    peak_time, peak = _peak(custom.tasks)
    assert peak_time == 60.0
    assert peak == DEVICES
    assert peak > _peak(stock.tasks)[1]


# ---------------------------------------------------------------------- the audit hook

def test_the_audit_ledger_is_consistent(rows):
    _, custom, _, audit = rows
    assert audit["succeeded"] + audit["failed"] + audit["not_generated"] == audit["generated"]
    assert audit["generated"] == custom[COLUMNS[7]]
    assert audit["succeeded"] == custom[COLUMNS[8]]
    assert audit["failed"] == custom[COLUMNS[10]]
    assert audit["by_reason"] == {"FAILED_DUE_TO_DELAY": audit["failed"]}
    assert audit["not_generated"] == custom[COLUMNS[13]]


def test_the_manager_hooks_are_reached_and_reported(rows):
    _, custom, _, audit = rows
    assert audit["man_usage"] == 0.0
    assert audit["man_transfers"] == 0
    assert custom[COLUMNS[41]] == 0.0  # MAN energy consumption (Wh)


def test_the_printed_lines_report_the_four_hooks(tmp_path, capsys):
    models.main(devices=DEVICES, duration=SHORT_DURATION, seed=SEED, output=tmp_path)
    printed = capsys.readouterr().out
    assert "one device reserved from type" in printed
    assert "Added 4 directed MAN links to complete the full mesh of 4 edge data centers" in printed
    assert "busiest instant: 6 tasks arrive together at t=60 s over 124 generated tasks" in printed
    assert "MAN 0.00 s" in printed
    assert "0 transfers crossed a MAN link" in printed


# ----------------------------------------------------------------- the comparison run

def test_the_custom_models_change_the_scenario(rows):
    stock, custom, _, _ = rows
    assert stock[COLUMNS[7]] == custom[COLUMNS[7]]
    tiers = [COLUMNS[15], COLUMNS[17], COLUMNS[19]]
    assert [stock[column] for column in tiers] != [custom[column] for column in tiers]
    successes = [COLUMNS[16], COLUMNS[18], COLUMNS[20]]
    assert sum(stock[column] for column in successes) == stock[COLUMNS[8]]
    assert sum(custom[column] for column in successes) == custom[COLUMNS[8]]


def test_two_full_csv_rows_were_written(rows):
    _, _, folder, _ = rows
    written = sorted(path for path in folder.rglob("Sequential_simulation.csv"))
    assert len(written) == 2
    for path in written:
        with path.open(newline="", encoding="utf-8") as handle:
            records = list(csv.DictReader(handle))
        assert len(records) == 1
        assert len(records[0]) == len(COLUMNS) == 56
    assert any("stock" in path.parts for path in written)
    assert any("stock" not in path.parts for path in written)
