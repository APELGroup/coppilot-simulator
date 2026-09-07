"""Pydantic request models for all routes."""
from typing import Literal

from pydantic import BaseModel


class RunRequest(BaseModel):
    horizon: Literal["day", "week", "month"]
    year: int = 2016
    month: int
    day: int | None = None
    mode: Literal["balanced"] = "balanced"


class ConvertOpenDSSRequest(BaseModel):
    network: Literal["1", "2", "3", "4"]
    mode: Literal["balanced", "unbalanced"]


class SimulateOpenDSSRequest(BaseModel):
    network: Literal["1", "2", "3", "4"]
    mode: Literal["balanced", "unbalanced"]
    day: int  # 1–365
    validation_hours: Literal[1, 2, 4, 24] = 2


class SaveOpenDSSRequest(BaseModel):
    network: Literal["1", "2", "3", "4"]
    mode: Literal["balanced", "unbalanced"]
    validation_day: int | None = None
    metrics: dict | None = None


class OpenDSSRunRequest(BaseModel):
    day: int  # 1–365 day of year


class PowerFlowRequest(BaseModel):
    date: str   # YYYY-MM-DD
    time: str   # HH:MM (15-min snap for SimBench; nominal for OpenDSS)


class CreateScenarioRequest(BaseModel):
    id: str | None = None
    name: str
    network_id: str
    sim_type: Literal["time_series"] = "time_series"
    mode: Literal["balanced", "unbalanced"] = "balanced"
    horizon: Literal["day", "week", "month"] = "day"
    timestep: str = "15min"
    created_by: str = "unknown"


class CreateUserRequest(BaseModel):
    name: str
    email: str
    role: Literal["admin", "researcher", "student"]


class UpdateUserRoleRequest(BaseModel):
    role: Literal["admin", "researcher", "student"]


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: Literal["student", "researcher"] = "student"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class _DeviceRegisterRequest(BaseModel):
    id: str
    name: str
    node_id: str | None = None
    extra: dict | None = None


class _DeviceTelemetryRequest(BaseModel):
    device_id: str
    readings: dict
