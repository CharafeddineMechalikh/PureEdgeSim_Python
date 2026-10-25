"""Location and mobility models, the counterpart of the locationmanager package."""
from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .distribution import ParetoDistribution
from .randomness import Randomness

if TYPE_CHECKING:
    from .manager import SimulationManager


@dataclass(frozen=True)
class Location:
    x_pos: float = 0.0
    y_pos: float = 0.0


class MobilityModel:
    """Base class. Subclasses implement get_next_location; the path is precomputed."""

    def __init__(self, manager: "SimulationManager | None", location: Location) -> None:
        self.manager = manager
        self.current_location = location
        self.is_mobile = False
        self.min_pause_duration = 0.0
        self.max_pause_duration = 0.0
        self.min_mobility_duration = 0.0
        self.max_mobility_duration = 0.0
        self.speed = 0.0
        self.random = Randomness.get_random()
        self.parameters: dict[str, str] = {}
        self.path: dict[int, Location] = {}
        self.datacenters_map: dict[int, object] = {}
        self.closest_edge_data_center = None

    @property
    def name(self) -> str:
        return type(self).__name__

    def set_parameters(self, parameters: dict[str, str] | None) -> "MobilityModel":
        self.parameters = {str(k).lower(): str(v) for k, v in (parameters or {}).items()}
        return self

    def _raw(self, name: str) -> str | None:
        value = self.parameters.get(name.lower())
        if value is None or value.strip() == "":
            return None
        return value.strip()

    def get_parameter(self, name: str, default: float | str) -> float | str:
        value = self._raw(name)
        if value is None:
            return default
        if isinstance(default, str):
            return value
        try:
            return float(value)
        except ValueError as error:
            raise ValueError(f'{self.name} - the "{name}" option must be a number, found "{value}"') from error

    def get_parameter_int(self, name: str, default: int) -> int:
        value = float(self.get_parameter(name, default))
        if value != math.floor(value):
            raise ValueError(f'{self.name} - the "{name}" option must be an integer, found "{value}"')
        return int(value)

    def get_parameter_bool(self, name: str, default: bool) -> bool:
        value = self._raw(name)
        return default if value is None else value.strip().lower() == "true"

    def get_required_parameter(self, name: str) -> str:
        value = self._raw(name)
        if value is None:
            raise ValueError(f'{self.name} - the "{name}" option is required, check the "mobility" element')
        return value

    @property
    def map_width(self) -> float:
        return self.manager.parameters.simulation_map_width

    @property
    def map_length(self) -> float:
        return self.manager.parameters.simulation_map_length

    @property
    def update_interval(self) -> float:
        return self.manager.parameters.update_interval

    def get_step_distance(self) -> float:
        return self.speed * self.update_interval

    def get_ticks_count(self) -> int:
        return int(self.manager.parameters.simulation_duration / self.update_interval) + 1

    def random_in_range(self, minimum: float, maximum: float) -> float:
        if maximum <= minimum:
            return minimum
        return minimum + self.random.random() * (maximum - minimum)

    @staticmethod
    def move_towards(origin: Location, target: Location, distance: float) -> Location:
        dx, dy = target.x_pos - origin.x_pos, target.y_pos - origin.y_pos
        gap = math.hypot(dx, dy)
        if gap == 0 or gap <= distance:
            return Location(target.x_pos, target.y_pos)
        ratio = distance / gap
        return Location(origin.x_pos + dx * ratio, origin.y_pos + dy * ratio)

    @staticmethod
    def reached(origin: Location, target: Location, tolerance: float) -> bool:
        return math.hypot(target.x_pos - origin.x_pos, target.y_pos - origin.y_pos) <= tolerance

    def reflect_location(self, location: Location) -> Location:
        width, length = self.map_width, self.map_length
        x, y = location.x_pos, location.y_pos
        if x < 0:
            x = -x
        if y < 0:
            y = -y
        if width > 0 and x > width:
            x = width - (x - width)
        if length > 0 and y > length:
            y = length - (y - length)
        return Location(min(max(x, 0), max(width, 0)), min(max(y, 0), max(length, 0)))

    def clamp_to_map(self, location: Location) -> Location:
        return Location(min(max(location.x_pos, 0), self.map_width),
                        min(max(location.y_pos, 0), self.map_length))

    def get_next_location(self, location: Location) -> Location:
        raise NotImplementedError

    def generate_path(self) -> None:
        self.closest_edge_data_center = self.get_data_center()
        if not self.is_mobile:
            return
        new_location = self.current_location
        interval = int(self.update_interval * 1000)
        simulation_time = int(self.manager.parameters.simulation_duration * 1000)
        for i in range(0, simulation_time + 1, interval):
            self.path[i] = new_location
            new_location = self.get_next_location(new_location)
            self.datacenters_map[i] = self.get_data_center_at(new_location)

    def update_location(self, time: float) -> Location:
        if time <= self.manager.parameters.simulation_duration:
            self.current_location = self.path.get(int(time) * 1000, self.current_location)
        return self.current_location

    def distance_to(self, other) -> float:
        theirs = other.mobility_model.current_location
        return math.hypot(self.current_location.x_pos - theirs.x_pos,
                          self.current_location.y_pos - theirs.y_pos)

    def get_data_center_at(self, location: Location):
        from .nodes import ComputingNode
        closest = ComputingNode.NULL
        best = self.manager.parameters.edge_data_centers_range
        for node in self.manager.edge_only_list:
            if not node.is_peripheral:
                continue
            position = node.mobility_model.current_location
            distance = math.hypot(location.x_pos - position.x_pos, location.y_pos - position.y_pos)
            if distance <= best:
                best, closest = distance, node
        return closest

    def get_data_center(self):
        return self.get_data_center_at(self.current_location)

    def get_closest_edge_data_center(self):
        if self.is_mobile and self.manager.engine.clock <= self.manager.parameters.simulation_duration:
            return self.datacenters_map.get(int(self.manager.engine.clock * 1000), self.closest_edge_data_center)
        return self.closest_edge_data_center


class DefaultMobilityModel(MobilityModel):
    def __init__(self, manager, location: Location) -> None:
        super().__init__(manager, location)
        self.pause = False
        self.pause_duration = -1.0
        self.mobility_duration = 0.0
        self.orientation_angle = self.random.randrange(359)

    def get_next_location(self, location: Location) -> Location:
        if self.pause and self.pause_duration > 0:
            self.pause_duration -= self.update_interval
            return location
        self.reorientate(location.x_pos, location.y_pos)
        if self.mobility_duration <= 0:
            self.start_pause()
        if self.pause_duration <= 0:
            self.resume()
        distance = self.get_step_distance()
        angle = math.radians(self.orientation_angle)
        return Location(location.x_pos + math.cos(angle) * distance,
                        location.y_pos + math.sin(angle) * distance)

    def resume(self) -> None:
        self.pause = False
        self.mobility_duration -= self.update_interval

    def start_pause(self) -> None:
        self.pause_duration = self.random_in_range(self.min_pause_duration, self.max_pause_duration)
        self.pause = True
        self.orientation_angle = self.random.randrange(359)
        self.mobility_duration = self.random_in_range(self.min_mobility_duration, self.max_mobility_duration)

    def reorientate(self, x: float, y: float) -> None:
        if x >= self.map_width:
            self.orientation_angle = -90 - self.random.randrange(180)
        elif x <= 0:
            self.orientation_angle = -90 + self.random.randrange(180)
        if y >= self.map_length:
            self.orientation_angle = -self.random.randrange(180)
        elif y <= 0:
            self.orientation_angle = self.random.randrange(180)


class RandomWalkMobilityModel(MobilityModel):
    def get_next_location(self, location: Location) -> Location:
        angle = math.radians(self.random.random() * 360.0)
        distance = self.get_step_distance()
        return self.reflect_location(Location(location.x_pos + math.cos(angle) * distance,
                                              location.y_pos + math.sin(angle) * distance))


class GaussMarkovMobilityModel(MobilityModel):
    def __init__(self, manager, location: Location) -> None:
        super().__init__(manager, location)
        self.initialised = False

    def init(self) -> None:
        self.alpha = float(self.get_parameter("alpha", 0.7))
        if not 0 <= self.alpha < 1:
            raise ValueError(f'{self.name} - the "alpha" option must be >= 0 and < 1, found "{self.alpha}"')
        self.direction_std = float(self.get_parameter("std", 30))
        self.mean_speed = self.speed
        self.speed_std = float(self.get_parameter("speed_std", self.mean_speed * 0.2))
        self.mean_direction = self.random.random() * 360.0
        self.direction = self.mean_direction
        self.current_speed = self.mean_speed
        self.initialised = True

    def get_next_location(self, location: Location) -> Location:
        if not self.initialised:
            self.init()
        noise = math.sqrt(1 - self.alpha * self.alpha)
        self.direction = (self.mean_direction + self.alpha * (self.direction - self.mean_direction)
                          + self.random.gauss(0, 1) * self.direction_std * noise)
        self.current_speed = (self.mean_speed + self.alpha * (self.current_speed - self.mean_speed)
                              + self.random.gauss(0, 1) * self.speed_std * noise)
        distance = max(0.0, self.current_speed) * self.update_interval
        angle = math.radians(self.direction)
        return self.reflect_location(Location(location.x_pos + math.cos(angle) * distance,
                                              location.y_pos + math.sin(angle) * distance))


class ManhattanMobilityModel(MobilityModel):
    def __init__(self, manager, location: Location) -> None:
        super().__init__(manager, location)
        self.target: Location | None = None

    def get_next_location(self, location: Location) -> Location:
        step = self.get_step_distance()
        if step <= 0:
            return location
        if self.target is None or self.reached(location, self.target, 1e-6):
            self.target = self.pick_intersection()
        return self.move_one_axis(location, self.target, step)

    @staticmethod
    def move_one_axis(location: Location, destination: Location, step: float) -> Location:
        x, y = location.x_pos, location.y_pos
        if abs(destination.x_pos - x) > step:
            return Location(x + math.copysign(step, destination.x_pos - x), y)
        if abs(destination.y_pos - y) > step:
            return Location(destination.x_pos, y + math.copysign(step, destination.y_pos - y))
        return Location(destination.x_pos, destination.y_pos)

    def pick_intersection(self) -> Location:
        grid = max(1.0, float(self.get_parameter("grid_size", 100)))
        columns = max(1, int(self.map_width / grid))
        rows = max(1, int(self.map_length / grid))
        return Location(grid * (1 + self.random.randrange(columns)), grid * (1 + self.random.randrange(rows)))


class WaypointMobilityModel(MobilityModel):
    def __init__(self, manager, location: Location) -> None:
        super().__init__(manager, location)
        self.waypoints: list[Location] | None = None
        self.target_index = 0
        self.pause_remaining = 0.0
        self.finished = False

    def get_next_location(self, location: Location) -> Location:
        if self.waypoints is None:
            self.parse_waypoints()
        if self.finished:
            return self.waypoints[-1]
        if self.pause_remaining > 0:
            self.pause_remaining -= self.update_interval
            return location
        target = self.waypoints[self.target_index]
        if self.reached(location, target, self.get_step_distance()):
            return self.advance(location)
        return self.move_towards(location, target, self.get_step_distance())

    def advance(self, location: Location) -> Location:
        if self.target_index >= len(self.waypoints) - 1:
            if self.get_parameter_bool("loop", True):
                self.target_index = 0
            else:
                self.finished = True
        else:
            self.target_index += 1
        self.pause_remaining = self.min_pause_duration
        return location

    def parse_waypoints(self) -> None:
        value = self.get_required_parameter("waypoints")
        parsed: list[Location] = []
        for point in value.split(";"):
            if point.strip() == "":
                continue
            coordinates = point.split(",")
            if len(coordinates) != 2:
                raise ValueError(f'{self.name} - the "waypoints" option must be written as "x1,y1;x2,y2", found "{value}"')
            try:
                parsed.append(Location(float(coordinates[0].strip()), float(coordinates[1].strip())))
            except ValueError as error:
                raise ValueError(f'{self.name} - the "waypoints" option must only contain numbers, '
                                 f'found "{point.strip()}"') from error
        if len(parsed) < 2:
            raise ValueError(f'{self.name} - the "waypoints" option must contain at least two points, found "{value}"')
        self.waypoints = parsed


class CircularMobilityModel(MobilityModel):
    def __init__(self, manager, location: Location) -> None:
        super().__init__(manager, location)
        self.angle = 0.0
        self.initialised = False

    def get_next_location(self, location: Location) -> Location:
        radius = float(self.get_parameter("radius", -1))
        if radius <= 0:
            raise ValueError(f'{self.name} - the "radius" option must be > 0, found "{radius}"')
        center_x = float(self.get_parameter("center_x", self.map_width / 2.0))
        center_y = float(self.get_parameter("center_y", self.map_length / 2.0))
        if not self.initialised:
            self.angle = math.atan2(location.y_pos - center_y, location.x_pos - center_x)
            self.initialised = True
        angular_step = self.get_step_distance() / radius
        self.angle += angular_step if self.get_parameter_bool("clockwise", True) else -angular_step
        return Location(center_x + math.cos(self.angle) * radius, center_y + math.sin(self.angle) * radius)


class LevyWalkMobilityModel(MobilityModel):
    def __init__(self, manager, location: Location) -> None:
        super().__init__(manager, location)
        self.target: Location | None = None

    def get_next_location(self, location: Location) -> Location:
        step = self.get_step_distance()
        if step <= 0:
            return location
        if self.target is None or self.reached(location, self.target, 1e-6):
            self.target = self.pick_flight_end(location)
        return self.move_towards(location, self.target, step)

    def pick_flight_end(self, location: Location) -> Location:
        min_step = float(self.get_parameter("min_step", self.get_step_distance()))
        max_step = float(self.get_parameter("max_step", math.hypot(self.map_width, self.map_length)))
        shape = float(self.get_parameter("shape", 1.5))
        if shape <= 0:
            raise ValueError(f'{self.name} - the "shape" option must be > 0, found "{shape}"')
        length = min(max_step, ParetoDistribution(min_step, shape, self.random).sample())
        angle = math.radians(self.random.random() * 360.0)
        return self.clamp_to_map(Location(location.x_pos + math.cos(angle) * length,
                                          location.y_pos + math.sin(angle) * length))


class BrownianMobilityModel(MobilityModel):
    def get_next_location(self, location: Location) -> Location:
        std = float(self.get_parameter("std", self.get_step_distance()))
        return self.reflect_location(Location(location.x_pos + self.random.gauss(0, 1) * std,
                                              location.y_pos + self.random.gauss(0, 1) * std))


class ReferencePointGroupMobilityModel(MobilityModel):
    def __init__(self, manager, location: Location) -> None:
        super().__init__(manager, location)
        self.anchor_path: list[Location] | None = None
        self.offset = Location(0, 0)
        self.tick = 0

    def get_next_location(self, location: Location) -> Location:
        if self.anchor_path is None:
            self.anchor_path = self.generate_anchor_path()
            self.offset = Location(location.x_pos - self.anchor_path[0].x_pos,
                                   location.y_pos - self.anchor_path[0].y_pos)
        self.tick = min(self.tick + 1, len(self.anchor_path) - 1)
        anchor = self.anchor_path[self.tick]
        return self.reflect_location(Location(anchor.x_pos + self.offset.x_pos, anchor.y_pos + self.offset.y_pos))

    def generate_anchor_path(self) -> list[Location]:
        import random as _random

        group = str(self.get_parameter("group", "1"))
        anchor_speed = float(self.get_parameter("anchor_speed", self.speed))
        anchor_pause = float(self.get_parameter("anchor_pause", 0))
        seed = (sum((i + 1) * ord(c) for i, c in enumerate(group)) * 1000003
                + int(self.manager.parameters.simulation_duration))
        anchor_random = _random.Random(seed)
        path: list[Location] = []
        anchor = Location(anchor_random.random() * self.map_width, anchor_random.random() * self.map_length)
        pause_remaining = 0.0
        target: Location | None = None
        step = anchor_speed * self.update_interval
        for _ in range(self.get_ticks_count()):
            path.append(anchor)
            if pause_remaining > 0:
                pause_remaining -= self.update_interval
                continue
            if target is None or self.reached(anchor, target, step):
                target = Location(anchor_random.random() * self.map_width, anchor_random.random() * self.map_length)
                pause_remaining = anchor_pause
            anchor = self.move_towards(anchor, target, step)
        return path

    def get_group(self) -> str:
        return str(self.get_parameter("group", "1"))


class MobilityModelFactory:
    MODELS = {
        "random-waypoint": DefaultMobilityModel,
        "default": DefaultMobilityModel,
        "random-walk": RandomWalkMobilityModel,
        "gauss-markov": GaussMarkovMobilityModel,
        "manhattan": ManhattanMobilityModel,
        "waypoint": WaypointMobilityModel,
        "circular": CircularMobilityModel,
        "levy-walk": LevyWalkMobilityModel,
        "brownian": BrownianMobilityModel,
        "group": ReferencePointGroupMobilityModel,
        "rpgm": ReferencePointGroupMobilityModel,
    }

    @classmethod
    def known_names(cls) -> list[str]:
        return sorted(cls.MODELS)

    @classmethod
    def resolve(cls, name: str) -> type[MobilityModel]:
        if name is None or name.strip() == "":
            raise ValueError("No mobility model given, expected one of: " + ", ".join(cls.known_names()))
        key = name.strip().lower()
        if key in cls.MODELS:
            return cls.MODELS[key]
        if "." not in name:
            raise ValueError(f'Mobility model "{name}" is not supported, expected one of: '
                             + ", ".join(cls.known_names()) + " (or a dotted class path)")
        module_name, _, class_name = name.strip().rpartition(".")
        try:
            model = getattr(importlib.import_module(module_name), class_name)
        except (ImportError, AttributeError) as error:
            raise ValueError(f'Mobility model class "{name}" was not found; check the spelling') from error
        if not (isinstance(model, type) and issubclass(model, MobilityModel)):
            raise ValueError(f'The class "{name}" does not extend MobilityModel')
        return model

    @classmethod
    def create(cls, name: str, manager, location: Location) -> MobilityModel:
        return cls.resolve(name)(manager, location)
