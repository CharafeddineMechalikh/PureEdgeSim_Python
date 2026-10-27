---
description: "The PureEdgeSim for Python manual: installation, architecture, configuration, models, task lifecycle, orchestrators, output metrics, and the Python-to-Java API map."
permalink: /docs/
---
# PureEdgeSim for Python documentation

This is the manual for the Python implementation of PureEdgeSim, a discrete-event simulator for cloud, edge, fog, and mist computing. It is written for researchers who already know the framework, or who arrive here from the Java project, and need to see how each part works in Python.

The Python port is a faithful twin of the Java simulator. It reads the same five settings files, produces the same CSV columns, and follows the same event flow. Where the two differ, this manual says so, and [Python vs Java](python-vs-java.md) lists every gap.

If you want the shortest path to a running simulation, read [Getting started](getting-started.md). If you want the internals first, read [Architecture](architecture.md) and [Task lifecycle](task-lifecycle.md).

## Reading paths

### Path 1: I want to run an experiment this week

1. [Getting started](getting-started.md): install with pip, run the CLI, read the output.
2. [Configuration](configuration.md): the five settings files and every parameter the parser accepts.
3. [Output and metrics](output-and-metrics.md): the 56 CSV columns and the text report.
4. [FAQ](faq.md): why a task failed, why a run is slow, what the Python port does not do yet.

### Path 2: I want to implement a new offloading algorithm

1. [Getting started](getting-started.md).
2. [Task lifecycle](task-lifecycle.md): where decisions happen in the event flow.
3. [Writing orchestrators](orchestrators.md): subclass `Orchestrator`, override `find_computing_node` and `results_returned`.
4. [Architecture](architecture.md): the modules you can plug into.

### Path 3: I came from the Java simulator

1. [Python vs Java](python-vs-java.md): the class-to-module map and the known gaps.
2. [Configuration](configuration.md): the parameter names are identical; the units and defaults match the Java parser.
3. [Simulation models](models.md): the energy, mobility, distribution, and network models, in Python terms.

## Documentation map

| Document | What it answers |
| --- | --- |
| [Getting started](getting-started.md) | How do I install the package and run my first scenario from the CLI or from Python? |
| [Architecture](architecture.md) | What modules exist, how do they depend on one another, and how does the event engine run? |
| [Configuration](configuration.md) | What does every key in `simulation_parameters.properties` and every XML element mean, and what are its units? |
| [Task lifecycle](task-lifecycle.md) | What happens to a task from generation to result, including service graphs, dependencies, and optional subtasks? |
| [Simulation models](models.md) | How are energy, mobility, probability distributions, and network transfers modeled in Python? |
| [Writing orchestrators](orchestrators.md) | How do I implement and plug in my own placement policy? |
| [Output and metrics](output-and-metrics.md) | How do I read the CSV, the console report, and the run metadata? |
| [Python vs Java](python-vs-java.md) | Which Java class maps to which Python module, and what does the port not have yet? |
| [FAQ](faq.md) | Why did my task fail? Why are no charts produced? Can I run in parallel? |
| [Contributing](contributing-guide.md) | How do I run pytest, measure coverage, and match the code style? |

## The one-paragraph mental model

PureEdgeSim is a discrete-event simulator. You describe a scenario in five files: `simulation_parameters.properties`, `applications.xml`, `cloud.xml`, `edge_datacenters.xml`, and `edge_devices.xml`. A scenario is one combination of orchestration architecture, orchestration algorithm, and number of edge devices. The framework pre-generates a list of tasks, feeds them to an event engine, and lets a workload orchestrator decide where each task executes. The task then travels through the network, waits for computing resources, executes, and sends its results back. Every event advances the simulator clock. When the run ends, the framework aggregates delays, failures, CPU use, network traffic, and energy into a CSV row and an optional text report. In parallel mode, results across a settings matrix are pooled into a single `run.json` per output folder.

## What the Python port does and does not do

The core runs on the standard library only, with no third-party dependencies. It supports the discrete-event engine, all three computing tiers, the WAN/MAN/LAN network with Wi-Fi, cellular, and Ethernet links, battery and static/dynamic energy accounting, nine mobility models, sixteen probability distributions, service graphs with dependencies and optional subtasks, and a parallel scenario sweep.

It does not yet have a visualizer (no live or saved charts), a per-event log, a container registry in CACHE mode, or chart output files. Those gaps, and the Java equivalents, are documented in [Python vs Java](python-vs-java.md).

## Conventions used in this manual

- **Simulation time** is the time inside the simulated world, in seconds unless stated otherwise.
- **Wall-clock time** is the real time your computer spends running the simulation.
- **Cloud**, **edge**, and **mist** are the three computing levels: remote data centers, edge data centers, and end devices.
- **Task** and **offloading request** are used interchangeably for a single-application task; a service graph request is a group of tasks that share a `request_id`.
- Code samples assume the package is installed and importable as `from pureedgesim import ...`.
- Configuration examples assume the settings folder `examples/default_settings/` and a working directory at the repository root.

## Other sources

- [Project README](../): installation, features, and citation.
- [Examples folder](https://github.com/CharafeddineMechalikh/PureEdgeSim_Python/tree/main/examples): runnable scenarios and settings folders.
- [Java PureEdgeSim manual](https://charafeddinemechalikh.github.io/PureEdgeSim/docs/): the reference this port mirrors.
- [Issue tracker](https://github.com/CharafeddineMechalikh/PureEdgeSim_Python/issues): questions and bug reports.
