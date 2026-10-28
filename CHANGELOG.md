# Changelog

## Unreleased

*   New `examples/trace_replay`, the Python mirror of Java `Example25`.
    `TraceTaskGenerator` reads `trace/azure_llm_code_1h.csv`, the 8819 LLM
    inference requests of the Azure dataset published with the Splitwise paper
    (CC-BY-4.0, attributed in `trace/NOTICE.md`), and turns each line into one
    request whose size, length and deadline come from the recorded prompt and
    completion token counts. The same scenario runs with poisson arrivals at the
    mean rate and mean sizes of the trace when `--synthetic` is passed. Both modes
    use one 8-core edge server sized to the mean demand of the hour: the recorded
    trace spends 120213 s in queues and 36.06 percent of its requests meet their
    deadline, against 231 s and 100 percent for random arrivals, at 42.42 and
    42.76 percent CPU utilization. The token-to-instruction mapping is
    configurable through the `--bytes-per-token`, `--mi-per-context-token`,
    `--mi-per-generated-token`, `--ttft-budget` and `--decode-budget` flags. The
    replay draws no random value, so its counters are the Java ones: the same
    8819 requests and the same 3180 successes.
*   The static network model now finishes a transfer at its exact completion time,
    the way the Java `NetworkLink` does, instead of clearing it at the next
    `network_update_interval` poll. A one-hop transfer therefore advances the clock
    by its propagation delay and not by up to a whole second, and every measured
    latency in the port moves with it. The realistic model, which polls the link,
    is unchanged.
*   The last hop of the shared WAN, from the metro router to the cloud, is now an
    `IGNORE` link, as in Java: it delays the tasks that cross it and moves no usage,
    traffic or energy counter, because the device link that entered the WAN already
    booked the same bits. Only the edge data center named `dc1` hangs on the WAN
    router; the other data centers keep their MAN ring and reach the cloud through
    it. Reported WAN usage and energy drop accordingly: on the ant colony scenario,
    which uses the shared WAN, the WAN usage column goes from 5914 s to 650 s.
*   Three result column headers now carry the Java wording: `Tasks successfully
    executed (Cloud)`, `(Edge)` and `(Mist)`, replacing `Successful tasks executed`.
    The positions and the values do not change.
*   An example README refresh followed: all 26 example runs were re-measured with
    the corrected model, and every committed console block and analytical sentence
    now quotes the 2026-10-28 numbers.
*   The test badge in the README is now the real coverage number: the workflow
    writes a shields endpoint JSON from the pytest coverage report and commits it,
    and the suite gates at 95 percent.

## Version 6.0.0 Changelog (October 27th 2026)

*   The version number follows the Java simulator. Both now release 6.0, because
    the Python package covers the same features, the same settings files, and the
    same 56 result columns.
*   An application can declare a service graph: a request generates several
    subtasks linked by dependencies, declared as `<subtask>` elements in
    `applications.xml`. A subtask is submitted only after the subtasks it depends
    on have returned their results, and a failure propagates to the whole subtree.
*   Service graphs model the data and the deadline of a real pipeline. The result
    size of each parent is added to the request size of its children, so the
    payload of a dependency travels over the network. The application `latency`
    is drawn once per request and shared by every subtask as an end-to-end
    deadline.
*   A subtask can be declared `optional="true"`. When one of its dependencies
    fails it is skipped instead of failing the request, its dependents are
    released without the missing input, and it is counted in its own column.
*   The report measures requests, not only tasks: the four columns generated,
    successful, failed, and average end-to-end makespan are appended at the end
    of the row, so the position of the existing columns does not change. The text
    report gains a `Requests` block.
*   `Simulation` exposes eight injection points, one per pluggable class:
    `set_custom_mobility_model`, `set_custom_orchestrator`,
    `set_custom_network_model`, `set_custom_computing_nodes_generator`,
    `set_custom_topology_creator`, `set_custom_task_generator`,
    `set_custom_computing_node` and `set_custom_simulation_manager`. A scenario
    can replace any of them with a subclass instead of editing the library.
*   The container registry is modelled: with `enable_registry=true` a task pulls
    its container from the registry before it executes, and the download travels
    over the network like any other transfer.
*   New examples cover the policies published with the Java simulator: tabular
    Q-learning, its mist-only and edge-orchestrated variants, a softmax policy,
    multi-objective and context-aware reinforcement placement, ant colony,
    deadline-aware priority placement, multi-access MEC, a three-layer fog,
    device self-clustering, storage-aware container caching, cooperative edge
    data centers, dynamic service-graph repartitioning, the extension points of
    `Simulation`, the four models that assemble a scenario (nodes generator,
    topology creator, task generator and simulation manager), and a scenario grid
    swept once sequentially and once in worker processes. Each one is a folder
    with its script, its settings, and a README that states what it shows, what to
    look for, and the measured result.
*   Every example folder runs from the repository root with
    `python examples/<name>/<name>.py` and writes its results under `output/`.
*   A manual for the Python package is published at
    `https://charafeddinemechalikh.github.io/PureEdgeSim_Python/docs/`, with the
    task lifecycle, the orchestrator guide, the models reference, the output and
    metrics reference, and a page that lists what differs from the Java version.
*   `pureedgesim models --verbose` prints the class behind each mobility model
    name, so the names accepted in `simulation_parameters.properties` can be
    checked without reading the source.

## Version 0.3.0 Changelog (October 25th 2026)

*   Each result folder carries a `run.properties` file with the version, the
    command, the seed, and the elapsed time of the run, and a copy of the
    settings that produced it, so a CSV can be traced back to its scenario.
*   A settings error names the file, the property, and the value read, and
    suggests the closest valid one. A misspelled boolean is rejected instead of
    being read as false, and an unknown property raises a warning rather than
    being ignored.

## Version 0.2.0 Changelog (October 25th 2026)

*   The energy of a transfer follows the direction of the link, matching the Java
    accounting, so a download and an upload of the same payload are not charged
    the same when the two rates differ.
*   Network usage per link is reported for the link that carries the traffic, and
    the access uplink and downlink are kept apart.
*   Devices that die from battery drain are counted as they die instead of being
    scanned at the end of the run, and the devices generated per type are
    allocated without truncation or a last-type fill.
*   Tasks that are never generated because their device died are counted.

## Version 0.1.0 Changelog (October 25th 2026)

*   Initial release of PureEdgeSim for Python, a port of the Java simulator with
    no third-party dependency: a discrete-event engine, the settings files and
    XML scenario format, mobility models and probability distributions, the cloud,
    edge, fog, and mist tiers, the placement algorithms, the energy model, and the
    same text and CSV report.
*   `pip install -e .` installs the `pureedgesim` package and its command-line
    entry point, `pureedgesim run --settings <folder>`.
