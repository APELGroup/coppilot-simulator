import { createFileRoute, useLocation } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Activity, RefreshCw, Zap } from "lucide-react";
import { AppShell, PageHeader } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { apiFetch, API_BASE } from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/connection-tool-devices")({
  head: () => ({
    meta: [
      { title: "Connection with Tool Devices — DT Lab" },
      { name: "description", content: "Connect external tool devices to your workspace." },
    ],
  }),
  component: ConnectionToolDevicesPage,
});

// ── Types ─────────────────────────────────────────────────────────────────────

interface PiDevice {
  id: string;
  name: string;
  node_id: string | null;
  active: boolean;
  power_p: number | null;
  power_q: number | null;
  last_seen: string | null;
}

interface EdgeNode {
  id: string;
  name: string;
  devices: PiDevice[];
}

interface PolytopeStep {
  t: string;
  vertices: [number, number][];
}

interface FlexibilityResult {
  node_id: string;
  timestamps: string[];
  devices: Record<string, PolytopeStep[]>;
  combined: PolytopeStep[];
  bus_labels: Record<string, string>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, unit: string) {
  if (v == null) return "—";
  return `${v.toFixed(2)} ${unit}`;
}

// ── Pi row ────────────────────────────────────────────────────────────────────

function PiRow({ pi }: { pi: PiDevice }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border px-4 py-3">
      <span
        className={cn(
          "h-2.5 w-2.5 shrink-0 rounded-full",
          pi.active ? "bg-green-500" : "bg-muted-foreground/40",
        )}
      />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{pi.name}</div>
        <div className="text-xs text-muted-foreground">{pi.id}</div>
      </div>
      <div className="text-right shrink-0 space-y-0.5">
        <div className="text-xs tabular-nums">
          <span className="text-muted-foreground">P </span>
          <span className="font-medium">{fmt(pi.power_p, "kW")}</span>
        </div>
        <div className="text-xs tabular-nums">
          <span className="text-muted-foreground">Q </span>
          <span className="font-medium">{fmt(pi.power_q, "kVAR")}</span>
        </div>
      </div>
      <Badge variant={pi.active ? "default" : "secondary"} className="text-xs shrink-0">
        {pi.active ? "Active" : "Offline"}
      </Badge>
    </div>
  );
}

// ── FOR polytope chart ────────────────────────────────────────────────────────

const CHART_COLORS = [
  { stroke: "#1a56db", fill: "#1a56db" },   // Pi #1 — brand blue
  { stroke: "#10b981", fill: "#10b981" },   // Pi #2 — green
  { stroke: "#f59e0b", fill: "#f59e0b" },   // Pi #3 — amber
  { stroke: "#8b5cf6", fill: "#8b5cf6" },   // Pi #4 — purple
];

function PolytopeChart({
  vertices,
  timestamp,
  colorIndex = 0,
}: {
  vertices: [number, number][];
  timestamp: string;
  colorIndex?: number;
}) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; p: number; q: number } | null>(null);

  const { stroke, fill } = CHART_COLORS[colorIndex % CHART_COLORS.length];
  const W = 400, H = 300, PAD = 36;
  const ps = vertices.map(v => v[0]);
  const qs = vertices.map(v => v[1]);
  const pad = 0.5;
  const pAbsMax = Math.max(Math.abs(Math.min(...ps)), Math.abs(Math.max(...ps))) + pad;
  const qAbsMax = Math.max(Math.abs(Math.min(...qs)), Math.abs(Math.max(...qs))) + pad;
  const pMin = -pAbsMax, pMax = pAbsMax;
  const qMin = -qAbsMax, qMax = qAbsMax;

  const sx = (p: number) => PAD + ((p - pMin) / (pMax - pMin)) * (W - 2 * PAD);
  const sy = (q: number) => H - PAD - ((q - qMin) / (qMax - qMin)) * (H - 2 * PAD);

  const pts = vertices.map(([p, q]) => `${sx(p)},${sy(q)}`).join(" ");
  const ox = sx(0), oy = sy(0);

  const pStep = Math.ceil(pAbsMax);
  const qStep = Math.ceil(qAbsMax);
  const pTicks = Array.from({ length: pStep * 2 + 1 }, (_, i) => i - pStep).filter(v => v !== 0);
  const qTicks = Array.from({ length: qStep * 2 + 1 }, (_, i) => i - qStep).filter(v => v !== 0);

  // Tooltip box dimensions
  const TW = 112, TH = 40;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      style={{ fontFamily: "inherit", display: "block", width: "100%" }}
    >
      {/* Grid lines */}
      {pTicks.map((p) => (
        <line key={`gp${p}`} x1={sx(p)} y1={PAD} x2={sx(p)} y2={H - PAD}
          stroke="var(--border)" strokeWidth={0.5} strokeDasharray="2 2" />
      ))}
      {qTicks.map((q) => (
        <line key={`gq${q}`} x1={PAD} y1={sy(q)} x2={W - PAD} y2={sy(q)}
          stroke="var(--border)" strokeWidth={0.5} strokeDasharray="2 2" />
      ))}

      {/* Axes */}
      <line x1={PAD} y1={oy} x2={W - PAD} y2={oy} stroke="currentColor" strokeWidth={1} />
      <line x1={ox} y1={PAD} x2={ox} y2={H - PAD} stroke="currentColor" strokeWidth={1} />

      {/* Axis arrows */}
      <polygon points={`${W - PAD},${oy} ${W - PAD - 6},${oy - 3} ${W - PAD - 6},${oy + 3}`}
        fill="currentColor" />
      <polygon points={`${ox},${PAD} ${ox - 3},${PAD + 6} ${ox + 3},${PAD + 6}`}
        fill="currentColor" />

      {/* Tick labels */}
      {pTicks.map((p) => (
        <text key={`tp${p}`} x={sx(p)} y={oy + 11} fontSize={8}
          fill="var(--muted-foreground)" textAnchor="middle">{p}</text>
      ))}
      {qTicks.filter(q => q !== 0).map((q) => (
        <text key={`tq${q}`} x={ox - 5} y={sy(q) + 3} fontSize={8}
          fill="var(--muted-foreground)" textAnchor="end">{q}</text>
      ))}

      {/* FOR polygon */}
      {pts && (
        <polygon points={pts} fill={fill} fillOpacity={0.2} stroke={stroke} strokeWidth={1.2} />
      )}

      {/* Vertex hit areas — invisible circles, trigger tooltip on hover */}
      {vertices.map(([p, q], i) => {
        const cx = sx(p), cy = sy(q);
        // flip tooltip left if too close to right edge
        const tx = cx + TW + 12 > W ? cx - TW - 8 : cx + 8;
        const ty = Math.max(PAD, Math.min(cy - TH / 2, H - PAD - TH));
        return (
          <g key={i}>
            <circle cx={cx} cy={cy} r={8} fill="transparent" style={{ cursor: "crosshair" }}
              onMouseEnter={() => setTooltip({ x: tx, y: ty, p, q })}
              onMouseLeave={() => setTooltip(null)}
            />
          </g>
        );
      })}

      {/* Tooltip */}
      {tooltip && (
        <g style={{ pointerEvents: "none" }}>
          <rect x={tooltip.x} y={tooltip.y} width={TW} height={TH} rx={5}
            fill="#1e293b" opacity={0.93} />
          <text x={tooltip.x + 9} y={tooltip.y + 15} fontSize={10} fill="#f8fafc" fontWeight={600}>
            P: {tooltip.p.toFixed(3)} kW
          </text>
          <text x={tooltip.x + 9} y={tooltip.y + 30} fontSize={10} fill="#94a3b8">
            Q: {tooltip.q.toFixed(3)} kVAR
          </text>
        </g>
      )}

      {/* Axis labels */}
      <text x={W - PAD - 4} y={oy - 7} fontSize={9} fill="currentColor" fontWeight={500} textAnchor="end">
        P (kW)
      </text>
      <text x={ox + 5} y={PAD + 9} fontSize={9} fill="currentColor" fontWeight={500}>
        Q (kVAR)
      </text>
    </svg>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function ConnectionToolDevicesPage() {
  const [nodes, setNodes] = useState<EdgeNode[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string>("");
  const [estimating, setEstimating] = useState(false);
  const [result, setResult] = useState<FlexibilityResult | null>(null);
  const [topoUrl, setTopoUrl] = useState<string | null>(null);
  const [topoNetwork, setTopoNetwork] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [forPlotUrl, setForPlotUrl] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"3d" | "2d">("3d");
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const location = useLocation();
  const isActive = location.pathname === "/connection-tool-devices";

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;
  const allActive = (selectedNode?.devices.length ?? 0) >= 2 && (selectedNode?.devices.every((d) => d.active) ?? false);

  async function fetchNodes() {
    try {
      const res = await apiFetch(`${API_BASE}/edge-nodes`);
      if (res.ok) setNodes(await res.json());
    } catch {
      // silently ignore
    }
  }

  useEffect(() => {
    if (!isActive) return;
    fetchNodes();
    const id = setInterval(fetchNodes, 15_000);
    return () => clearInterval(id);
  }, [isActive]);

  // Reset everything when node changes
  useEffect(() => {
    setResult(null);
    setStep(0);
    setTopoUrl(null);
    setTopoNetwork(null);
  }, [selectedNodeId]);

  // Fetch topology only once both Pis are active — then keep it even if one goes offline
  useEffect(() => {
    if (!allActive || !selectedNodeId || topoUrl) return;
    apiFetch(`${API_BASE}/edge-nodes/${selectedNodeId}/topology`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.url) setTopoUrl(`${API_BASE}${data.url}`);
        if (data?.network) setTopoNetwork(data.network);
      })
      .catch(() => {});
  }, [allActive, selectedNodeId]);

  // Reset slider when new result arrives
  useEffect(() => {
    setStep(0);
  }, [result]);

  // Send highlight step to iframe via postMessage
  useEffect(() => {
    if (!iframeRef.current?.contentWindow || !result) return;
    iframeRef.current.contentWindow.postMessage(
      { type: "highlight", step, n: result.combined.length },
      "*",
    );
  }, [step, result]);

  // Build 3D Plotly blob when result changes
  useEffect(() => {
    if (forPlotUrl) URL.revokeObjectURL(forPlotUrl);
    if (!result) { setForPlotUrl(null); return; }

    const traces: object[] = [];
    const n = result.combined.length;

    const allP = result.combined.flatMap(s => s.vertices.map(v => v[0]));
    const allQ = result.combined.flatMap(s => s.vertices.map(v => v[1]));
    const pExt = Math.max(Math.abs(Math.min(...allP)), Math.abs(Math.max(...allP))) * 1.15;
    const qExt = Math.max(Math.abs(Math.min(...allQ)), Math.abs(Math.max(...allQ))) * 1.15;

    // Color interpolation: deep blue → violet
    const lerp = (a: number, b: number, t: number) => Math.round(a + (b - a) * t);
    const color = (t: number) => {
      const r = lerp(29, 124, t/(n-1)), g = lerp(78, 58, t/(n-1)), b = lerp(216, 237, t/(n-1));
      return `rgb(${r},${g},${b})`;
    };

    // P=0 plane (Q–Time): light blue
    traces.push({ type:"mesh3d",
      x:[0,0,0,0], y:[0,n-1,n-1,0], z:[-qExt,-qExt,qExt,qExt],
      i:[0,0], j:[1,2], k:[2,3],
      color:"#bfdbfe", opacity:0.45, showlegend:true, name:"P = 0 plane", hoverinfo:"skip", flatshading:true });
    // P=0 plane border
    traces.push({ type:"scatter3d",
      x:[0,0,0,0,0], y:[0,n-1,n-1,0,0], z:[-qExt,-qExt,qExt,qExt,-qExt],
      mode:"lines", line:{color:"#93c5fd",width:1.5}, showlegend:false, hoverinfo:"skip" });

    // Q=0 plane (P–Time): light green
    traces.push({ type:"mesh3d",
      x:[-pExt,pExt,pExt,-pExt], y:[0,0,n-1,n-1], z:[0,0,0,0],
      i:[0,0], j:[1,2], k:[2,3],
      color:"#bbf7d0", opacity:0.45, showlegend:true, name:"Q = 0 plane", hoverinfo:"skip", flatshading:true });
    // Q=0 plane border
    traces.push({ type:"scatter3d",
      x:[-pExt,pExt,pExt,-pExt,-pExt], y:[0,0,n-1,n-1,0], z:[0,0,0,0,0],
      mode:"lines", line:{color:"#86efac",width:1.5}, showlegend:false, hoverinfo:"skip" });

    result.combined.forEach((step, t) => {
      const c = color(t);
      const vx = step.vertices.map(v => v[0]);
      const vz = step.vertices.map(v => v[1]);
      const vy = vx.map(() => t);
      const k = vx.length;

      // Filled polygon (mesh)
      const ii = Array.from({length: k - 2}, () => 0);
      const jj = Array.from({length: k - 2}, (_, i) => i + 1);
      const kk = Array.from({length: k - 2}, (_, i) => i + 2);
      traces.push({
        type:"mesh3d", x:vx, y:vy, z:vz,
        i:ii, j:jj, k:kk,
        color:c, opacity:0.18, flatshading:true,
        showlegend:false, hoverinfo:"skip",
      });

      // Polygon boundary with hover
      const hx = [...vx, vx[0]], hy = [...vy, t], hz = [...vz, vz[0]];
      traces.push({
        type:"scatter3d", x:hx, y:hy, z:hz, mode:"lines",
        line:{ color:c, width:3 },
        showlegend:false,
        hovertemplate:"<b>t = %{y} min</b><br>P: %{x:.2f} kW<br>Q: %{z:.2f} kVAR<extra></extra>",
      });
    });

    const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"/>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"><\/script>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{width:100%;height:100%;background:#f8fafc}
  .hoverlayer .hovertext rect{fill:#1e293b!important;opacity:0.92!important}
  .hoverlayer .hovertext text{fill:#f8fafc!important;font-size:12px!important}
</style>
</head><body>
<div id="p" style="width:100%;height:100%"></div>
<script>
Plotly.newPlot("p",${JSON.stringify(traces)},{
  margin:{l:0,r:0,t:0,b:80},
  paper_bgcolor:"#f8fafc",
  hoverlabel:{bgcolor:"#1e293b",font:{color:"#f8fafc",size:12},bordercolor:"#334155"},
  scene:{
    xaxis:{title:"P (kW)",titlefont:{size:12,color:"#334155"},tickfont:{size:10},
           gridcolor:"#e2e8f0",zerolinecolor:"#94a3b8",zerolinewidth:2,showspikes:false},
    yaxis:{title:"Time (min)",titlefont:{size:12,color:"#334155"},tickfont:{size:10},
           gridcolor:"#e2e8f0",showspikes:false},
    zaxis:{title:"Q (kVAR)",titlefont:{size:12,color:"#334155"},tickfont:{size:10},
           gridcolor:"#e2e8f0",zerolinecolor:"#94a3b8",zerolinewidth:2,showspikes:false},
    camera:{eye:{x:1.7,y:-1.6,z:0.8}},
    bgcolor:"#f8fafc",
    aspectmode:"manual",
    aspectratio:{x:1.4,y:1.5,z:0.9},
  },
  showlegend:true,
  legend:{x:0.01,y:0.98,bgcolor:"rgba(248,250,252,0.85)",bordercolor:"#e2e8f0",borderwidth:1,font:{size:11,color:"#334155"}},
},{displayModeBar:false,responsive:true});

// Highlight on postMessage
const N_PLANES = 4; // plane traces before polygon traces
const N = ${n};
window.addEventListener('message', function(e) {
  if (!e.data || e.data.type !== 'highlight') return;
  const s = e.data.step;
  for (let t = 0; t < N; t++) {
    const meshIdx = N_PLANES + t * 2;
    const lineIdx = N_PLANES + t * 2 + 1;
    const isHl = t === s;
    Plotly.restyle('p', { opacity: isHl ? 0.55 : 0.18 }, [meshIdx]);
    Plotly.restyle('p', { 'line.width': isHl ? 7 : 2.5, 'line.color': isHl ? '#f59e0b' : null }, [lineIdx]);
  }
});
<\/script></body></html>`;

    const blob = new Blob([html], { type: "text/html" });
    setForPlotUrl(URL.createObjectURL(blob));
  }, [result]);

  async function handleEstimate() {
    if (!selectedNodeId) return;
    setEstimating(true);
    setResult(null);
    try {
      const res = await apiFetch(
        `${API_BASE}/edge-nodes/${selectedNodeId}/flexibility`,
        { method: "POST" },
      );
      if (res.ok) setResult(await res.json());
    } catch {
      // error handled silently; user can retry
    } finally {
      setEstimating(false);
    }
  }

  const currentCombined = result?.combined[step] ?? null;
  const deviceNames = result ? Object.keys(result.devices) : [];

  return (
    <AppShell>
      <PageHeader
        title="Connection with Edge devices"
        description="Monitor edge nodes and estimate flexibility potential."
      />

      <Card className="p-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-1">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Activity className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold">Edge Nodes</div>
            <div className="text-xs text-muted-foreground">
              Select a node to view its Raspberry Pi devices and estimate flexibility
            </div>
          </div>
        </div>

        <Separator className="my-5" />

        <div className="grid gap-8 lg:grid-cols-[280px_1fr] lg:items-start">
          {/* ── Left panel ─────────────────────────────────────────────── */}
          <div className="space-y-4">
            {/* Node selector */}
            <div className="space-y-2">
              <Label>Select Edge Node</Label>
              <div className="flex gap-2">
                <Select value={selectedNodeId} onValueChange={setSelectedNodeId}>
                  <SelectTrigger className="flex-1">
                    <SelectValue
                      placeholder={
                        nodes.length === 0 ? "No nodes registered" : "Choose a node…"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {nodes.map((n) => (
                      <SelectItem key={n.id} value={n.id}>
                        {n.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  size="icon"
                  variant="outline"
                  onClick={fetchNodes}
                  title="Refresh"
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* Pi list */}
            {selectedNode && selectedNode.devices.length > 0 && (
              <div className="space-y-2">
                <Label>Raspberry Pi Devices</Label>
                <div className="space-y-2">
                  {selectedNode.devices.map((pi) => (
                    <PiRow key={pi.id} pi={pi} />
                  ))}
                </div>
              </div>
            )}

            {selectedNode && selectedNode.devices.length === 0 && (
              <p className="text-xs text-muted-foreground border border-dashed rounded-md p-3">
                No devices registered in this node yet.
              </p>
            )}

            {!selectedNodeId && nodes.length === 0 && (
              <p className="text-xs text-muted-foreground border border-dashed rounded-md p-3">
                No nodes yet. Run <code className="font-mono">agent.py</code> with{" "}
                <code className="font-mono">--node</code> to register one.
              </p>
            )}

            {/* Estimate button */}
            {selectedNode && (
              <Button
                className="w-full"
                disabled={!allActive || estimating}
                onClick={handleEstimate}
              >
                <Zap className="h-4 w-4 mr-2" />
                {estimating ? "Estimating…" : "Estimate Flexibility Potential"}
              </Button>
            )}

            {selectedNode && !allActive && (
              <p className="text-xs text-muted-foreground text-center">
                All devices must be active to enable estimation.
              </p>
            )}
          </div>

          {/* ── Right panel ───────────────────────────────────────────── */}
          <div className="space-y-4">

            {/* ── Topology ── */}
            {selectedNode && (allActive || topoUrl) && (
              <div className="space-y-2">
                <div className="flex items-baseline gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Network Topology
                  </p>
                  {topoNetwork && (
                    <span className="text-xs font-mono text-muted-foreground truncate">{topoNetwork}</span>
                  )}
                </div>
                <div className="rounded-xl border border-border overflow-hidden">
                  {topoUrl ? (
                    <iframe
                      src={topoUrl}
                      className="w-full h-[260px] block"
                      title="Network Topology"
                    />
                  ) : (
                    <div className="flex items-center justify-center h-[260px] text-sm text-muted-foreground bg-muted/20">
                      Loading topology…
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── FOR ── */}
            {result && currentCombined ? (
              <div className="space-y-4">
                {/* Title + view toggle */}
                <div className="flex items-center gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex-1">
                    Flexibility Operating Region — CCP (MV/LV)
                  </p>
                  <div className="flex rounded-md border border-border overflow-hidden text-xs">
                    <button
                      onClick={() => setViewMode("2d")}
                      className={cn(
                        "px-3 py-1.5 font-medium transition-colors",
                        viewMode === "2d"
                          ? "bg-primary text-primary-foreground"
                          : "bg-background text-muted-foreground hover:bg-muted"
                      )}
                    >
                      2D
                    </button>
                    <button
                      onClick={() => setViewMode("3d")}
                      className={cn(
                        "px-3 py-1.5 font-medium transition-colors border-l border-border",
                        viewMode === "3d"
                          ? "bg-primary text-primary-foreground"
                          : "bg-background text-muted-foreground hover:bg-muted"
                      )}
                    >
                      3D
                    </button>
                  </div>
                  <Badge variant="outline" className="tabular-nums font-mono text-xs">
                    15-min horizon
                  </Badge>
                </div>

                {/* 2D view */}
                {viewMode === "2d" && (
                  <div className="space-y-3">
                    <div className="rounded-xl border border-border overflow-hidden bg-muted/10 p-4 flex justify-center">
                      <div style={{ width: "72%" }}>
                        <PolytopeChart
                          vertices={currentCombined.vertices}
                          timestamp={currentCombined.t}
                          colorIndex={0}
                        />
                      </div>
                    </div>
                    {/* Time slider */}
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground w-10 tabular-nums">{result.combined[0].t}</span>
                      <input
                        type="range"
                        min={0}
                        max={result.combined.length - 1}
                        value={step}
                        onChange={e => setStep(Number(e.target.value))}
                        className="flex-1 accent-primary h-1.5 cursor-pointer"
                      />
                      <span className="text-xs text-muted-foreground w-10 text-right tabular-nums">
                        {result.combined.at(-1)?.t}
                      </span>
                    </div>
                  </div>
                )}

                {/* 3D view */}
                {viewMode === "3d" && (
                  <div className="rounded-xl border border-border overflow-hidden bg-muted/10">
                    {forPlotUrl
                      ? <iframe ref={iframeRef} src={forPlotUrl} className="w-full h-[500px] block" title="FOR 3D" />
                      : <div className="flex items-center justify-center h-[380px] text-sm text-muted-foreground">Generating plot…</div>
                    }
                  </div>
                )}

                {/* Legend */}
                <div className="rounded-lg border border-border bg-muted/10 px-4 py-3 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
                  <div className="flex items-center gap-1.5">
                    <span
                      className="h-3 w-3 rounded-sm border shrink-0"
                      style={{
                        background: CHART_COLORS[0].fill + "33",
                        borderColor: CHART_COLORS[0].stroke,
                      }}
                    />
                    <span>Aggregated FOR — CCP</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-foreground">P &gt; 0</span>
                    <span>Power consumption</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-foreground">P &lt; 0</span>
                    <span>Reverse flow to grid</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-foreground">Q &gt; 0</span>
                    <span>Reactive power absorption</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-foreground">Q &lt; 0</span>
                    <span>Reactive power injection</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center rounded-xl border border-dashed border-border bg-muted/20 min-h-[200px]">
                <p className="text-sm text-muted-foreground text-center px-6">
                  {selectedNode
                    ? allActive
                      ? "Press \"Estimate Flexibility Potential\" to see results."
                      : "All devices must be active to run the estimation."
                    : "Select an Edge Node to get started."}
                </p>
              </div>
            )}
          </div>
        </div>
      </Card>
    </AppShell>
  );
}
