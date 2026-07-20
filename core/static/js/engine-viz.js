/**
 * AbsorbAI Engine Visualization Module
 * Renders all 10-layer engine outputs as interactive charts/graphs.
 * Pure Canvas 2D — no external dependencies.
 */

const VIZ = {
  colors: {
    teal: '#14a6aa', tealDim: 'rgba(20,166,170,0.3)',
    gold: '#c8a96e', goldDim: 'rgba(200,169,110,0.3)',
    red: '#f08080', redDim: 'rgba(240,128,128,0.2)',
    green: '#7dce82', greenDim: 'rgba(125,206,130,0.2)',
    white: '#f0ede8', muted: '#7a8899',
    bg: '#0a1628', card: 'rgba(255,255,255,0.035)',
    grid: 'rgba(255,255,255,0.06)',
    bands: [
      'rgba(20,166,170,0.08)', 'rgba(20,166,170,0.15)',
      'rgba(20,166,170,0.30)', 'rgba(20,166,170,0.15)', 'rgba(20,166,170,0.08)',
    ],
  },
  dpr: window.devicePixelRatio || 1,
};

function _setupCanvas(canvas, w, h) {
  canvas.width = w * VIZ.dpr;
  canvas.height = h * VIZ.dpr;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(VIZ.dpr, VIZ.dpr);
  return ctx;
}

// ─── 1. CONCENTRATION-TIME CURVE ──────────────────────────────────────────────

function renderConcentrationCurve(containerId, drugName, simData, mcBands, pdParams) {
  const container = document.getElementById(containerId);
  if (!container || !simData?.t?.length) return;

  container.innerHTML = '';
  const W = container.clientWidth || 520, H = 260;
  const canvas = document.createElement('canvas');
  container.appendChild(canvas);
  const ctx = _setupCanvas(canvas, W, H);

  const pad = { l: 55, r: 20, t: 30, b: 40 };
  const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;

  const t = simData.t, c = simData.c;
  const tMax = Math.max(...t), cAll = [...c];

  if (mcBands?.p95) cAll.push(...mcBands.p95);
  const cMax = Math.max(...cAll.filter(v => isFinite(v)), 0.001) * 1.15;

  const tx = v => pad.l + (v / tMax) * pw;
  const ty = v => pad.t + ph - (v / cMax) * ph;

  // Grid
  ctx.strokeStyle = VIZ.colors.grid;
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (ph / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + pw, y); ctx.stroke();
  }
  for (let h = 0; h <= tMax; h += 12) {
    const x = tx(h);
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ph); ctx.stroke();
  }

  // MC uncertainty bands (p5-p95, p25-p75)
  if (mcBands?.t?.length) {
    const bandPairs = [['p5', 'p95', VIZ.colors.bands[0]], ['p25', 'p75', VIZ.colors.bands[2]]];
    for (const [lo, hi, fill] of bandPairs) {
      if (!mcBands[lo] || !mcBands[hi]) continue;
      ctx.fillStyle = fill;
      ctx.beginPath();
      const bt = mcBands.t;
      for (let i = 0; i < bt.length; i++) {
        const x = tx(bt[i]), y = ty(mcBands[hi][i]);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      for (let i = bt.length - 1; i >= 0; i--) {
        ctx.lineTo(tx(bt[i]), ty(mcBands[lo][i]));
      }
      ctx.closePath(); ctx.fill();
    }
    // MC median
    if (mcBands.median) {
      ctx.strokeStyle = 'rgba(20,166,170,0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      mcBands.t.forEach((v, i) => {
        const x = tx(v), y = ty(mcBands.median[i]);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // Therapeutic window (EC50 line)
  if (pdParams?.ec50) {
    const ec50y = ty(pdParams.ec50);
    if (ec50y > pad.t && ec50y < pad.t + ph) {
      ctx.strokeStyle = VIZ.colors.goldDim;
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      ctx.beginPath(); ctx.moveTo(pad.l, ec50y); ctx.lineTo(pad.l + pw, ec50y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = VIZ.colors.gold;
      ctx.font = '10px "DM Mono", monospace';
      ctx.fillText('EC₅₀ = ' + pdParams.ec50.toFixed(2), pad.l + 4, ec50y - 4);
    }
  }

  // Main concentration line
  ctx.strokeStyle = VIZ.colors.teal;
  ctx.lineWidth = 2;
  ctx.shadowColor = VIZ.colors.teal;
  ctx.shadowBlur = 6;
  ctx.beginPath();
  for (let i = 0; i < t.length; i++) {
    const x = tx(t[i]), y = ty(c[i]);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.shadowBlur = 0;

  // Cmax marker
  const cmaxIdx = c.indexOf(Math.max(...c));
  if (cmaxIdx >= 0) {
    const cx = tx(t[cmaxIdx]), cy = ty(c[cmaxIdx]);
    ctx.fillStyle = VIZ.colors.teal;
    ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = VIZ.colors.white;
    ctx.font = 'bold 9px "DM Mono", monospace';
    ctx.fillText(`Cmax=${c[cmaxIdx].toFixed(3)}`, cx + 6, cy - 6);
    ctx.font = '9px "DM Mono", monospace';
    ctx.fillStyle = VIZ.colors.muted;
    ctx.fillText(`Tmax=${t[cmaxIdx].toFixed(1)}h`, cx + 6, cy + 8);
  }

  // Axes labels
  ctx.fillStyle = VIZ.colors.muted;
  ctx.font = '10px "DM Mono", monospace';
  ctx.textAlign = 'center';
  for (let h = 0; h <= tMax; h += 12) {
    ctx.fillText(h + 'h', tx(h), H - pad.b + 16);
  }
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = (cMax / 4 * (4 - i)).toFixed(2);
    ctx.fillText(val, pad.l - 6, pad.t + (ph / 4) * i + 4);
  }

  // Title
  ctx.fillStyle = VIZ.colors.white;
  ctx.font = '11px "Outfit", sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(drugName + ' — Concentration vs Time', pad.l, pad.t - 12);

  // Legend
  const lx = pad.l + pw - 160;
  ctx.font = '9px "DM Mono", monospace';
  ctx.fillStyle = VIZ.colors.teal;
  ctx.fillRect(lx, pad.t + 6, 12, 2);
  ctx.fillStyle = VIZ.colors.muted;
  ctx.fillText('Simulation', lx + 16, pad.t + 10);
  ctx.fillStyle = VIZ.colors.bands[2];
  ctx.fillRect(lx, pad.t + 18, 12, 6);
  ctx.fillStyle = VIZ.colors.muted;
  ctx.fillText('P25-P75 (MC)', lx + 16, pad.t + 24);
}


// ─── 2. MONTE CARLO DISTRIBUTION HISTOGRAM ───────────────────────────────────

function renderMCHistogram(containerId, distribution, metricName) {
  const container = document.getElementById(containerId);
  if (!container || !distribution) return;

  container.innerHTML = '';
  const W = container.clientWidth || 400, H = 200;
  const canvas = document.createElement('canvas');
  container.appendChild(canvas);
  const ctx = _setupCanvas(canvas, W, H);

  const pad = { l: 50, r: 20, t: 30, b: 35 };
  const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;

  const { median, p5, p25, p75, p95, mean, std } = distribution;
  const lo = p5 - std * 0.5, hi = p95 + std * 0.5;
  const nBins = 25;
  const binW = (hi - lo) / nBins;
  const bins = new Array(nBins).fill(0);

  // Simulate normal distribution for histogram
  const nSamples = 500;
  for (let i = 0; i < nSamples; i++) {
    let u = 0, v = 0;
    while (u === 0) u = Math.random();
    while (v === 0) v = Math.random();
    const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    const val = mean + z * std;
    const idx = Math.floor((val - lo) / binW);
    if (idx >= 0 && idx < nBins) bins[idx]++;
  }

  const maxBin = Math.max(...bins, 1);
  const tx = v => pad.l + ((v - lo) / (hi - lo)) * pw;
  const bh = v => (v / maxBin) * ph;

  // Bars
  const barW = pw / nBins - 1;
  for (let i = 0; i < nBins; i++) {
    const val = lo + (i + 0.5) * binW;
    const x = pad.l + (i / nBins) * pw;
    const h = bh(bins[i]);
    const inIQR = val >= p25 && val <= p75;
    ctx.fillStyle = inIQR ? VIZ.colors.teal : VIZ.colors.tealDim;
    ctx.fillRect(x, pad.t + ph - h, barW, h);
  }

  // Percentile lines
  const pLines = [
    { v: p5, label: 'P5', color: VIZ.colors.muted },
    { v: median, label: 'P50', color: VIZ.colors.teal },
    { v: p95, label: 'P95', color: VIZ.colors.muted },
  ];
  for (const pl of pLines) {
    const x = tx(pl.v);
    ctx.strokeStyle = pl.color;
    ctx.lineWidth = pl.v === median ? 2 : 1;
    ctx.setLineDash(pl.v === median ? [] : [4, 3]);
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ph); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = pl.color;
    ctx.font = '9px "DM Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(pl.label, x, pad.t - 4);
    ctx.fillText(pl.v.toFixed(2), x, pad.t + ph + 14);
  }

  // Axis
  ctx.fillStyle = VIZ.colors.white;
  ctx.font = '11px "Outfit", sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText((metricName || 'AUC') + ' Distribution (Monte Carlo)', pad.l, pad.t - 14);
}


// ─── 3. PARETO FRONTIER SCATTER ──────────────────────────────────────────────

function renderParetoFrontier(containerId, paretoSchedules) {
  const container = document.getElementById(containerId);
  if (!container || !paretoSchedules?.length) return;

  container.innerHTML = '';
  const W = container.clientWidth || 500, H = 280;
  const canvas = document.createElement('canvas');
  canvas.style.cursor = 'crosshair';
  container.appendChild(canvas);
  const ctx = _setupCanvas(canvas, W, H);

  const pad = { l: 60, r: 30, t: 35, b: 50 };
  const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;

  // Extract objectives for axes: peak_toxicity_risk vs inconvenience
  const points = paretoSchedules.map(s => ({
    x: s.objectives?.peak_toxicity_risk ?? 0,
    y: s.objectives?.inconvenience ?? 0,
    coverage: s.objectives?.therapeutic_coverage ?? 0,
    label: s.label || '',
    feasible: s.is_feasible,
    data: s,
  }));

  const xMax = Math.max(...points.map(p => p.x), 0.1) * 1.2;
  const yMax = Math.max(...points.map(p => p.y), 0.1) * 1.2;

  const tx = v => pad.l + (v / xMax) * pw;
  const ty = v => pad.t + ph - (v / yMax) * ph;

  // Grid
  ctx.strokeStyle = VIZ.colors.grid;
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (ph / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + pw, y); ctx.stroke();
    const x = pad.l + (pw / 4) * i;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ph); ctx.stroke();
  }

  // Pareto front line (connect sorted by x)
  const sorted = [...points].sort((a, b) => a.x - b.x);
  if (sorted.length > 1) {
    ctx.strokeStyle = VIZ.colors.goldDim;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    sorted.forEach((p, i) => {
      const x = tx(p.x), y = ty(p.y);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Points
  for (const p of points) {
    const x = tx(p.x), y = ty(p.y);
    const r = 5 + p.coverage * 6;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = p.feasible ? VIZ.colors.tealDim : VIZ.colors.redDim;
    ctx.fill();
    ctx.strokeStyle = p.feasible ? VIZ.colors.teal : VIZ.colors.red;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    if (p.label) {
      ctx.fillStyle = VIZ.colors.white;
      ctx.font = '9px "DM Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText(p.label, x, y - r - 5);
    }
  }

  // Ideal corner arrow
  ctx.fillStyle = VIZ.colors.greenDim;
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t + ph);
  ctx.lineTo(pad.l + 40, pad.t + ph);
  ctx.lineTo(pad.l, pad.t + ph - 40);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = VIZ.colors.green;
  ctx.font = '8px "DM Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillText('IDEAL', pad.l + 3, pad.t + ph - 6);

  // Axis labels
  ctx.fillStyle = VIZ.colors.muted;
  ctx.font = '10px "DM Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText('Peak Toxicity Risk', pad.l + pw / 2, H - 6);
  ctx.save();
  ctx.translate(14, pad.t + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Inconvenience', 0, 0);
  ctx.restore();

  // Title
  ctx.fillStyle = VIZ.colors.white;
  ctx.font = '11px "Outfit", sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('Pareto Frontier — Schedule Trade-offs', pad.l, pad.t - 14);
}


// ─── 4. KNOWLEDGE GRAPH (force-directed minimap) ─────────────────────────────

function renderKnowledgeGraph(containerId, interactionChains) {
  const container = document.getElementById(containerId);
  if (!container || !interactionChains?.length) return;

  container.innerHTML = '';
  const W = container.clientWidth || 500, H = 320;
  const canvas = document.createElement('canvas');
  container.appendChild(canvas);
  const ctx = _setupCanvas(canvas, W, H);

  // Build nodes and edges from interaction chains
  const nodeSet = new Map();
  const edges = [];

  for (const itx of interactionChains) {
    const a = itx.entity_a || '', b = itx.entity_b || '';
    const path = itx.reasoning_dict?.steps || [];
    if (!a || !b) continue;
    if (!nodeSet.has(a)) nodeSet.set(a, { id: a, x: 0, y: 0, vx: 0, vy: 0, type: 'drug' });
    if (!nodeSet.has(b)) nodeSet.set(b, { id: b, x: 0, y: 0, vx: 0, vy: 0, type: 'drug' });

    // Add intermediates from path
    const pathNodes = itx.reasoning_dict?.steps?.filter(s => s.description?.includes('enzyme'))
      .map(s => s.value) || [];

    let mech = (itx.mechanism || '').substring(0, 30);
    if (mech.includes('CYP')) {
      const cyp = mech.match(/CYP\w+/)?.[0];
      if (cyp && !nodeSet.has(cyp)) {
        nodeSet.set(cyp, { id: cyp, x: 0, y: 0, vx: 0, vy: 0, type: 'enzyme' });
      }
      if (cyp) {
        edges.push({ from: a, to: cyp, label: 'substrate', sev: itx.severity || 0.3 });
        edges.push({ from: cyp, to: b, label: 'metabolizes', sev: itx.severity || 0.3 });
        continue;
      }
    }
    edges.push({ from: a, to: b, label: mech, sev: itx.severity || 0.3 });
  }

  const nodes = [...nodeSet.values()];
  if (nodes.length === 0) return;

  // Initialize positions in circle
  const cx = W / 2, cy = H / 2, radius = Math.min(W, H) / 3;
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    n.x = cx + radius * Math.cos(angle) + (Math.random() - 0.5) * 20;
    n.y = cy + radius * Math.sin(angle) + (Math.random() - 0.5) * 20;
  });

  // Simple force simulation (50 iterations)
  for (let iter = 0; iter < 60; iter++) {
    const k = 80;
    // Repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = nodes[j].x - nodes[i].x, dy = nodes[j].y - nodes[i].y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const force = (k * k) / dist;
        dx = (dx / dist) * force * 0.1;
        dy = (dy / dist) * force * 0.1;
        nodes[i].x -= dx; nodes[i].y -= dy;
        nodes[j].x += dx; nodes[j].y += dy;
      }
    }
    // Attraction along edges
    for (const e of edges) {
      const a = nodeSet.get(e.from), b = nodeSet.get(e.to);
      if (!a || !b) continue;
      let dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const force = (dist - k) * 0.02;
      dx = (dx / dist) * force;
      dy = (dy / dist) * force;
      a.x += dx; a.y += dy;
      b.x -= dx; b.y -= dy;
    }
    // Center gravity
    nodes.forEach(n => {
      n.x += (cx - n.x) * 0.01;
      n.y += (cy - n.y) * 0.01;
      n.x = Math.max(40, Math.min(W - 40, n.x));
      n.y = Math.max(40, Math.min(H - 40, n.y));
    });
  }

  // Draw edges
  for (const e of edges) {
    const a = nodeSet.get(e.from), b = nodeSet.get(e.to);
    if (!a || !b) continue;
    const sevColor = e.sev > 0.6 ? VIZ.colors.red : e.sev > 0.3 ? VIZ.colors.gold : VIZ.colors.teal;
    ctx.strokeStyle = sevColor;
    ctx.lineWidth = 1 + e.sev * 2;
    ctx.globalAlpha = 0.6;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    ctx.globalAlpha = 1;

    // Edge label
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    ctx.fillStyle = VIZ.colors.muted;
    ctx.font = '8px "DM Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(e.label.substring(0, 20), mx, my - 4);

    // Arrow
    const angle = Math.atan2(b.y - a.y, b.x - a.x);
    const arrowX = b.x - Math.cos(angle) * 18, arrowY = b.y - Math.sin(angle) * 18;
    ctx.fillStyle = sevColor;
    ctx.beginPath();
    ctx.moveTo(arrowX, arrowY);
    ctx.lineTo(arrowX - 6 * Math.cos(angle - 0.4), arrowY - 6 * Math.sin(angle - 0.4));
    ctx.lineTo(arrowX - 6 * Math.cos(angle + 0.4), arrowY - 6 * Math.sin(angle + 0.4));
    ctx.closePath(); ctx.fill();
  }

  // Draw nodes
  for (const n of nodes) {
    const isEnzyme = n.type === 'enzyme';
    const r = isEnzyme ? 10 : 14;
    ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fillStyle = isEnzyme ? 'rgba(200,169,110,0.2)' : 'rgba(20,166,170,0.15)';
    ctx.fill();
    ctx.strokeStyle = isEnzyme ? VIZ.colors.gold : VIZ.colors.teal;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.fillStyle = VIZ.colors.white;
    ctx.font = (isEnzyme ? '9' : '10') + 'px "DM Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(n.id.substring(0, 15), n.x, n.y + r + 13);
  }

  // Title
  ctx.fillStyle = VIZ.colors.white;
  ctx.font = '11px "Outfit", sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('Causal Knowledge Graph — Active Regimen', 10, 16);
}


// ─── 5. STRESS TEST GRID ─────────────────────────────────────────────────────

function renderStressTestGrid(containerId, stressResults) {
  const container = document.getElementById(containerId);
  if (!container) return;
  if (!stressResults || Object.keys(stressResults).length === 0) {
    container.innerHTML = '<div style="text-align:center;padding:1.5rem;color:#7a8899;font-size:0.82rem">No stress test data available yet.</div>';
    return;
  }

  let html = '';
  for (const [drug, data] of Object.entries(stressResults)) {
    const badge = data.is_fragile
      ? '<span class="risk-badge risk-high">FRAGILE</span>'
      : '<span class="risk-badge risk-clear">ROBUST</span>';

    html += `<div style="margin-bottom:1.2rem">
      <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.6rem">
        <span style="font-size:0.9rem;font-weight:400;color:#f0ede8">${drug}</span>${badge}
      </div>
      <div class="stress-grid">`;

    for (const sc of (data.scenarios || [])) {
      const sev = sc.outcome_severity || 0;
      const color = sev > 0.5 ? '#f08080' : sev > 0.2 ? '#c8a96e' : '#7dce82';
      const barW = Math.max(sev * 100, 4);
      html += `<div class="stress-cell">
        <div class="stress-name">${sc.name.replace(/_/g, ' ')}</div>
        <div class="stress-bar-track">
          <div class="stress-bar" style="width:${barW}%;background:${color}"></div>
        </div>
        <div class="stress-val" style="color:${color}">${(sev * 100).toFixed(0)}%</div>
        <div class="stress-desc">${sc.outcome?.substring(0, 60) || ''}</div>
      </div>`;
    }
    html += '</div></div>';
  }

  container.innerHTML = html;
}


// ─── 6. REASONING CHAIN STEP CARDS ───────────────────────────────────────────

function renderReasoningChain(containerId, reasoningDict) {
  const container = document.getElementById(containerId);
  if (!container || !reasoningDict?.steps?.length) return;

  let html = `<div class="reasoning-chain">
    <div class="chain-conclusion">${reasoningDict.final_conclusion || ''}</div>
    <div class="chain-meta">Confidence: ${((reasoningDict.confidence || 0) * 100).toFixed(0)}% · ${reasoningDict.model_version || ''}</div>
    <div class="chain-steps">`;

  for (const step of reasoningDict.steps) {
    const confColor = step.confidence > 0.8 ? '#7dce82' : step.confidence > 0.5 ? '#c8a96e' : '#f08080';
    html += `<div class="chain-step">
      <div class="step-num">${step.id}</div>
      <div class="step-body">
        <div class="step-desc">${step.description}</div>
        <div class="step-value">${typeof step.value === 'object' ? JSON.stringify(step.value) : step.value}</div>
        <div class="step-meta">
          <span style="color:${confColor}">${(step.confidence * 100).toFixed(0)}%</span>
          <span>Source: ${step.source?.substring(0, 50) || '—'}</span>
        </div>
        ${step.uncertainty_note ? `<div class="step-warn">${step.uncertainty_note}</div>` : ''}
        ${step.references?.length ? `<div class="step-refs">${step.references.slice(0, 2).join(' · ')}</div>` : ''}
      </div>
    </div>`;
  }

  html += '</div></div>';
  container.innerHTML = html;
}


// ─── 7. LAYER PROGRESS INDICATOR ─────────────────────────────────────────────

const ENGINE_LAYERS = [
  { id: 0, name: 'Input Validation', icon: '✓' },
  { id: 1, name: 'Biological Twin', icon: '🧬' },
  { id: 2, name: 'PK/PD Engine', icon: '📈' },
  { id: 3, name: 'Monte Carlo', icon: '🎲' },
  { id: 4, name: 'Schedule Optimizer', icon: '⚡' },
  { id: 5, name: 'Knowledge Graph', icon: '🔗' },
  { id: 6, name: 'Temporal Kinetics', icon: '⏱' },
  { id: 7, name: 'Stress Testing', icon: '🛡' },
  { id: 8, name: 'Bayesian Update', icon: '📊' },
  { id: 9, name: 'Explainability', icon: '💡' },
  { id: 10, name: 'Audit & Safety', icon: '🔒' },
];

function showLayerProgress(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.style.display = 'block';
  container.innerHTML = `<div class="layer-progress">
    ${ENGINE_LAYERS.map(l => `<div class="lp-step" id="lp-${l.id}">
      <span class="lp-icon">${l.icon}</span>
      <span class="lp-name">${l.name}</span>
      <span class="lp-status lp-pending"></span>
    </div>`).join('')}
  </div>`;

  // Animate through layers
  let i = 0;
  const timer = setInterval(() => {
    if (i >= ENGINE_LAYERS.length) { clearInterval(timer); return; }
    const el = document.getElementById(`lp-${i}`);
    if (el) {
      el.classList.add('lp-active');
      const status = el.querySelector('.lp-status');
      if (status) { status.classList.remove('lp-pending'); status.classList.add('lp-done'); }
    }
    if (i > 0) {
      const prev = document.getElementById(`lp-${i - 1}`);
      if (prev) prev.classList.remove('lp-active');
    }
    i++;
  }, 400);

  return timer;
}

function hideLayerProgress(containerId, timer) {
  if (timer) clearInterval(timer);
  const container = document.getElementById(containerId);
  if (container) {
    const steps = container.querySelectorAll('.lp-step');
    steps.forEach(s => {
      s.classList.add('lp-active');
      const status = s.querySelector('.lp-status');
      if (status) { status.classList.remove('lp-pending'); status.classList.add('lp-done'); }
    });
    setTimeout(() => { container.style.display = 'none'; }, 1200);
  }
}


// ─── 8. COUNTERFACTUAL BAR CHART ─────────────────────────────────────────────

function renderCounterfactualBars(containerId, counterfactualRisk) {
  const container = document.getElementById(containerId);
  if (!container) return;
  if (!counterfactualRisk || Object.keys(counterfactualRisk).length === 0) {
    container.innerHTML = '<div style="text-align:center;padding:1.2rem;color:#7a8899;font-size:0.82rem">No counterfactual risk data. Run engine analysis first.</div>';
    return;
  }

  const entries = Object.entries(counterfactualRisk).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const maxVal = Math.max(...entries.map(e => Math.abs(e[1])), 1);

  let html = '';
  for (const [drug, pct] of entries) {
    const w = (Math.abs(pct) / maxVal) * 100;
    const color = pct > 30 ? VIZ.colors.red : pct > 10 ? VIZ.colors.gold : VIZ.colors.teal;
    html += `<div class="cf-bar-row">
      <span class="cf-drug">${drug}</span>
      <div class="cf-track"><div class="cf-fill" style="width:${w}%;background:${color}"></div></div>
      <span class="cf-pct" style="color:${color}">${pct > 0 ? '+' : ''}${pct.toFixed(1)}%</span>
    </div>`;
  }
  container.innerHTML = html;
}


// ─── MASTER RENDER — WIRE INTO ENGINE RESULTS ────────────────────────────────

function renderAllVisualizations(result) {
  if (!result) return;

  // PK curves + MC histograms per drug
  if (result.pk_results) {
    const pkVizContainer = document.getElementById('pk-viz-area');
    if (pkVizContainer) pkVizContainer.innerHTML = '';

    for (const [drug, pkData] of Object.entries(result.pk_results)) {
      const sim = pkData.simulation || {};
      const mcBands = pkData.concentration_bands || {};
      const mc = pkData.uncertainty || {};
      const mcCmax = pkData.mc_cmax || {};

      // Create containers
      const drugSection = document.createElement('div');
      drugSection.className = 'viz-drug-section';
      drugSection.innerHTML = `
        <div class="viz-drug-title">${drug}</div>
        <div class="viz-row">
          <div class="viz-chart" id="viz-curve-${drug}"></div>
          <div class="viz-chart viz-chart-sm" id="viz-mc-${drug}"></div>
        </div>`;
      (pkVizContainer || document.getElementById('pk-grid'))?.appendChild(drugSection);

      // Render after DOM insert
      setTimeout(() => {
        const pdParams = { ec50: null };
        // Try to get EC50 from known params
        const pdMap = { warfarin: 1.5, amlodipine: 6.0, metformin: 800, digoxin: 1.2, atorvastatin: 3.5, omeprazole: 0.08 };
        pdParams.ec50 = pdMap[drug.toLowerCase()] || null;

        renderConcentrationCurve(`viz-curve-${drug}`, drug, sim, mcBands, pdParams);
        if (mc.median != null) renderMCHistogram(`viz-mc-${drug}`, mc, 'AUC');
      }, 50);
    }
  }

  // Pareto frontier
  if (result.pareto_schedules?.length) {
    renderParetoFrontier('viz-pareto', result.pareto_schedules);
  }

  // Knowledge graph
  if (result.interaction_chains?.length) {
    renderKnowledgeGraph('viz-kg', result.interaction_chains);
  }

  // Stress tests
  if (result.stress_test_results) {
    renderStressTestGrid('viz-stress', result.stress_test_results);
  }

  // Counterfactual bars
  if (result.counterfactual_risk) {
    renderCounterfactualBars('cf-risk-list', result.counterfactual_risk);
  }
}
