"""The scenario sweep: the 51-column result row, reproducibility and the output files."""
from __future__ import annotations

import csv
import re

import pytest
from conftest import SETTINGS, build_manager, run_manager
from pureedgesim import NodeStatus, Randomness, Scenario
from pureedgesim.cli import main
from pureedgesim.network import LinkType
from pureedgesim.runner import (COLUMNS, Simulation, build_scenarios, output_folder, run_scenario, summarize)


def sweep(parameters):
    """Configure the smallest sweep that still produces workload, as ``launch`` does."""
    parameters.orchestration_architectures = ["ALL"]
    parameters.orchestration_algorithms = ["TRADE_OFF"]
    parameters.min_number_of_devices = parameters.max_number_of_devices = 10
    parameters.devices_increment = 1
    parameters.random_seed = 99
    Randomness.set_seed(99)
    return parameters


def test_the_sweep_crosses_architectures_algorithms_and_device_counts(parameters):
    parameters.orchestration_architectures = ["ALL", "CLOUD_ONLY"]
    parameters.orchestration_algorithms = ["TRADE_OFF", "ROUND_ROBIN"]
    parameters.min_number_of_devices = 10
    parameters.max_number_of_devices = 20
    parameters.devices_increment = 10
    assert [(s.orchestration_architecture, s.orchestration_algorithm, s.devices_count)
            for s in build_scenarios(parameters)] == [
                ("ALL", "TRADE_OFF", 10), ("ALL", "TRADE_OFF", 20),
                ("ALL", "ROUND_ROBIN", 10), ("ALL", "ROUND_ROBIN", 20),
                ("CLOUD_ONLY", "TRADE_OFF", 10), ("CLOUD_ONLY", "TRADE_OFF", 20),
                ("CLOUD_ONLY", "ROUND_ROBIN", 10), ("CLOUD_ONLY", "ROUND_ROBIN", 20)]


def test_the_output_folder_is_named_after_the_launch_time():
    assert output_folder("out", "2026-10-25_12-00-00").as_posix() == "out/2026-10-25_12-00-00"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", output_folder("out").name)


def test_a_row_holds_one_value_per_csv_column(parameters, files):
    sweep(parameters)
    row = run_scenario(parameters, files, build_scenarios(parameters)[0], 0)
    assert len(COLUMNS) == 51
    assert list(row) == COLUMNS


def test_the_row_starts_with_the_scenario_it_was_run_for(parameters, files):
    sweep(parameters)
    row = run_scenario(parameters, files, Scenario("MIST_AND_EDGE", "ROUND_ROBIN", 5), 0)
    assert (row[COLUMNS[0]], row[COLUMNS[1]], row[COLUMNS[2]]) == ("MIST_AND_EDGE", "ROUND_ROBIN", 5)


def test_the_counters_in_the_row_are_the_manager_metrics(parameters, files):
    engine, manager = run_manager(parameters, files, "ALL", "TRADE_OFF", devices=10)
    metrics = manager.metrics
    row = summarize(manager)
    assert row[COLUMNS[7]] == metrics.generated_tasks > 0
    assert row[COLUMNS[8]] == metrics.succeeded_tasks
    assert row[COLUMNS[9]] == metrics.not_executed
    assert row[COLUMNS[10]] == metrics.delay_failures
    assert (row[COLUMNS[14]], row[COLUMNS[16]], row[COLUMNS[18]]) == (metrics.cloud_tasks,
                                                                      metrics.edge_tasks, metrics.mist_tasks)
    assert row[COLUMNS[3]] == round(metrics.total_execution_time, 4)
    assert row[COLUMNS[4]] == round(metrics.total_execution_time / metrics.executed_tasks, 4)


def test_the_not_generated_column_counts_the_tasks_of_dead_devices(parameters, files):
    engine, manager = build_manager(parameters, files, "ALL", "TRADE_OFF", devices=10)
    task = manager.tasks[0]
    task.source_device.status = NodeStatus.DEAD
    manager._send_to_orchestrator(task)
    row = summarize(manager)
    assert row[COLUMNS[13]] == manager.metrics.not_generated == 1
    assert row[COLUMNS[11]] == manager.metrics.death_failures == 0


def test_the_network_usage_column_sums_the_three_networks(parameters, files):
    engine, manager = run_manager(parameters, files, "ALL", "TRADE_OFF", devices=10)
    network = manager.network
    row = summarize(manager)
    assert row[COLUMNS[20]] == round(sum(network.network_usage.values()), 4)
    assert row[COLUMNS[20]] == round(network.network_usage[LinkType.LAN]
                                     + network.network_usage[LinkType.MAN]
                                     + network.network_usage[LinkType.WAN], 4)
    assert row[COLUMNS[22]] == round(network.network_usage[LinkType.LAN], 4)
    assert row[COLUMNS[21]] == round(network.network_usage[LinkType.WAN], 4) > 0
    assert row[COLUMNS[23]] == round(network.total_traffic_bits / 8 / 1e6, 4) > 0


def test_the_layer_energies_add_up_to_the_total(parameters, files):
    engine, manager = run_manager(parameters, files, "ALL", "TRADE_OFF", devices=10)
    row = summarize(manager)
    assert row[COLUMNS[31]] == pytest.approx(row[COLUMNS[33]] + row[COLUMNS[35]] + row[COLUMNS[37]], abs=1e-3)
    assert row[COLUMNS[33]] > 0 and row[COLUMNS[35]] > 0 and row[COLUMNS[37]] > 0
    assert row[COLUMNS[38]] == pytest.approx(row[COLUMNS[37]] / len(manager.edge_devices), rel=1e-3)


def test_the_battery_columns_list_one_entry_per_battery_device(parameters, files):
    engine, manager = run_manager(parameters, files, "ALL", "TRADE_OFF", devices=10)
    row = summarize(manager)
    battery = [node for node in manager.edge_devices if node.is_battery_powered()]
    assert len(battery) > 0
    percentages = row[COLUMNS[49]].split("-")
    assert len(percentages) == len(battery)
    assert all(0.0 < float(value) <= 100.0 for value in percentages)
    assert row[COLUMNS[45]] == 0
    assert row[COLUMNS[50]] == ""


def test_a_device_that_dies_is_reported_once_with_its_death_time(parameters, files):
    engine, manager = build_manager(parameters, files, "ALL", "TRADE_OFF", devices=10)
    battery = [node for node in manager.edge_devices if node.is_battery_powered()]
    victim = battery[0]
    # An idle draw that empties the battery after one simulated minute.
    victim.energy_model.idle_consumption = victim.energy_model.battery_capacity * 3600 / 60
    engine.start()
    assert victim.is_dead()
    row = summarize(manager)
    assert row[COLUMNS[45]] == 1
    assert row[COLUMNS[48]] == round(victim.death_time, 4)
    assert row[COLUMNS[50]] == str(round(victim.death_time, 2))
    percentages = row[COLUMNS[49]].split("-")
    assert percentages.count("0") == 1
    assert all(0.0 < float(value) <= 100.0 for value in percentages if value != "0")
    assert float(row[COLUMNS[47]]) <= 100.0


def test_the_same_seed_and_iteration_replay_the_same_row(parameters, files):
    sweep(parameters)
    scenario = build_scenarios(parameters)[0]
    assert run_scenario(parameters, files, scenario, 0) == run_scenario(parameters, files, scenario, 0)


def test_a_different_iteration_gives_a_different_row(parameters, files):
    sweep(parameters)
    scenario = build_scenarios(parameters)[0]
    first = run_scenario(parameters, files, scenario, 0)
    second = run_scenario(parameters, files, scenario, 1)
    assert first != second
    assert first[COLUMNS[3]] != second[COLUMNS[3]]
    assert first[COLUMNS[8]] != second[COLUMNS[8]]


def test_launch_writes_one_row_per_scenario_in_a_timestamped_folder(parameters, files, tmp_path):
    sweep(parameters)
    parameters.orchestration_algorithms = ["TRADE_OFF", "ROUND_ROBIN"]
    parameters.save_log_file = False
    simulation = Simulation(SETTINGS, tmp_path / "results", parameters, files)
    rows = simulation.launch()
    assert len(rows) == 2
    folder = simulation.results_folder
    assert folder.parent == tmp_path / "results"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", folder.name)
    path = folder / "Sequential_simulation.csv"
    assert path.exists() and not (folder / "Parallel_simulation.csv").exists()
    assert (folder / "run.json").is_file()
    assert (folder / "settings" / "edge_devices.xml").read_bytes() == (
        SETTINGS / "edge_devices.xml").read_bytes()
    with path.open(newline="", encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert list(written[0]) == COLUMNS
    assert [line[COLUMNS[1]] for line in written] == ["TRADE_OFF", "ROUND_ROBIN"]
    for line, row in zip(written, rows):
        assert line[COLUMNS[7]] == str(row[COLUMNS[7]])


def test_launch_writes_to_the_folder_from_the_parameters(parameters, files, tmp_path):
    sweep(parameters)
    parameters.output_folder = str(tmp_path / "from-props")
    simulation = Simulation(SETTINGS, None, parameters, files)
    simulation.launch()
    assert (simulation.results_folder / "Sequential_simulation.csv").exists()
    assert simulation.results_folder.parent == tmp_path / "from-props"


def test_launch_saves_a_text_report_per_scenario(parameters, files, tmp_path):
    sweep(parameters)
    parameters.save_log_file = True
    simulation = Simulation(SETTINGS, tmp_path / "results", parameters, files)
    rows = simulation.launch()
    report = simulation.results_folder / "Sequential_simulation.txt"
    text = report.read_text(encoding="utf-8")
    assert report.exists()
    assert text.count("Scenario:") == len(rows)
    assert "Scenario: ALL / TRADE_OFF / 10 devices" in text
    assert f"Generated tasks      : {rows[0][COLUMNS[7]]}" in text


def test_no_text_report_is_written_when_logging_is_off(parameters, files, tmp_path):
    sweep(parameters)
    parameters.save_log_file = False
    simulation = Simulation(SETTINGS, tmp_path / "results", parameters, files)
    simulation.launch()
    assert list(simulation.results_folder.glob("*.txt")) == []


def test_clearing_the_output_folder_drops_the_previous_results(parameters, files, tmp_path):
    sweep(parameters)
    parameters.clear_output_folder = True
    previous = tmp_path / "results" / "stale.csv"
    previous.parent.mkdir(parents=True)
    previous.write_text("old\n", encoding="utf-8")
    simulation = Simulation(SETTINGS, previous.parent, parameters, files)
    simulation.launch()
    assert not previous.exists()
    assert (simulation.results_folder / "Sequential_simulation.csv").exists()


def test_the_parallel_sweep_reuses_the_seed_of_the_main_process(parameters, files, tmp_path):
    """Real worker processes: they get the seed with the parameters, so they replay the same runs."""
    sweep(parameters)
    parameters.orchestration_architectures = ["ALL", "MIST_ONLY"]
    parameters.save_log_file = False
    sequential = Simulation(SETTINGS, tmp_path / "sequential", parameters, files)
    expected = sequential.launch()

    parameters.parallel_simulation = True
    parallel = Simulation(SETTINGS, tmp_path / "parallel", parameters, files)
    rows = parallel.launch()

    assert [row[COLUMNS[0]] for row in rows] == ["ALL", "MIST_ONLY"]
    assert rows == expected
    path = parallel.results_folder / "Parallel_simulation.csv"
    assert path.exists() and not (path.parent / "Sequential_simulation.csv").exists()
    with path.open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 2


def test_the_cli_runs_a_scenario_and_reports_where_the_results_are(tmp_path, capsys):
    code = main(["run", "--settings", str(SETTINGS), "--output", str(tmp_path / "results"),
                 "--devices", "3", "--duration", "2", "--architectures", "CLOUD_ONLY",
                 "--algorithms", "TRADE_OFF", "--seed", "99"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "Ran 1 scenario(s)" in printed
    assert "CLOUD_ONLY" in printed and "TRADE_OFF" in printed
    folders = [path for path in (tmp_path / "results").iterdir() if path.is_dir()]
    assert [path.name for path in folders if (path / "Sequential_simulation.csv").exists()] == \
        [folders[0].name]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", folders[0].name)


def test_the_cli_models_command_lists_the_mobility_models(capsys):
    assert main(["models"]) == 0
    printed = capsys.readouterr().out
    assert "random-waypoint" in printed and "gauss-markov" in printed


def test_the_cli_reports_broken_settings_without_a_traceback(tmp_path, capsys):
    assert main(["run", "--settings", str(tmp_path / "empty"), "--output", str(tmp_path / "results")]) == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "parameters file not found" in captured.err
    assert "Traceback" not in captured.err
