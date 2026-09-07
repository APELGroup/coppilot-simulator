"""Edge node listing, flexibility estimation, and topology-plot routes."""
import simbench as sb
import plotly.graph_objects as go
from pandapower.plotting.plotly import simple_plotly as pp_simple_plotly
from fastapi import APIRouter, Depends, HTTPException

from auth_utils import get_current_user
from shared_state import _devices, _edge_nodes, _telemetry, PLOTS_DIR, style_traces, build_plot_html

router = APIRouter()


@router.get("/edge-nodes")
def list_edge_nodes(_cu: dict = Depends(get_current_user)):
    """Return all edge nodes, each with their devices and latest P/Q readings."""
    from datetime import datetime as _dt, timezone as _tz

    result = []
    for node in _edge_nodes.values():
        devices = []
        for dev in _devices.values():
            if dev.get("node_id") != node["id"]:
                continue
            # Determine active status: last_seen within 60 seconds
            last_seen_str = dev.get("last_seen")
            active = False
            if last_seen_str:
                try:
                    last_seen_dt = _dt.fromisoformat(last_seen_str)
                    age = (_dt.utcnow() - last_seen_dt).total_seconds()
                    active = age < 10
                except ValueError:
                    pass

            # Latest P/Q from telemetry
            latest = list(_telemetry.get(dev["id"], []))
            readings = latest[-1]["readings"] if latest else {}
            devices.append({
                **dev,
                "active": active,
                "power_p": readings.get("power_p"),
                "power_q": readings.get("power_q"),
            })
        result.append({**node, "devices": devices})
    return result


def _minkowski_sum(v1: list, v2: list) -> list:
    """
    Compute the Minkowski sum of two convex polygons given as vertex lists [[p,q], ...].
    Returns vertices of the resulting polygon sorted by angle.
    """
    import numpy as np
    from scipy.spatial import ConvexHull
    pts = np.array([[a[0] + b[0], a[1] + b[1]] for a in v1 for b in v2])
    hull = ConvexHull(pts)
    verts = pts[hull.vertices]
    center = verts.mean(axis=0)
    angles = np.arctan2(verts[:, 1] - center[1], verts[:, 0] - center[0])
    return verts[np.argsort(angles)].tolist()


@router.post("/edge-nodes/{node_id}/flexibility")
def estimate_node_flexibility(node_id: str, _cu: dict = Depends(get_current_user)):
    """
    Call every device in the node, collect each one's polytope series,
    and return the Minkowski sum across devices as a single combined FOR per time step.
    """
    import requests as _req
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if node_id not in _edge_nodes:
        raise HTTPException(status_code=404, detail="Edge node not found")

    devices = [d for d in _devices.values() if d.get("node_id") == node_id]
    if not devices:
        raise HTTPException(status_code=404, detail="No devices in this node")

    def _call(dev: dict):
        ip   = dev.get("agent_ip")
        port = dev.get("agent_port", 8765)
        print(f"[flexibility] calling {dev['id']} at {ip}:{port}")
        if not ip:
            raise ValueError(f"Agent IP unknown for {dev['id']} — re-register the device")
        resp = _req.post(f"http://{ip}:{port}/flexibility", timeout=10)
        resp.raise_for_status()
        return resp.json()

    # Collect individual polytopes per device, then compute combined (Minkowski sum)
    device_polytopes: dict[str, list] = {}   # name → [vertices per step]
    timestamps: list[str] = []

    with ThreadPoolExecutor(max_workers=len(devices)) as pool:
        futures = {pool.submit(_call, dev): dev for dev in devices}
        for future in as_completed(futures):
            dev = futures[future]
            try:
                data = future.result()
                if not timestamps:
                    timestamps = data["timestamps"]
                device_polytopes[dev["name"]] = [
                    step["vertices"] for step in data["polytopes"]
                ]
            except _req.exceptions.ConnectionError as exc:
                raise HTTPException(status_code=503, detail=f"Could not reach agent: {exc}")
            except _req.exceptions.Timeout:
                raise HTTPException(status_code=504, detail="An agent timed out")
            except Exception as exc:
                print(f"[flexibility] error: {type(exc).__name__}: {exc}")
                raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")

    # Compute combined FOR (Minkowski sum across all devices per time step)
    combined: list = []
    for i in range(len(timestamps)):
        verts = None
        for name_verts in device_polytopes.values():
            verts = name_verts[i] if verts is None else _minkowski_sum(verts, name_verts[i])
        combined.append(verts)

    def to_steps(verts_list: list) -> list:
        return [{"t": ts, "vertices": v} for ts, v in zip(timestamps, verts_list)]

    # Build bus label map: device name → "Bus {idx}" using _TOPO_PI_BUSES order
    ordered_names = [dev["name"] for dev in devices]
    bus_labels = {
        name: f"Bus {_TOPO_PI_BUSES[i]}" if i < len(_TOPO_PI_BUSES) else f"Bus {i}"
        for i, name in enumerate(ordered_names)
    }

    return {
        "node_id": node_id,
        "timestamps": timestamps,
        "devices": {name: to_steps(vl) for name, vl in device_polytopes.items()},
        "combined": to_steps(combined),
        "bus_labels": bus_labels,
    }


# Hardcoded for the 1-LV-rural1--0-no_sw SimBench network used in DT Lab.
_TOPO_NETWORK   = "1-LV-rural1--0-no_sw"
_TOPO_TRAFO_IDX = 0          # MV/LV transformer index → shown as "Edge Node"
_TOPO_PI_BUSES  = [3, 0]     # LV bus indices where the two Raspberry Pis are connected
_PI_COLORS      = ["#10b981", "#10b981"]   # green for both Pis


@router.get("/edge-nodes/{node_id}/topology")
def get_node_topology(node_id: str, _cu: dict = Depends(get_current_user)):
    """
    Generate (or regenerate) an annotated Plotly topology map for the edge node.
    Highlights the MV/LV transformer as "Edge Node" and the two Pi buses.
    Returns {"url": "/plots/topo-<node_id>.html"}.
    """
    if node_id not in _edge_nodes:
        raise HTTPException(status_code=404, detail="Edge node not found")

    # Load network topology (no power flow needed)
    net = sb.get_simbench_net(_TOPO_NETWORK)

    # Base plot + styling
    fig = pp_simple_plotly(net, auto_open=False)
    fig = style_traces(fig)

    # ── Edge Node: midpoint between transformer HV and LV buses ──────────────
    trafo = net.trafo.iloc[_TOPO_TRAFO_IDX]
    hv = net.bus_geodata.loc[trafo["hv_bus"]]
    lv = net.bus_geodata.loc[trafo["lv_bus"]]
    tx = (hv["x"] + lv["x"]) / 2
    ty = (hv["y"] + lv["y"]) / 2
    fig.add_trace(go.Scatter(
        x=[tx], y=[ty],
        mode="markers+text",
        name="Edge Node (CCP)",
        marker=dict(color="#f59e0b", size=22, symbol="triangle-up",
                    line=dict(color="#ffffff", width=2)),
        text=["Edge Node (CCP)"],
        textposition="middle right",
        textfont=dict(size=11, color="#f59e0b"),
        hoverinfo="name",
    ))

    # ── Pi buses ──────────────────────────────────────────────────────────────
    # Use actual device IDs for labels (ordered by registration)
    node_devices = sorted(
        [d for d in _devices.values() if d.get("node_id") == node_id],
        key=lambda d: d["id"],
    )
    for i, bus_idx in enumerate(_TOPO_PI_BUSES):
        bx = net.bus_geodata.loc[bus_idx, "x"]
        by = net.bus_geodata.loc[bus_idx, "y"]
        pi_label = node_devices[i]["id"] if i < len(node_devices) else f"Pi #{i + 1}"
        fig.add_trace(go.Scatter(
            x=[bx], y=[by],
            mode="markers+text",
            name=pi_label,
            marker=dict(color=_PI_COLORS[i], size=16, symbol="circle",
                        line=dict(color="#ffffff", width=2)),
            text=[pi_label],
            textposition="top center",
            textfont=dict(size=11, color=_PI_COLORS[i]),
            hoverinfo="name",
        ))

    # ── Auto-zoom to transformer + Pi buses ───────────────────────────────────
    xs = [tx] + [net.bus_geodata.loc[b, "x"] for b in _TOPO_PI_BUSES]
    ys = [ty] + [net.bus_geodata.loc[b, "y"] for b in _TOPO_PI_BUSES]
    pad_x = (max(xs) - min(xs)) * 0.4 or 0.001
    pad_y = (max(ys) - min(ys)) * 0.4 or 0.001
    fig.update_layout(
        xaxis=dict(range=[min(xs) - pad_x, max(xs) + pad_x]),
        yaxis=dict(range=[min(ys) - pad_y, max(ys) + pad_y]),
    )

    # ── Write HTML and return URL ─────────────────────────────────────────────
    html = build_plot_html(fig, _TOPO_NETWORK, hide_modebar=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PLOTS_DIR / f"topo-{node_id}.html"
    out_path.write_text(html, encoding="utf-8")

    return {"url": f"/plots/topo-{node_id}.html", "network": _TOPO_NETWORK}
