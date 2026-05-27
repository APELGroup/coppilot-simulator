"""
Database layer for SimBench backend.

DB is OPTIONAL. If DATABASE_URL is not set or PostgreSQL is unreachable,
every function in this module returns None/False and the app continues
running in filesystem-only mode — existing behaviour is fully preserved.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, JSON, String,
    create_engine, text,
)
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

_engine = None
_Session = None


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class NetworkRecord(Base):
    """[DB-BACKED] Mirrors the network metadata in data/networks.json."""
    __tablename__ = "networks"

    id           = Column(String,  primary_key=True)
    name         = Column(String,  nullable=False)
    voltage      = Column(String)
    type         = Column(String)
    status       = Column(String)
    created      = Column(String)
    version      = Column(String)
    buses        = Column(Integer)
    lines        = Column(Integer)
    transformers = Column(Integer)
    loads        = Column(Integer)
    plot_url     = Column(String)
    extra        = Column(JSON, nullable=True)   # forward-compat catch-all


class SimulationRun(Base):
    """
    [DB-BACKED] One row per completed simulation.
    CSV result files are still written to the filesystem (unchanged);
    this table stores only the run metadata / index.
    """
    __tablename__ = "simulation_runs"

    run_id     = Column(String,   primary_key=True)
    network_id = Column(String,   nullable=False, index=True)
    horizon    = Column(String,   nullable=False)   # day | week | month
    year       = Column(Integer,  nullable=False)
    month      = Column(Integer,  nullable=False)
    day        = Column(Integer,  nullable=True)    # None for month horizon
    mode             = Column(String,   nullable=False)
    status           = Column(String,   nullable=False, default="completed")
    has_trafo        = Column(Boolean,  nullable=False, default=False)
    started_at                = Column(DateTime, nullable=True)
    duration_seconds          = Column(Float,    nullable=True)
    violations_under_voltage  = Column(Integer,  nullable=True)
    violations_over_voltage   = Column(Integer,  nullable=True)
    violations_line_overload  = Column(Integer,  nullable=True)
    violations_trafo_overload = Column(Integer,  nullable=True)
    violations_total          = Column(Integer,  nullable=True)
    created_by                = Column(String,   nullable=True)
    created_at                = Column(DateTime, nullable=False, default=datetime.utcnow)


class EdgeNode(Base):
    """Logical grouping of edge devices (e.g. a substation or field cabinet)."""
    __tablename__ = "edge_nodes"

    id         = Column(String,  primary_key=True)
    name       = Column(String,  nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class EdgeDevice(Base):
    """Registered edge device (Raspberry Pi, PLC, sensor node, …)."""
    __tablename__ = "edge_devices"

    id            = Column(String,  primary_key=True)
    name          = Column(String,  nullable=False)
    node_id       = Column(String,  nullable=True)       # belongs to which EdgeNode
    status        = Column(String,  default="online")   # online | offline
    last_seen     = Column(DateTime, nullable=True)
    registered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    extra         = Column(JSON, nullable=True)


class DeviceTelemetry(Base):
    """One telemetry snapshot posted by an edge device."""
    __tablename__ = "device_telemetry"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String,  nullable=False, index=True)
    ts        = Column(DateTime, nullable=False, default=datetime.utcnow)
    readings  = Column(JSON, nullable=False)


# ---------------------------------------------------------------------------
# Connection bootstrap
# ---------------------------------------------------------------------------

def init_db() -> bool:
    """
    Connect to PostgreSQL and create tables if they don't exist.
    Returns True on success, False if DB is not configured or unreachable.
    Safe to call at startup — failure is logged and swallowed.
    """
    global _engine, _Session

    url = os.getenv("DATABASE_URL")
    if not url:
        logger.info("DATABASE_URL not set — running in filesystem-only mode")
        return False

    try:
        _engine = create_engine(url, pool_pre_ping=True, echo=False)
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))   # verify reachability
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(bind=_engine)
        # ── Column migrations (safe to run on every startup) ──────────────
        try:
            with _engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE users "
                    "ADD COLUMN IF NOT EXISTS hashed_password VARCHAR"
                ))
                conn.execute(text(
                    "ALTER TABLE simulation_runs "
                    "ADD COLUMN IF NOT EXISTS created_by VARCHAR"
                ))
                conn.execute(text(
                    "ALTER TABLE edge_devices "
                    "ADD COLUMN IF NOT EXISTS node_id VARCHAR"
                ))
                conn.commit()
            logger.info("Schema migration: hashed_password + created_by + node_id columns ensured")
        except Exception as mig_exc:
            logger.warning("Schema migration skipped (non-fatal): %s", mig_exc)
        logger.info("PostgreSQL connected and schema ready")
        return True
    except (OperationalError, SQLAlchemyError, Exception) as exc:
        logger.warning("PostgreSQL unavailable — filesystem fallback active. Reason: %s", exc)
        _engine = None
        _Session = None
        return False


def db_available() -> bool:
    return _Session is not None


# ---------------------------------------------------------------------------
# Run helpers (used by /runs and /networks/{id}/run)
# ---------------------------------------------------------------------------

def _run_to_api(run: SimulationRun) -> dict:
    """Convert an ORM row to the same JSON shape /runs has always returned."""
    nid, rid = run.network_id, run.run_id
    return {
        "network_id":       nid,
        "run_id":           rid,
        "started_at":       run.started_at.isoformat() if run.started_at else None,
        "duration_seconds": run.duration_seconds,
        "violations": {
            "under_voltage":  run.violations_under_voltage,
            "over_voltage":   run.violations_over_voltage,
            "line_overload":  run.violations_line_overload,
            "trafo_overload": run.violations_trafo_overload,
            "total":          run.violations_total,
        },
        "results": {
            "vm_pu":        f"/networks/{nid}/results/{rid}/vm-pu",
            "line_loading": f"/networks/{nid}/results/{rid}/line-loading",
            "trafo_loading": (
                f"/networks/{nid}/results/{rid}/trafo-loading"
                if run.has_trafo else None
            ),
        },
        "created_by": run.created_by,
    }


def get_db_runs() -> list[dict] | None:
    """
    Return all runs from PostgreSQL ordered by creation time.
    Returns None if DB is unavailable — caller should then fall back to
    the filesystem scan. An empty list [] is a valid DB result and is
    returned as-is; the caller decides whether to also fall back in that case.
    """
    if not db_available():
        return None
    try:
        with _Session() as session:
            rows = (
                session.query(SimulationRun)
                .order_by(SimulationRun.created_at)
                .all()
            )
            return [_run_to_api(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("DB read failed, filesystem fallback active: %s", exc)
        return None


def save_run(
    *,
    run_id: str,
    network_id: str,
    horizon: str,
    year: int,
    month: int,
    day: int | None,
    mode: str,
    has_trafo: bool,
    started_at: datetime | None = None,
    duration_seconds: float | None = None,
    violations_under_voltage: int | None = None,
    violations_over_voltage: int | None = None,
    violations_line_overload: int | None = None,
    violations_trafo_overload: int | None = None,
    violations_total: int | None = None,
    created_by: str | None = None,
) -> bool:
    """
    Persist a completed simulation run.
    Returns True on success, False (non-fatal) if DB is unavailable or the
    insert fails — the HTTP response is returned to the client either way.
    """
    if not db_available():
        return False
    try:
        with _Session() as session:
            session.add(SimulationRun(
                run_id=run_id, network_id=network_id,
                horizon=horizon, year=year, month=month, day=day,
                mode=mode, status="completed", has_trafo=has_trafo,
                started_at=started_at, duration_seconds=duration_seconds,
                violations_under_voltage=violations_under_voltage,
                violations_over_voltage=violations_over_voltage,
                violations_line_overload=violations_line_overload,
                violations_trafo_overload=violations_trafo_overload,
                violations_total=violations_total,
                created_by=created_by,
            ))
            session.commit()
        logger.info("Run %s saved to PostgreSQL", run_id)
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not persist run %s: %s", run_id, exc)
        return False


def delete_run(run_id: str) -> bool:
    """
    Delete a simulation run from PostgreSQL by run_id.
    Returns True if deleted, False if not found or DB unavailable.
    """
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.query(SimulationRun).filter_by(run_id=run_id).first()
            if not row:
                return False
            session.delete(row)
            session.commit()
        logger.info("Run %s deleted from PostgreSQL", run_id)
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not delete run %s: %s", run_id, exc)
        return False


# ---------------------------------------------------------------------------
# Network helpers (used by /networks and /networks/{id})
# ---------------------------------------------------------------------------

_NETWORK_KNOWN_KEYS = {
    "id", "name", "voltage", "type", "status", "created", "version",
    "buses", "lines", "transformers", "loads", "plot_url",
}


def _network_to_api(n: NetworkRecord) -> dict:
    """Convert a NetworkRecord ORM row to the original JSON shape."""
    result = {
        "id":           n.id,
        "name":         n.name,
        "voltage":      n.voltage,
        "type":         n.type,
        "status":       n.status,
        "created":      n.created,
        "version":      n.version,
        "buses":        n.buses,
        "lines":        n.lines,
        "transformers": n.transformers,
        "loads":        n.loads,
        "plot_url":     n.plot_url,
    }
    if n.extra:
        result.update(n.extra)
    return result


def get_db_networks() -> list[dict] | None:
    """
    Return all networks from PostgreSQL ordered by id.
    Returns None if DB unavailable — caller falls back to JSON file.
    """
    if not db_available():
        return None
    try:
        with _Session() as session:
            rows = session.query(NetworkRecord).order_by(NetworkRecord.id).all()
            return [_network_to_api(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("DB read failed for networks: %s", exc)
        return None


def get_db_network(network_id: str) -> dict | None:
    """
    Return a single network by ID from PostgreSQL.
    Returns None if not found OR if DB is unavailable.
    """
    if not db_available():
        return None
    try:
        with _Session() as session:
            row = session.query(NetworkRecord).filter_by(id=network_id).first()
            return _network_to_api(row) if row else None
    except SQLAlchemyError as exc:
        logger.warning("DB read failed for network %s: %s", network_id, exc)
        return None


def save_network(data: dict) -> bool:
    """
    Insert or update a network record. Silently returns False when DB is unavailable.
    Keys not in _NETWORK_KNOWN_KEYS are stored in the extra JSON column.
    """
    if not db_available():
        return False
    try:
        extra = {k: v for k, v in data.items() if k not in _NETWORK_KNOWN_KEYS} or None
        with _Session() as session:
            row = session.query(NetworkRecord).filter_by(id=data["id"]).first()
            if row:
                for key in _NETWORK_KNOWN_KEYS:
                    if key in data:
                        setattr(row, key, data[key])
                row.extra = extra
            else:
                session.add(NetworkRecord(
                    id=data["id"],
                    name=data["name"],
                    voltage=data.get("voltage"),
                    type=data.get("type"),
                    status=data.get("status"),
                    created=data.get("created"),
                    version=data.get("version"),
                    buses=data.get("buses"),
                    lines=data.get("lines"),
                    transformers=data.get("transformers"),
                    loads=data.get("loads"),
                    plot_url=data.get("plot_url"),
                    extra=extra,
                ))
            session.commit()
        logger.info("Network %s saved to PostgreSQL", data["id"])
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not save network %s: %s", data["id"], exc)
        return False


def update_network_loads(network_id: str, loads: int) -> bool:
    """Patch the loads count for a single network row. Silent no-op if DB unavailable."""
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.query(NetworkRecord).filter_by(id=network_id).first()
            if row:
                row.loads = loads
                session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not update loads for %s: %s", network_id, exc)
        return False


def delete_network(network_id: str) -> bool:
    """
    Delete a network record from PostgreSQL by id.
    Returns True if deleted, False if not found or DB unavailable.
    """
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.query(NetworkRecord).filter_by(id=network_id).first()
            if not row:
                return False
            session.delete(row)
            session.commit()
        logger.info("Network %s deleted from PostgreSQL", network_id)
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not delete network %s: %s", network_id, exc)
        return False


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------

class Scenario(Base):
    __tablename__ = "scenarios"

    id         = Column(String,   primary_key=True)
    name       = Column(String,   nullable=False)
    network_id = Column(String,   nullable=False, index=True)
    sim_type   = Column(String,   nullable=False)
    mode       = Column(String,   nullable=False)
    horizon    = Column(String,   nullable=False)
    timestep   = Column(String,   nullable=False, default="15min")
    created_by = Column(String,   nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def _scenario_to_api(s: "Scenario") -> dict:
    return {
        "id":        s.id,
        "name":      s.name,
        "networkId": s.network_id,
        "simType":   s.sim_type,
        "mode":      s.mode,
        "horizon":   s.horizon,
        "timestep":  s.timestep,
        "createdBy": s.created_by,
        "createdAt": s.created_at.strftime("%Y-%m-%d") if s.created_at else None,
    }


def get_db_scenarios() -> list[dict] | None:
    if not db_available():
        return None
    try:
        with _Session() as session:
            rows = session.query(Scenario).order_by(Scenario.created_at.desc()).all()
            return [_scenario_to_api(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("DB read failed for scenarios: %s", exc)
        return None


def save_scenario(
    *,
    id: str,
    name: str,
    network_id: str,
    sim_type: str = "time_series",
    mode: str = "balanced",
    horizon: str = "day",
    timestep: str = "15min",
    created_by: str = "unknown",
) -> dict | None:
    if not db_available():
        return None
    try:
        with _Session() as session:
            row = Scenario(
                id=id, name=name, network_id=network_id,
                sim_type=sim_type, mode=mode, horizon=horizon,
                timestep=timestep, created_by=created_by,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _scenario_to_api(row)
    except SQLAlchemyError as exc:
        logger.warning("Could not save scenario %s: %s", id, exc)
        return None


def delete_scenario(scenario_id: str) -> bool:
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.query(Scenario).filter_by(id=scenario_id).first()
            if row:
                session.delete(row)
                session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not delete scenario %s: %s", scenario_id, exc)
        return False


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id              = Column(String,   primary_key=True)
    name            = Column(String,   nullable=False)
    email           = Column(String,   nullable=False, index=True)
    role            = Column(String,   nullable=False)
    initials        = Column(String,   nullable=False)
    is_self         = Column(Boolean,  nullable=False, default=False)
    hashed_password = Column(String,   nullable=True)
    created_at      = Column(DateTime, nullable=False, default=datetime.utcnow)


def _user_to_api(u: "User") -> dict:
    return {
        "id":       u.id,
        "name":     u.name,
        "email":    u.email,
        "role":     u.role,
        "initials": u.initials,
        "isSelf":   u.is_self,
    }


def get_user_by_email(email: str) -> dict | None:
    """
    Return a user dict that *includes* hashed_password — for auth use only.
    Returns None if not found or DB unavailable.
    """
    if not db_available():
        return None
    try:
        with _Session() as session:
            row = session.query(User).filter_by(email=email).first()
            if row is None:
                return None
            return {
                "id":              row.id,
                "name":            row.name,
                "email":           row.email,
                "role":            row.role,
                "initials":        row.initials,
                "is_self":         row.is_self,
                "hashed_password": row.hashed_password,
            }
    except SQLAlchemyError as exc:
        logger.warning("DB read failed for user by email %s: %s", email, exc)
        return None


def update_user_password(user_id: str, hashed_password: str) -> bool:
    """Set a new hashed_password for the given user. Returns True on success."""
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.query(User).filter_by(id=user_id).first()
            if row is None:
                return False
            row.hashed_password = hashed_password
            session.commit()
        logger.info("Password updated for user %s", user_id)
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not update password for user %s: %s", user_id, exc)
        return False


_SEED_USERS = [
    {"id": "u-1", "name": "Marco Rossi",         "email": "marco.rossi@dtlab.io",     "role": "admin",      "initials": "MR", "is_self": True},
    {"id": "u-2", "name": "Dr. Elena Marchetti", "email": "elena.marchetti@dtlab.io", "role": "researcher", "initials": "EM", "is_self": False},
    {"id": "u-3", "name": "Sofia Bianchi",        "email": "sofia.bianchi@dtlab.io",  "role": "student",    "initials": "SB", "is_self": False},
    {"id": "u-4", "name": "Luca Conti",           "email": "luca.conti@dtlab.io",     "role": "student",    "initials": "LC", "is_self": False},
    {"id": "u-5", "name": "Giulia Ferrari",       "email": "giulia.ferrari@dtlab.io", "role": "researcher", "initials": "GF", "is_self": False},
]


def seed_users() -> bool:
    """
    Seed the 5 hardcoded users with hashed passwords on first startup.
    If users already exist but have no hashed_password (legacy rows from
    before Milestone 1), fill in the default password hash for them.
    Safe to call multiple times — fully idempotent.
    """
    if not db_available():
        return False
    try:
        import bcrypt as _bcrypt
        _default_pw = os.getenv("SEED_USER_PASSWORD", "DtLab2025!")
        hashed = _bcrypt.hashpw(_default_pw.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")

        with _Session() as session:
            count = session.query(User).count()
            if count == 0:
                for u in _SEED_USERS:
                    session.add(User(**u, hashed_password=hashed))
                session.commit()
                logger.info("Seeded %d users into PostgreSQL", len(_SEED_USERS))
                return True
            else:
                # Back-fill hashed_password for any legacy rows that lack it
                rows = session.query(User).filter(User.hashed_password.is_(None)).all()
                for row in rows:
                    row.hashed_password = hashed
                if rows:
                    session.commit()
                    logger.info(
                        "Back-filled hashed_password for %d existing user(s)", len(rows)
                    )
                return False
    except SQLAlchemyError as exc:
        logger.warning("Failed to seed users: %s", exc)
        return False


def get_db_users() -> list[dict] | None:
    if not db_available():
        return None
    try:
        with _Session() as session:
            rows = session.query(User).order_by(User.created_at).all()
            return [_user_to_api(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("DB read failed for users: %s", exc)
        return None


def save_user(
    *,
    id: str,
    name: str,
    email: str,
    role: str,
    initials: str,
    is_self: bool = False,
    hashed_password: str | None = None,
) -> dict | None:
    if not db_available():
        return None
    try:
        with _Session() as session:
            existing = session.query(User).filter_by(email=email).first()
            if existing:
                return _user_to_api(existing)
            row = User(
                id=id, name=name, email=email, role=role,
                initials=initials, is_self=is_self,
                hashed_password=hashed_password,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _user_to_api(row)
    except SQLAlchemyError as exc:
        logger.warning("Could not save user %s: %s", id, exc)
        return None


def update_user_role(user_id: str, role: str) -> bool:
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.query(User).filter_by(id=user_id).first()
            if row:
                row.role = role
                session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not update role for user %s: %s", user_id, exc)
        return False


def delete_user(user_id: str) -> bool:
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.query(User).filter_by(id=user_id).first()
            if row:
                session.delete(row)
                session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not delete user %s: %s", user_id, exc)
        return False


# ---------------------------------------------------------------------------
# Validation metrics helpers
# ---------------------------------------------------------------------------

class ValidationMetrics(Base):
    __tablename__ = "validation_metrics"

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    network_id          = Column(String,   nullable=False, index=True)
    mode                = Column(String,   nullable=False)
    day                 = Column(Integer,  nullable=False)
    recorded_at         = Column(DateTime, nullable=False, default=datetime.utcnow)
    bus_voltage_mape    = Column(Float,    nullable=True)
    bus_voltage_max_err = Column(Float,    nullable=True)
    bus_voltage_bias    = Column(Float,    nullable=True)
    bus_voltage_matched = Column(Integer,  nullable=True)
    mv_line_mae         = Column(Float,    nullable=True)
    mv_line_max_ae      = Column(Float,    nullable=True)
    lv_line_mae         = Column(Float,    nullable=True)
    lv_line_max_ae      = Column(Float,    nullable=True)
    trafo_mae           = Column(Float,    nullable=True)
    trafo_max_ae        = Column(Float,    nullable=True)
    full_validation     = Column(JSON,     nullable=True)


def save_validation_metrics(
    network_id: str,
    mode: str,
    day: int,
    validation: dict,
) -> bool:
    if not db_available():
        return False
    try:
        bv = validation.get("bus_voltage", {}) or {}
        mv = validation.get("mv_line_loading", {}) or {}
        lv = validation.get("lv_line_loading", {}) or {}
        tr = validation.get("trafo_loading", {}) or {}
        with _Session() as session:
            session.add(ValidationMetrics(
                network_id=network_id, mode=mode, day=day,
                bus_voltage_mape=bv.get("mape"),
                bus_voltage_max_err=bv.get("max_error"),
                bus_voltage_bias=bv.get("bias"),
                bus_voltage_matched=bv.get("matched"),
                mv_line_mae=mv.get("mae"),
                mv_line_max_ae=mv.get("max_ae"),
                lv_line_mae=lv.get("mae"),
                lv_line_max_ae=lv.get("max_ae"),
                trafo_mae=tr.get("mae"),
                trafo_max_ae=tr.get("max_ae"),
                full_validation=validation,
            ))
            session.commit()
        logger.info("Validation metrics saved for %s day=%s", network_id, day)
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not save validation metrics: %s", exc)
        return False


def get_latest_validation(network_id: str, mode: str) -> dict | None:
    if not db_available():
        return None
    try:
        with _Session() as session:
            row = (
                session.query(ValidationMetrics)
                .filter_by(network_id=network_id, mode=mode)
                .order_by(ValidationMetrics.recorded_at.desc())
                .first()
            )
            return row.full_validation if row else None
    except SQLAlchemyError as exc:
        logger.warning("DB read failed for validation metrics: %s", exc)
        return None


def seed_networks_from_file(data_file: Path) -> bool:
    """
    Populate the networks table from the JSON file if the table is currently empty.
    Idempotent — skips silently if rows already exist.
    Returns True if rows were inserted, False otherwise.
    """
    if not db_available():
        return False
    try:
        with _Session() as session:
            if session.query(NetworkRecord).count() > 0:
                logger.info("networks table already populated — skipping seed")
                return False

        with open(data_file, "r", encoding="utf-8") as f:
            networks = json.load(f)

        with _Session() as session:
            for n in networks:
                extra = {k: v for k, v in n.items() if k not in _NETWORK_KNOWN_KEYS} or None
                session.add(NetworkRecord(
                    id=n["id"],
                    name=n["name"],
                    voltage=n.get("voltage"),
                    type=n.get("type"),
                    status=n.get("status"),
                    created=n.get("created"),
                    version=n.get("version"),
                    buses=n.get("buses"),
                    lines=n.get("lines"),
                    transformers=n.get("transformers"),
                    loads=n.get("loads"),
                    plot_url=n.get("plot_url"),
                    extra=extra,
                ))
            session.commit()
        logger.info("Seeded %d networks from %s into PostgreSQL", len(networks), data_file)
        return True
    except (OSError, SQLAlchemyError, Exception) as exc:
        logger.warning("Failed to seed networks from file: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Edge device helpers
# ---------------------------------------------------------------------------

def save_device(*, device_id: str, name: str, node_id: str | None = None,
                extra: dict | None = None) -> bool:
    """Upsert a device record and mark it online with current timestamp."""
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.get(EdgeDevice, device_id)
            now = datetime.utcnow()
            if row is None:
                session.add(EdgeDevice(id=device_id, name=name, node_id=node_id,
                                       status="online", last_seen=now, extra=extra))
            else:
                row.name = name
                row.status = "online"
                row.last_seen = now
                if node_id is not None:
                    row.node_id = node_id
                if extra is not None:
                    row.extra = extra
            session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("save_device failed: %s", exc)
        return False


def get_db_devices() -> list[dict] | None:
    """Return all registered edge devices. None if DB unavailable."""
    if not db_available():
        return None
    try:
        with _Session() as session:
            rows = session.query(EdgeDevice).order_by(EdgeDevice.registered_at).all()
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "node_id": r.node_id,
                    "status": r.status,
                    "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                    "registered_at": r.registered_at.isoformat() if r.registered_at else None,
                    "extra": r.extra,
                }
                for r in rows
            ]
    except SQLAlchemyError as exc:
        logger.warning("get_db_devices failed: %s", exc)
        return None


def save_telemetry(*, device_id: str, readings: dict) -> bool:
    """Insert one telemetry row for the given device."""
    if not db_available():
        return False
    try:
        with _Session() as session:
            session.add(DeviceTelemetry(device_id=device_id,
                                        ts=datetime.utcnow(), readings=readings))
            session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("save_telemetry failed: %s", exc)
        return False


def get_db_telemetry(device_id: str, limit: int = 60) -> list[dict] | None:
    """Return the last `limit` telemetry rows for a device. None if DB unavailable."""
    if not db_available():
        return None
    try:
        with _Session() as session:
            rows = (
                session.query(DeviceTelemetry)
                .filter_by(device_id=device_id)
                .order_by(DeviceTelemetry.ts.desc())
                .limit(limit)
                .all()
            )
            return [{"ts": r.ts.isoformat(), "readings": r.readings} for r in reversed(rows)]
    except SQLAlchemyError as exc:
        logger.warning("get_db_telemetry failed: %s", exc)
        return None


def mark_device_offline(device_id: str) -> bool:
    """Set a device's status to offline."""
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.get(EdgeDevice, device_id)
            if row:
                row.status = "offline"
                session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("mark_device_offline failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Edge node helpers
# ---------------------------------------------------------------------------

def save_edge_node(*, node_id: str, name: str) -> bool:
    """Upsert an edge node record."""
    if not db_available():
        return False
    try:
        with _Session() as session:
            row = session.get(EdgeNode, node_id)
            if row is None:
                session.add(EdgeNode(id=node_id, name=name))
            else:
                row.name = name
            session.commit()
        return True
    except SQLAlchemyError as exc:
        logger.warning("save_edge_node failed: %s", exc)
        return False


def get_db_edge_nodes() -> list[dict] | None:
    """Return all edge nodes. None if DB unavailable."""
    if not db_available():
        return None
    try:
        with _Session() as session:
            rows = session.query(EdgeNode).order_by(EdgeNode.created_at).all()
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except SQLAlchemyError as exc:
        logger.warning("get_db_edge_nodes failed: %s", exc)
        return None
