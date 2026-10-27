---
description: "How to contribute to PureEdgeSim for Python: run the tests, measure coverage, match the code style, and build the documentation site."
---
# Contributing

The repository is a standard `src`-layout Python package. The package is at `src/pureedgesim/`, the tests at `tests/`, and the runnable scenarios at `examples/`. There are no runtime dependencies; the only extra you need for development is `pytest`.

## Set up a development environment

```bash
git clone https://github.com/CharafeddineMechalikh/PureEdgeSim_Python.git
cd PureEdgeSim_Python
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[test]"
```

`pip install -e ".[test]"` puts `src/` on the path (the editable install) and adds `pytest`. `pyproject.toml` sets `pythonpath = ["src", "."]` for pytest, so the tests import `pureedgesim` even without an editable install.

## Run the tests

From the repository root:

```bash
pytest
```

`[tool.pytest.ini_options]` points `testpaths` at `tests/` and runs with `-q`. The suite covers the engine, nodes, network, tasks, orchestrator, manager, runner, config, parameters, distribution, mobility, metadata, and partitioning, plus the partitioning examples.

Run one file, or one test, while iterating:

```bash
pytest tests/test_tasks.py
pytest tests/test_tasks.py::test_a_service_graph_instantiates_one_task_per_subtask
```

The shared setup lives in `tests/conftest.py`. The `parameters` and `files` fixtures load `examples/default_settings/` and shorten the run (120 seconds, three devices, a fixed seed) so a test is fast and deterministic. `build_manager` and `run_manager` construct a real `SimulationManager` without going through the runner, which is the pattern to follow for unit tests of the lifecycle.

## Coverage

`pytest-cov` comes with the `test` extra, so the development install above already provides it:

```bash
pytest --cov=pureedgesim --cov-report=term-missing
```

The CI (`.github/workflows/tests.yml`) installs `.[test]`, runs plain `pytest`, and then runs a second job that fails below 95 percent coverage. Aim to add a test alongside every behavioral change, especially for new distributions, mobility models, orchestrator logic, or CSV columns.

## Continuous integration

Every push to `main` and every pull request runs `pytest` on Python 3.10, 3.11, 3.12, and 3.13 (the versions the package declares support for), then measures coverage on 3.12 and fails the build under 95 percent. Keep code compatible with the oldest, 3.10; the codebase already uses `X | None` unions and `list[str]` generics under `from __future__ import annotations`.

## Code style

The source is consistent and easy to match. Follow what is already there:

- Start every module with a one-line docstring naming the Java counterpart it replaces (for example, `"""Discrete-event engine, the counterpart of the simulationengine package."""`).
- Put `from __future__ import annotations` at the top so type hints can use modern syntax.
- Use `@dataclass` for plain value objects (`Task`, `Application`, `Subtask`, `DatacenterSpec`, `DeviceSpec`, `SimulationParameters`, `Event`) and `Enum` for closed sets (`NodeType`, `NodeStatus`, `EventType`, `TaskStatus`, `LinkType`, `LinkTechnology`).
- Keep everything on the standard library. Do not add third-party imports to `src/pureedgesim/`.
- Raise `ValueError` for configuration problems, and name the file and the property or element in the message (the properties and XML parsers do this throughout). Raise `FileNotFoundError` when a required file is missing.
- Errors in the XML parsers quote the application, subtask, and attribute at fault; reuse the existing helper messages (`_subtask_error`) rather than inventing new phrasings.
- Match the import grouping already in use: standard library, then relative modules, wrapped to a readable width.

The package has no linter or formatter pinned in `pyproject.toml`, so consistency with the surrounding code is the bar. Keep lines near the existing length (roughly 110 columns) and prefer explicit, readable control flow.

## Conventions that must not drift

Several choices are load-bearing for correctness and for CSV compatibility with Java; if you change them, update [Output and metrics](output-and-metrics.md) and [Python vs Java](python-vs-java.md) in the same change.

- The `COLUMNS` list in `runner.py` is the exact CSV header, in order. Adding a metric means appending a name there and setting the matching key in `summarize`.
- Units: bandwidth properties are Mbps, sizes are KB in XML (converted to bits by the parser), `simulation_time` is minutes in the properties file but `simulation_duration` is seconds in Python.
- Energy conversions go through `NANOJOULES_TO_WATT_HOURS` and `CELLULAR_DOWNLINK_FACTOR`; do not inline the constants.
- The event engine breaks time ties by insertion serial, which is what makes a seeded run deterministic. Do not change `FutureQueue` ordering casually.

## The documentation site

The manual in `docs/` is published with GitHub Pages using the Jekyll Cayman theme. The root `_config.yml` sets the theme, title, and description, and enables `jekyll-relative-links` and `jekyll-sitemap`. The `_includes/head-custom.html` partial renders fenced ```` ```mermaid ```` blocks and builds the fixed documentation sidebar on the client, only for pages under `/docs/`. When you add a manual page, add its slug and label to the `pages` array in that file so it appears in the sidebar. Write plain markdown, keep cross-links to the Java manual as absolute URLs, and link internal pages by relative `.md` name.

## Making a change

1. Branch from `main`.
2. Add or update a test in `tests/` for the behavior.
3. Run `pytest` locally and confirm it is green on at least one supported version.
4. Update the relevant manual page if the change is observable (a new parameter, a new column, a new model).
5. Open a pull request; CI runs the suite across 3.10 to 3.13.

## Cross-links

- The Java contribution and build guide: [Java Contributing](https://charafeddinemechalikh.github.io/PureEdgeSim/docs/contributing-guide.html).
- What the tests exercise, in module terms: [Architecture](architecture.md).
