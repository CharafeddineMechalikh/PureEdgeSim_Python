"""Replaying a recorded production workload instead of drawing one.

    PYTHONPATH=src python examples/trace_replay/trace_replay.py

Port of the Java `Example25`. The scenario replays one hour of a published
production trace, the code completion sample of the Azure LLM inference dataset
released with the Splitwise paper (`trace/azure_llm_code_1h.csv`, attributed in
`trace/NOTICE.md`). `TraceTaskGenerator` reads that file and turns every recorded
invocation into exactly one request: its arrival second, its prompt and completion
sizes, its compute length and its latency budget all come from the trace, so the
burstiness of real traffic reaches the orchestrator untouched. The 8819 requests are
handed to the 50 devices in turn, and the single edge data center is sized to the
mean demand of the hour, so what breaks requests is the shape of the traffic rather
than its average.

Run the same scenario with the requests drawn at random instead, at the mean rate
and mean sizes of the trace:

    PYTHONPATH=src python examples/trace_replay/trace_replay.py
    PYTHONPATH=src python examples/trace_replay/trace_replay.py --synthetic

The first replays the recorded hour, the second feeds the same server with poisson
arrivals. Compare the two summary lines: the mean load is almost identical, the
recorded hour is the one that queues.

The token-to-simulator mapping is a set of knobs rather than a hard-coded guess, and
each one can be changed on the command line, as `--decode-budget=0.5`:
`--bytes-per-token`, `--mi-per-context-token`, `--mi-per-generated-token`,
`--ttft-budget` and `--decode-budget`. An optional `devices duration seed` triple
shrinks the scenario, which is what the test suite uses.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pureedgesim import COLUMNS, DefaultTaskGenerator, Simulation, Task, load_parameters, load_settings

EXAMPLE_DIR = Path(__file__).resolve().parent
SETTINGS = EXAMPLE_DIR / "settings"
OUTPUT = EXAMPLE_DIR / "output"
TRACE = EXAMPLE_DIR / "trace" / "azure_llm_code_1h.csv"

# Index of the only application of this scenario in applications.xml.
APPLICATION = 0
# One second of initialization, so the first request is not generated before the
# deployment of the simulation is finished.
INITIALIZATION = 1

BYTES_PER_TOKEN = 4.0
MI_PER_CONTEXT_TOKEN = 12.0
MI_PER_GENERATED_TOKEN = 2000.0
TTFT_BUDGET = 2.0
DECODE_BUDGET = 0.1

# The command line name of each mapping knob, mapped to the run keyword it sets.
KNOBS = {"--bytes-per-token": "bytes_per_token", "--mi-per-context-token": "mi_per_context_token",
         "--mi-per-generated-token": "mi_per_generated_token", "--ttft-budget": "ttft_budget",
         "--decode-budget": "decode_budget"}


class TraceTaskGenerator(DefaultTaskGenerator):
    """Turns every recorded invocation of the trace into one scheduled request."""

    def __init__(self, manager, bytes_per_token: float = BYTES_PER_TOKEN,
                 mi_per_context_token: float = MI_PER_CONTEXT_TOKEN,
                 mi_per_generated_token: float = MI_PER_GENERATED_TOKEN,
                 ttft_budget: float = TTFT_BUDGET, decode_budget: float = DECODE_BUDGET,
                 trace: Path = TRACE) -> None:
        super().__init__(manager)
        self.bytes_per_token = bytes_per_token
        self.mi_per_context_token = mi_per_context_token
        self.mi_per_generated_token = mi_per_generated_token
        self.ttft_budget = ttft_budget
        self.decode_budget = decode_budget
        self.trace = trace
        self.dropped = 0

    def generate(self) -> list[Task]:
        """Reads the trace and returns one task per recorded invocation, in arrival order.

        Invocations that fall after the end of the simulated period are dropped and
        counted, so shortening `simulation_time` truncates the replay instead of
        failing it.
        """
        devices = [node for node in self.manager.edge_devices if node.generates_tasks and node.is_alive()]
        if not devices:
            raise ValueError(f"no edge device generates tasks, so the trace of {self.trace} has nowhere to go")

        application = self.manager.applications[APPLICATION]
        duration = int(self.manager.parameters.simulation_duration)
        tasks: list[Task] = []
        identifier = 1
        self.request_counter = 0
        self.dropped = 0

        for line, fields in enumerate(self._read_rows(), start=2):
            arrival_ms, context_tokens, generated_tokens = (int(value) for value in fields[:3])
            # The clock ticks in whole seconds, so each recorded offset is rounded
            # to its second, the way the Java example rounds it.
            time = INITIALIZATION + (arrival_ms + 500) // 1000
            if time > duration:
                self.dropped += 1
                continue
            tasks.append(self._create_recorded_task(application, devices[(identifier - 1) % len(devices)], time,
                                                    context_tokens, generated_tokens, identifier))
            identifier += 1

        print(f"{type(self).__name__} - Trace replay: {len(tasks)} requests scheduled between "
              f"{INITIALIZATION} and {duration} s, {self.dropped} dropped because they arrive after the end "
              f"of the run.")
        tasks.sort(key=lambda task: task.time)
        return tasks

    def _create_recorded_task(self, application, device, time: int, context_tokens: int,
                              generated_tokens: int, identifier: int) -> Task:
        """Builds the task of one recorded invocation.

        The sizes, the length and the deadline come from the trace; the container
        size and the application type come from applications.xml, which is what a
        trace of invocations cannot say.
        """
        latency = self.ttft_budget + generated_tokens * self.decode_budget
        self.request_counter += 1
        task = Task(
            id=identifier,
            type=application.type,
            application_id=APPLICATION,
            length=context_tokens * self.mi_per_context_token + generated_tokens * self.mi_per_generated_token,
            container_size=application.container_size.sample(),
            request_size=round(context_tokens * self.bytes_per_token * 8),
            result_size=round(generated_tokens * self.bytes_per_token * 8),
            max_latency=latency,
            time=time,
            source_device=device,
            registry=self.manager.registry,
        )
        task.set_request(self.request_counter, 1, time, time + latency)
        return task

    def _read_rows(self):
        """Yields the three fields of every data line of the trace, header excluded."""
        try:
            lines = self.trace.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ValueError(f"cannot read the trace file {self.trace}") from error
        for number, line in enumerate(lines[1:], start=2):
            fields = line.split(",")
            if len(fields) < 3:
                raise ValueError(f"malformed trace line {number} of {self.trace}")
            yield fields


def run(synthetic: bool = False, devices: int | None = None, duration: float | None = None,
        seed: int | None = None, output: str | Path = OUTPUT, bytes_per_token: float = BYTES_PER_TOKEN,
        mi_per_context_token: float = MI_PER_CONTEXT_TOKEN, mi_per_generated_token: float = MI_PER_GENERATED_TOKEN,
        ttft_budget: float = TTFT_BUDGET, decode_budget: float = DECODE_BUDGET) -> dict:
    """Runs the scenario in one of its two modes and prints the metrics of the run."""

    class _Generator(TraceTaskGenerator):
        def __init__(self, manager) -> None:
            super().__init__(manager, bytes_per_token=bytes_per_token, mi_per_context_token=mi_per_context_token,
                             mi_per_generated_token=mi_per_generated_token, ttft_budget=ttft_budget,
                             decode_budget=decode_budget)

    _Generator.__name__ = "TraceTaskGenerator"

    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    if devices is not None:
        parameters.min_number_of_devices = parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration is not None:
        parameters.simulation_duration = duration
    if seed is not None:
        parameters.random_seed = seed

    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    if not synthetic:
        simulation.set_custom_task_generator(_Generator)
    rows = simulation.launch()
    if not rows:
        raise ValueError(f"{SETTINGS}: the settings declare no scenario, nothing to run")

    row = rows[-1]
    label = "synthetic" if synthetic else "recorded"
    print(f"{label:<10} tasks={row[COLUMNS[7]]:>6} ok={row[COLUMNS[8]]:>6} "
          f"requests_ok={row[COLUMNS[54]]:>5}/{row[COLUMNS[53]]:<5} "
          f"compute={row[COLUMNS[3]]} s waiting={row[COLUMNS[5]]} s "
          f"avg_wait={row[COLUMNS[6]]} s avg_makespan={row[COLUMNS[55]]} s "
          f"edge_cpu={row[COLUMNS[30]]} % traffic={row[COLUMNS[24]]} MB energy={row[COLUMNS[32]]} Wh")
    return row


def main(argv: list[str] | None = None) -> dict:
    """Starts the example; the flags are read in the order documented above."""
    argv = list(sys.argv[1:] if argv is None else argv)
    synthetic = "--synthetic" in argv
    overrides: dict[str, float] = {}
    values = []
    for argument in argv:
        name, separator, raw = argument.partition("=")
        if separator and name in KNOBS:
            overrides[KNOBS[name]] = float(raw)
        elif argument.startswith("--"):
            raise ValueError(f"unknown option {argument}; the tuning knobs are {', '.join(sorted(KNOBS))}")
        else:
            values.append(argument)
    return run(synthetic=synthetic,
               devices=int(values[0]) if len(values) > 0 else None,
               duration=float(values[1]) if len(values) > 1 else None,
               seed=int(values[2]) if len(values) > 2 else None, **overrides)


if __name__ == "__main__":
    main()
