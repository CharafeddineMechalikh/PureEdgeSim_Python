"""Probability distributions and mobility models, configured from Python.

    python examples/distributions_and_mobility.py

The first run keeps the plain numbers of the settings folder: every task of an
application has the same length, the same sizes and the same arrival pattern, and
the devices stand still. The second run replaces those constants by distributions,
and lets the devices move with the Gauss-Markov model, so the workload and the
radio coverage change from one task to the next.
"""
from __future__ import annotations

from pathlib import Path

from pureedgesim import (COLUMNS, ExponentialDistribution, LogNormalDistribution,
                       NormalDistribution, Randomness, Simulation, SimulationParameters,
                       WeibullDistribution, load_parameters, load_settings)

SETTINGS = Path(__file__).resolve().parent / "default_settings"


def base_parameters() -> SimulationParameters:
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    parameters.simulation_duration = 300.0
    parameters.min_number_of_devices = parameters.max_number_of_devices = 20
    parameters.devices_increment = 1
    parameters.orchestration_architectures = ["ALL"]
    parameters.orchestration_algorithms = ["TRADE_OFF"]
    parameters.random_seed = 7
    parameters.save_log_file = False
    return parameters


def run(label: str, files) -> dict:
    simulation = Simulation(SETTINGS, "output/examples", base_parameters(), files)
    row = simulation.launch()[0]
    print(f"{label:<22} tasks={row[COLUMNS[7]]:>5} ok={row[COLUMNS[8]]:>5} "
          f"delay={row[COLUMNS[4]]:<8} failed(delay)={row[COLUMNS[10]]:>4} "
          f"failed(mobility)={row[COLUMNS[12]]:>4} energy={row[COLUMNS[31]]}")
    return row


def main() -> None:
    Randomness.set_seed(7)
    Randomness.begin_scenario(0)
    plain = load_settings(SETTINGS)
    heavy = plain.applications[2]
    print(f"{heavy.name}: every task draws {heavy.task_length.sample():.0f} MI, "
          f"{heavy.request_size.sample() / 8000:.0f} KB, "
          f"gaps of {ExponentialDistribution(60 / heavy.rate.mean()).sample():.1f} s")
    print("draws from the lognormal task length:",
          ", ".join(f"{LogNormalDistribution(30000, 9000).sample():.0f}" for _ in range(6)))

    run("constants, static", plain)

    distributed = load_settings(SETTINGS)
    for app in distributed.applications:
        mean = app.task_length.mean()
        app.task_length = LogNormalDistribution(mean, mean / 3)
        app.request_size = WeibullDistribution(1.5, app.request_size.mean() / 0.9)
        app.arrival_distribution = ExponentialDistribution(60 / app.rate.mean())
    for spec in distributed.devices:
        spec.mobile = True
        spec.mobility_model = "gauss-markov"
        spec.mobility_options = {"alpha": "0.8", "std": "15", "speed_std": "0.4"}
        spec.speed = NormalDistribution(2.0, 0.5).bounded(0.0, 5.0)
    run("distributions, mobile", distributed)


if __name__ == "__main__":
    main()
