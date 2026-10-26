"""The properties reader and the four XML scenario files."""
from __future__ import annotations

from pathlib import Path

import pytest

from pureedgesim import load_parameters, load_settings
from pureedgesim.parameters import SimulationParameters, validate


CLOUD_XML = """<?xml version="1.0"?>
<cloud_data_centers>
	<datacenter>
		<idleConsumption>0</idleConsumption>
		<maxConsumption>150</maxConsumption>
		<cores>10</cores><mips>30000</mips><ram>100000</ram><storage>10000000</storage>
	</datacenter>
</cloud_data_centers>
"""

EDGE_XML = """<?xml version="1.0"?>
<edge_datacenters>
	<datacenter name="dc1"><periphery>true</periphery><idleConsumption>50</idleConsumption>
		<maxConsumption>200</maxConsumption><cores>5</cores><mips>10000</mips><ram>5000</ram>
		<storage>50000</storage><location><x_pos>30</x_pos><y_pos>30</y_pos></location></datacenter>
	<datacenter name="dc2"><periphery>true</periphery><idleConsumption>50</idleConsumption>
		<maxConsumption>200</maxConsumption><cores>5</cores><mips>10000</mips><ram>5000</ram>
		<storage>50000</storage><location><x_pos>170</x_pos><y_pos>170</y_pos></location></datacenter>
	<network_links><link><from>dc1</from><to>dc2</to></link></network_links>
</edge_datacenters>
"""

DEVICE_XML = """<?xml version="1.0"?>
<edge_devices>
	<device><mobility model="random-walk">true</mobility><connectivity>wifi</connectivity>
		<speed>2</speed><percentage>60</percentage><battery>true</battery>
		<batteryCapacity>20</batteryCapacity><initialBatteryLevel>90</initialBatteryLevel>
		<idleConsumption>1</idleConsumption><maxConsumption>5</maxConsumption>
		<cores>2</cores><mips>2000</mips><ram>2000</ram><storage>10000</storage></device>
	<device><mobility>false</mobility><connectivity>cellular</connectivity>
		<speed>0</speed><percentage>40</percentage><battery>false</battery>
		<idleConsumption>1</idleConsumption><maxConsumption>5</maxConsumption>
		<cores>2</cores><mips>2000</mips><ram>2000</ram><storage>10000</storage></device>
</edge_devices>
"""

APPLICATION_XML = """<?xml version="1.0"?>
<applications>
	<application name="A"><type>Real-time</type><rate distribution="poisson" mean="10"/>
		<usage_percentage>50</usage_percentage><latency>0.5</latency>
		<arrival>uniform</arrival>
		<container_size>100</container_size><request_size>10</request_size>
		<results_size>20</results_size><task_length>2000</task_length></application>
	<application name="B"><type>Offloaded</type><rate>5</rate><usage_percentage>50</usage_percentage>
		<latency>10</latency><container_size>200</container_size><request_size>30</request_size>
		<results_size>40</results_size><task_length>5000</task_length></application>
</applications>
"""

PROPERTIES = """
simulation_time=5
update_interval=2
batch_size=50
random_seed=42
length=300
width=400
edge_devices_range=15
edge_datacenters_coverage=120
wan_bandwidth=10
wan_latency=0.1
wan_nanojoules_per_bit=50
wifi_bandwidth=1300
orchestration_architectures=ALL,EDGE_AND_CLOUD
orchestration_algorithms=TRADE_OFF,ROUND_ROBIN
enable_registry=true
registry_mode=CACHE
output_folder=my_output
clear_output_folder=true
parallel_simulation=false
"""


@pytest.fixture
def scenario_folder(tmp_path: Path) -> Path:
    (tmp_path / "simulation_parameters.properties").write_text(PROPERTIES, encoding="utf-8")
    (tmp_path / "cloud.xml").write_text(CLOUD_XML, encoding="utf-8")
    (tmp_path / "edge_datacenters.xml").write_text(EDGE_XML, encoding="utf-8")
    (tmp_path / "edge_devices.xml").write_text(DEVICE_XML, encoding="utf-8")
    (tmp_path / "applications.xml").write_text(APPLICATION_XML, encoding="utf-8")
    return tmp_path


def test_properties_are_converted_to_si_units(scenario_folder):
    values = load_parameters(scenario_folder / "simulation_parameters.properties")
    assert values.simulation_duration == 300.0
    assert values.update_interval == 2.0
    assert values.batch_size == 50
    assert values.random_seed == 42
    assert (values.simulation_map_width, values.simulation_map_length) == (400.0, 300.0)
    assert values.wan_bandwidth == 10e6
    assert values.wan_energy_per_bit == pytest.approx(50 * 2.7777777777778e-13)
    assert values.orchestration_architectures == ["ALL", "EDGE_AND_CLOUD"]
    assert values.orchestration_algorithms == ["TRADE_OFF", "ROUND_ROBIN"]
    assert values.output_folder == "my_output"
    assert values.clear_output_folder and values.enable_registry
    assert values.registry_mode == "CACHE"


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="parameters file not found"):
        load_parameters(tmp_path / "nope.properties")


def test_comments_and_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "p.properties"
    path.write_text("# a comment\n\n   \nsimulation_time=2\n", encoding="utf-8")
    assert load_parameters(path).simulation_duration == 120.0


def test_a_non_numeric_parameter_names_the_key(tmp_path):
    path = tmp_path / "p.properties"
    path.write_text("simulation_time=ten\n", encoding="utf-8")
    with pytest.raises(ValueError, match='simulation_time" must be a number'):
        load_parameters(path)


def test_a_non_numeric_seed_is_rejected(tmp_path):
    path = tmp_path / "p.properties"
    path.write_text("random_seed=abc\n", encoding="utf-8")
    with pytest.raises(ValueError, match="random_seed"):
        load_parameters(path)


@pytest.mark.parametrize("line,message", [
    ("simulation_time=0", "simulation_time must be > 0"),
    ("update_interval=0.001", "update_interval must be >= 0.01"),
    ("min_number_of_edge_devices=0", "min_number_of_edge_devices must be > 0"),
    ("edge_device_counter_size=0", "edge_device_counter_size must be > 0"),
    ("edge_datacenters_coverage=0", "edge_datacenters_coverage must be > 0"),
    ("network_update_interval=0.0001", "network_update_interval must be >= 0.001"),
    ("charts_update_interval=90", "charts_update_interval must be between"),
    ("registry_mode=WEIRD", "registry_mode"),
])
def test_validation_errors_name_the_parameter(tmp_path, line, message):
    path = tmp_path / "p.properties"
    path.write_text("simulation_time=10\n" + line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_parameters(path)


def test_an_unknown_architecture_is_rejected(tmp_path):
    path = tmp_path / "p.properties"
    path.write_text("simulation_time=10\norchestration_architectures=MIST_AND_SKY\n", encoding="utf-8")
    with pytest.raises(ValueError, match='unknown architecture "MIST_AND_SKY"'):
        load_parameters(path)


def test_a_misspelled_boolean_is_rejected_with_a_suggestion(tmp_path):
    path = tmp_path / "p.properties"
    path.write_text("simulation_time=10\nparallel_simulation=ture\n", encoding="utf-8")
    with pytest.raises(ValueError, match='parameter "parallel_simulation" must be "true" or "false", found "ture"'):
        load_parameters(path)
    with pytest.raises(ValueError, match='did you mean "true"'):
        load_parameters(path)


def test_an_unknown_property_is_reported_without_stopping(tmp_path, capsys):
    path = tmp_path / "p.properties"
    path.write_text("simulation_time=10\nwan_bandwidht=20\n", encoding="utf-8")
    assert load_parameters(path).simulation_duration == 600.0
    printed = capsys.readouterr().err
    assert 'unknown property "wan_bandwidht"' in printed
    assert 'did you mean "wan_bandwidth"' in printed


def test_an_unknown_property_without_a_close_match_is_just_reported(tmp_path, capsys):
    path = tmp_path / "p.properties"
    path.write_text("simulation_time=10\nmy_note=hello\n", encoding="utf-8")
    assert load_parameters(path).simulation_duration == 600.0
    printed = capsys.readouterr().err
    assert 'unknown property "my_note"' in printed
    assert "did you mean" not in printed


def test_shipped_settings_hold_no_unknown_property(settings_folder, capsys):
    load_parameters(settings_folder / "simulation_parameters.properties")
    assert "unknown property" not in capsys.readouterr().err


def test_validate_accepts_the_dataclass_defaults():
    validate(SimulationParameters(), Path("defaults"))


def test_settings_folder_lists_every_file(tmp_path):
    (tmp_path / "cloud.xml").write_text(CLOUD_XML, encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing settings file"):
        load_settings(tmp_path)


def test_scenario_files_are_parsed(scenario_folder):
    files = load_settings(scenario_folder)
    assert len(files.cloud) == 1 and len(files.edge_datacenters) == 2
    assert files.man_links == [("dc1", "dc2")]
    assert [device.connectivity for device in files.devices] == ["wifi", "cellular"]
    assert files.devices[0].mobility_model == "random-walk"
    assert files.devices[0].battery and not files.devices[1].battery
    assert files.get_edge_count() == 2


def test_application_sizes_are_scaled_to_bits(scenario_folder):
    files = load_settings(scenario_folder)
    first = files.applications[0]
    assert first.container_size.mean() == 100 * 8000
    assert first.request_size.mean() == 10 * 8000
    assert first.results_size.mean() == 20 * 8000
    assert first.task_length.mean() == 2000
    assert first.arrival_distribution.mean() == 6.0
    assert first.rate.mean() == 10


def test_device_percentages_must_add_up(tmp_path):
    folder = tmp_path
    (folder / "simulation_parameters.properties").write_text(PROPERTIES, encoding="utf-8")
    (folder / "cloud.xml").write_text(CLOUD_XML, encoding="utf-8")
    (folder / "edge_datacenters.xml").write_text(EDGE_XML, encoding="utf-8")
    (folder / "applications.xml").write_text(APPLICATION_XML, encoding="utf-8")
    (folder / "edge_devices.xml").write_text(
        DEVICE_XML.replace("<percentage>60</percentage>", "<percentage>60</percentage>"
                                                          "<percentage2>1</percentage2>")
        .replace("<percentage>40</percentage>", "<percentage>30</percentage>"), encoding="utf-8")
    with pytest.raises(ValueError, match="must add up to 100"):
        load_settings(folder)


def test_unknown_connectivity_is_rejected(tmp_path):
    (tmp_path / "simulation_parameters.properties").write_text(PROPERTIES, encoding="utf-8")
    (tmp_path / "cloud.xml").write_text(CLOUD_XML, encoding="utf-8")
    (tmp_path / "edge_datacenters.xml").write_text(EDGE_XML, encoding="utf-8")
    (tmp_path / "applications.xml").write_text(APPLICATION_XML, encoding="utf-8")
    (tmp_path / "edge_devices.xml").write_text(DEVICE_XML.replace("cellular", "bluetooth"), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown connectivity"):
        load_settings(tmp_path)


def test_two_edge_data_centers_on_the_same_spot_are_rejected(tmp_path):
    (tmp_path / "simulation_parameters.properties").write_text(PROPERTIES, encoding="utf-8")
    (tmp_path / "cloud.xml").write_text(CLOUD_XML, encoding="utf-8")
    (tmp_path / "applications.xml").write_text(APPLICATION_XML, encoding="utf-8")
    (tmp_path / "edge_devices.xml").write_text(DEVICE_XML, encoding="utf-8")
    (tmp_path / "edge_datacenters.xml").write_text(
        EDGE_XML.replace("<x_pos>170</x_pos><y_pos>170</y_pos>", "<x_pos>30</x_pos><y_pos>30</y_pos>"),
        encoding="utf-8")
    with pytest.raises(ValueError, match="same location"):
        load_settings(tmp_path)


def test_edge_data_center_without_a_location_is_rejected(tmp_path):
    (tmp_path / "simulation_parameters.properties").write_text(PROPERTIES, encoding="utf-8")
    (tmp_path / "cloud.xml").write_text(CLOUD_XML, encoding="utf-8")
    (tmp_path / "applications.xml").write_text(APPLICATION_XML, encoding="utf-8")
    (tmp_path / "edge_devices.xml").write_text(DEVICE_XML, encoding="utf-8")
    (tmp_path / "edge_datacenters.xml").write_text(
        EDGE_XML.replace("<location><x_pos>30</x_pos><y_pos>30</y_pos></location>", ""), encoding="utf-8")
    with pytest.raises(ValueError, match="has no <location> element"):
        load_settings(tmp_path)


def test_shipped_examples_are_loadable(settings_folder):
    files = load_settings(settings_folder)
    assert files.applications and files.devices and files.edge_datacenters


def test_the_partitioning_examples_load_their_service_graph():
    folder = Path(__file__).resolve().parents[1] / "examples" / "partitioning_settings"
    parameters = load_parameters(folder / "simulation_parameters.properties")
    files = load_settings(folder)
    assert parameters.orchestration_architectures == ["ALL"]
    assert parameters.random_seed == 42
    assert files.man_links == [("dc1", "dc2"), ("dc2", "dc3"), ("dc3", "dc4"), ("dc4", "dc1")]
    graph = files.applications[0]
    assert graph.has_subtasks and len(graph.subtasks) == 7
    assert {subtask.name for subtask in graph.subtasks} == {
        "capture", "preprocess", "detect", "classify", "track", "aggregate", "notify"}


# ---------------------------------------------------------------------------
# Service graphs
# ---------------------------------------------------------------------------

GRAPH_APPLICATION = ('<application name="Video"><type>Real-time</type><rate>60</rate>'
                     '<usage_percentage>100</usage_percentage><latency>2</latency>'
                     '<container_size>100</container_size><request_size>10</request_size>'
                     '<results_size>20</results_size><task_length>1000</task_length>{subtasks}'
                     '</application>')


def load_applications_xml(tmp_path, subtasks: str):
    path = tmp_path / "applications.xml"
    graph_file = ('<?xml version="1.0"?><applications>' + GRAPH_APPLICATION + '</applications>')
    path.write_text(graph_file.format(subtasks=subtasks), encoding="utf-8")
    from pureedgesim.config import load_applications
    return load_applications(path)


def test_an_application_without_subtask_elements_remains_a_single_task(tmp_path):
    application = load_applications_xml(tmp_path, "")[0]
    assert application.has_subtasks is False
    assert application.subtasks == ()


def test_a_service_graph_inherits_the_application_values(tmp_path):
    application = load_applications_xml(
        tmp_path,
        '<subtask name="capture"/>'
        '<subtask name="detect" depends_on="capture"/>'
        '<subtask name="alert" depends_on="detect"/>')[0]
    assert application.has_subtasks is True
    assert [subtask.name for subtask in application.subtasks] == ["capture", "detect", "alert"]
    assert application.subtasks[0].is_root
    assert application.subtasks[1].dependencies == ("capture",)
    assert application.subtasks[2].dependencies == ("detect",)
    for subtask in application.subtasks:
        assert subtask.task_length.mean() == 1000
        assert subtask.latency.mean() == 2
        assert subtask.container_size.mean() == 100 * 8000
        assert subtask.request_size.mean() == 10 * 8000
        assert subtask.results_size.mean() == 20 * 8000


def test_subtask_attributes_override_the_application_values(tmp_path):
    application = load_applications_xml(
        tmp_path,
        '<subtask name="heavy" latency="1.5" task_length="5000" request_size="30" '
        'results_size="40" container_size="200"/>')[0]
    subtask = application.subtasks[0]
    assert subtask.latency.mean() == 1.5
    assert subtask.task_length.mean() == 5000
    assert subtask.request_size.mean() == 30 * 8000
    assert subtask.results_size.mean() == 40 * 8000
    assert subtask.container_size.mean() == 200 * 8000


def test_a_subtask_may_depend_on_several_others(tmp_path):
    application = load_applications_xml(
        tmp_path,
        '<subtask name="a"/><subtask name="b"/><subtask name="join" depends_on="a, b, a"/>')[0]
    assert application.subtasks[2].dependencies == ("a", "b")


@pytest.mark.parametrize("subtasks, message", [
    ('<subtask depends_on="a"/>', "has no"),
    ('<subtask name="a"/><subtask name="a"/>', "declared more than once"),
    ('<subtask name="a" length="10"/>', "unknown attribute"),
    ('<subtask name="a" depends_on="missing"/>', "unknown dependency"),
    ('<subtask name="a" depends_on="a"/>', "cannot depend on itself"),
    ('<subtask name="a"/><subtask name="b" depends_on="a,"/>', "empty name"),
    ('<subtask name="a" depends_on="b"/><subtask name="b" depends_on="a"/>', "dependency cycle"),
    ('<subtask name="a" task_length="0"/>', "invalid"),
    ('<subtask name="a" latency="-1"/>', "invalid"),
    ('<subtask name="a" request_size="fast"/>', "non-numeric"),
])
def test_a_broken_service_graph_is_rejected(tmp_path, subtasks, message):
    with pytest.raises(ValueError, match=message):
        load_applications_xml(tmp_path, subtasks)
