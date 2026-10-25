"""Command line entry point: ``pureedgesim run --settings <folder>``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .mobility import MobilityModelFactory
from .runner import COLUMNS, Simulation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pureedgesim",
                                     description="Run a PureEdgeSim scenario in Python.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run the scenarios of a settings folder")
    run.add_argument("--settings", default="settings", help="folder holding the five settings files")
    run.add_argument("--output", default=None, help="output folder (default: output_folder property)")
    run.add_argument("--devices", type=int, default=None, help="run only this edge devices count")
    run.add_argument("--architectures", default=None,
                     help="comma separated architectures, overriding the properties file")
    run.add_argument("--algorithms", default=None,
                     help="comma separated orchestration algorithms, overriding the properties file")
    run.add_argument("--seed", type=int, default=None, help="random seed, for reproducible runs")
    run.add_argument("--duration", type=float, default=None, help="simulation duration, in minutes")
    run.add_argument("--parallel", action="store_true", help="run the scenarios in separate processes")

    models = subparsers.add_parser("models", help="list the built-in mobility models")
    models.add_argument("--verbose", action="store_true", help="also show the class behind each name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "models":
        return _print_models(args.verbose)
    return _run(args)


def _print_models(verbose: bool) -> int:
    if verbose:
        for name in sorted(MobilityModelFactory.known_names()):
            print(f"{name:14s} {MobilityModelFactory.known_models()[name].__name__}")
    else:
        print(", ".join(sorted(MobilityModelFactory.known_names())))
    return 0


def _run(args: argparse.Namespace) -> int:
    settings = Path(args.settings)
    simulation = Simulation(settings, args.output)
    simulation.load()
    parameters = simulation.parameters
    if args.architectures:
        parameters.orchestration_architectures = [a.strip() for a in args.architectures.split(",") if a.strip()]
    if args.algorithms:
        parameters.orchestration_algorithms = [a.strip() for a in args.algorithms.split(",") if a.strip()]
    if args.devices:
        parameters.min_number_of_devices = args.devices
        parameters.max_number_of_devices = args.devices
        parameters.devices_increment = 1
    if args.seed is not None:
        parameters.random_seed = args.seed
    if args.duration is not None:
        parameters.simulation_duration = args.duration * 60
    if args.parallel:
        parameters.parallel_simulation = True

    rows = simulation.launch()
    print(f"Ran {len(rows)} scenario(s), results in {simulation.results_folder}")
    for row in rows:
        architecture = f"{row[COLUMNS[0]]:<14}"
        algorithm = f"{row[COLUMNS[1]]:<12}"
        devices = f"{row[COLUMNS[2]]:>6d}"
        print(f"  {architecture} {algorithm} {devices} tasks={row[COLUMNS[7]]:>6d} "
              f"ok={row[COLUMNS[8]]:>6d} avg_delay={row[COLUMNS[4]]} energy={row[COLUMNS[31]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
