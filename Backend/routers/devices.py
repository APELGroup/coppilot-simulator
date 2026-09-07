"""Edge device registration, telemetry, and live-stream routes."""
import asyncio
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from auth_utils import get_current_user
from db import save_device, save_edge_node, save_telemetry, get_db_telemetry
from schemas import _DeviceRegisterRequest, _DeviceTelemetryRequest
from shared_state import _devices, _edge_nodes, _telemetry, _ws_subs

router = APIRouter()


@router.get("/devices")
def list_devices(_cu: dict = Depends(get_current_user)):
    """Return all registered edge devices."""
    return list(_devices.values())


@router.post("/devices/register", status_code=200)
def register_device(body: _DeviceRegisterRequest, request: Request):
    """Called by a device on boot to announce itself. No auth required."""
    from datetime import datetime as _dt
    now = _dt.utcnow().isoformat()
    agent_ip = request.client.host if request.client else None
    _devices[body.id] = {
        "id": body.id,
        "name": body.name,
        "node_id": body.node_id,
        "status": "online",
        "last_seen": now,
        "registered_at": _devices.get(body.id, {}).get("registered_at", now),
        "agent_ip": agent_ip,
        "agent_port": body.extra.get("agent_port", 8765) if body.extra else 8765,
        "extra": body.extra,
    }
    # Auto-create the node in memory if it's new
    if body.node_id and body.node_id not in _edge_nodes:
        _edge_nodes[body.node_id] = {"id": body.node_id, "name": body.node_id}
        save_edge_node(node_id=body.node_id, name=body.node_id)
    save_device(device_id=body.id, name=body.name, node_id=body.node_id, extra=body.extra)
    return {"ok": True}


@router.post("/devices/telemetry", status_code=200)
async def post_telemetry(body: _DeviceTelemetryRequest):
    """
    Called by a device every few seconds to push a readings dict.
    Fans out the payload to every subscribed browser WebSocket.
    No auth required — devices may not have tokens.
    """
    from datetime import datetime as _dt
    now = _dt.utcnow().isoformat()
    snapshot = {"ts": now, "readings": body.readings}

    # Update in-memory registry
    if body.device_id in _devices:
        _devices[body.device_id]["last_seen"] = now
        _devices[body.device_id]["status"] = "online"
    _telemetry[body.device_id].append(snapshot)

    # Persist to DB (non-blocking side-effect)
    save_telemetry(device_id=body.device_id, readings=body.readings)

    # Fan out to subscribed WebSockets
    dead: list = []
    for ws in list(_ws_subs.get(body.device_id, set())):
        try:
            await ws.send_json(snapshot)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_subs[body.device_id].discard(ws)

    return {"ok": True}


@router.get("/devices/{device_id}/telemetry")
def get_device_telemetry(device_id: str, limit: int = 60,
                         _cu: dict = Depends(get_current_user)):
    """Return recent telemetry for a device (history preload)."""
    # Try DB first; fall back to in-memory deque
    db_rows = get_db_telemetry(device_id, limit)
    if db_rows is not None:
        return db_rows
    rows = list(_telemetry.get(device_id, deque()))
    return rows[-limit:] if len(rows) > limit else rows


@router.websocket("/devices/{device_id}/stream")
async def device_stream(websocket: WebSocket, device_id: str):
    """Browser subscribes here for live telemetry from a specific device."""
    await websocket.accept()
    _ws_subs[device_id].add(websocket)
    try:
        # Send latest snapshot immediately so the UI isn't blank
        latest = list(_telemetry.get(device_id, []))
        if latest:
            await websocket.send_json(latest[-1])
        # Keep the connection alive; data arrives via post_telemetry fanout
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_subs[device_id].discard(websocket)


@router.post("/devices/{device_id}/flexibility")
def estimate_flexibility(device_id: str, _cu: dict = Depends(get_current_user)):
    """
    Ask the agent running on the device to compute flexibility potential.
    The agent exposes a small HTTP server on port 8765 with a /flexibility endpoint.
    For real hardware, replace the dummy script inside the agent with actual measurements.
    """
    import requests as _req

    device = _devices.get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    agent_ip   = device.get("agent_ip")
    agent_port = device.get("agent_port", 8765)

    if not agent_ip:
        raise HTTPException(status_code=503, detail="Agent IP unknown — re-register the device")

    try:
        resp = _req.post(f"http://{agent_ip}:{agent_port}/flexibility", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        data["device_id"] = device_id   # ensure it's always present
        return data
    except _req.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Could not reach agent — is it running?")
    except _req.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Agent timed out")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent error: {exc}")
