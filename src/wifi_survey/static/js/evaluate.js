// Ansicht „Auswertung“: Messwerte je Gerät, berechnete Ausleuchtung über alle Stockwerke, Hinweise.

import { api } from './api.js';
import { el, Viewport, isTyping } from './viewport.js';
import * as G from './geom.js';
import { section, div, button } from './plans.js';
import { slider } from './floor.js';

export const RATING_COLOR = { gut: '#1a9850', ausreichend: '#91cf60', schwach: '#fdae61', kritisch: '#d73027' };
const SIM_KEY = 'ws-sim';   // Simulation bleibt beim Wechsel des Stockwerks erhalten (sessionStorage)

function staggerApLabel(placed, pos, baseTy, dir, px) {
  let ty = baseTy;
  const step = dir * px(15);
  const wBox = px(180);
  const hBox = px(14);
  while (placed.some(([ox, oy]) => Math.abs(pos[0] - ox) < wBox && Math.abs((pos[1] + ty) - oy) < hBox)) {
    ty += step;
  }
  placed.push([pos[0], pos[1] + ty]);
  return ty;
}

function loadSim() {
  const empty = { active: false, moved: {}, off: [], added: [], movable: null, add: 0 };
  try {
    return { ...empty, ...JSON.parse(sessionStorage.getItem(SIM_KEY) || '{}') };
  } catch {
    return empty;
  }
}

export class EvaluationView {
  constructor(ctx, floorId) {
    this.ctx = ctx;
    this.floorId = floorId;
    this.ev = null;
    this.error = null;
    this.mapKey = 'best';
    this.band = sessionStorage.getItem('ws-band') === '5' ? '5' : '2.4';   // Karte und Abdeckung je Band
    this.heatOpacity = 0.75;
    this.selected = null;
    this.overview = null;
    this.sim = loadSim();
    this.simResult = null;
    this.simBusy = false;
    this.lastRec = null;
    this.drag = null;
  }

  async mount() {
    const floors = this.ctx.floorsSorted();
    this.floor = floors.find((f) => f.id === this.floorId) || floors.find((f) => f.scale && f.devices?.length) || floors[0];
    this.vp = new Viewport(this.ctx.svg, { onChange: () => this.renderOverlay() });
    this.vp.handler = this;
    this.keyHandler = (e) => { if (!isTyping(e) && (e.key === 'f' || e.key === 'F')) this.vp.fit(); };
    window.addEventListener('keydown', this.keyHandler);
    if (!this.floor) {
      this.renderPanel();
      return;
    }
    const w = this.vp.world;
    this.layer = { image: el('g', {}, w), heat: el('g', {}, w), walls: el('g', {}, w), area: el('g', {}, w), links: el('g', {}, w), devices: el('g', {}, w) };
    el('rect', { x: 0, y: 0, width: this.floor.image_w, height: this.floor.image_h, fill: 'var(--plan-paper)', class: 'plan-paper' }, this.layer.image);
    el('image', { href: api.floorImageUrl(this.floor), x: 0, y: 0, width: this.floor.image_w, height: this.floor.image_h, opacity: 0.45, class: 'plan-img' }, this.layer.image);
    this.vp.contentBox = { x: 0, y: 0, w: this.floor.image_w, h: this.floor.image_h };
    this.ctx.hint('Farben: berechnetes Signal aller Zugangspunkte im Haus, auch durch die Decken (grün stark, rot schwach). Gestrichelt: gezählte Hausfläche. Punkte: Geräte, eingefärbt nach ihrem gemessenen Signal; orangener Ring = hängt an einem schwächeren Zugangspunkt als möglich.');
    await this.load();
    requestAnimationFrame(() => this.fitToGrid());
  }

  async unmount() {
    window.removeEventListener('keydown', this.keyHandler);
    this.vp.destroy();
  }

  async load() {
    try {
      this.ev = await api.evaluation(this.floor.id);
      this.error = null;
      this.checkMapKey();
    } catch (e) {
      this.ev = null;
      this.error = e.message;
    }
    this.renderStage();
    this.renderPanel();
    if (this.ev) {
      this.loadOverview();
      if (this.sim.active) this.runSim();
    }
  }

  async loadOverview() {
    try {
      this.overview = await api.evaluationOverview();
    } catch {
      this.overview = null;
    }
    this.renderPanel();
  }

  // Band der Karte: 5 GHz nur, wenn es dafür Karten gibt; die Simulation rechnet mit 2,4 GHz
  shownBand() {
    return this.band === '5' && this.ev?.maps5?.length && !this.simulating() ? '5' : '2.4';
  }

  bandMaps() {
    return (this.shownBand() === '5' ? this.ev?.maps5 : this.ev?.maps) || [];
  }

  checkMapKey() {
    const maps = this.bandMaps();
    if (!maps.includes(this.mapKey)) this.mapKey = maps.includes('best') ? 'best' : maps[0];
  }

  setBand(band) {
    this.band = band;
    sessionStorage.setItem('ws-band', band);
    this.checkMapKey();
    this.renderStage();
    this.renderPanel();
  }

  fitToGrid() {
    if (!this.ev) { this.vp.fit(); return; }
    const g = this.ev.grid;
    this.vp.fit({ x: g.x, y: g.y, w: g.cols * g.cell_px, h: g.rows * g.cell_px });
  }

  // --- Zeichenfläche ----------------------------------------------------------------------

  renderStage() {
    if (!this.layer) return;
    const { heat, walls, area } = this.layer;
    heat.replaceChildren();
    walls.replaceChildren();
    area.replaceChildren();
    for (const poly of this.ev?.area?.outline || []) {
      el('polygon', { points: poly.map((q) => q.join(',')).join(' '), fill: 'none', stroke: 'var(--outline-eval)', 'stroke-width': 2.5,
        'stroke-dasharray': '10 6', 'vector-effect': 'non-scaling-stroke', opacity: 0.85 }, area);
    }
    for (const w of this.floor.walls) {
      el('line', { x1: w.a[0], y1: w.a[1], x2: w.b[0], y2: w.b[1], stroke: 'var(--wall-map)', 'stroke-width': w.thickness_px, 'stroke-opacity': 0.55, 'stroke-linecap': 'butt' }, walls);
    }
    if (this.ev && this.mapKey) {
      const g = this.ev.grid;
      const simMap = this.simulating() ? this.simResult.floor.map : null;
      el('image', {
        href: simMap || api.heatmapUrl(this.floor.id, this.mapKey, this.ev.measured_at, this.shownBand()),
        x: g.x, y: g.y, width: g.cols * g.cell_px, height: g.rows * g.cell_px,
        preserveAspectRatio: 'none', opacity: this.heatOpacity, class: 'heat',
      }, heat);
    }
    this.renderOverlay();
  }

  renderOverlay() {
    if (!this.layer) return;
    this.ctx.status(undefined, `Zoom ${G.fmt(this.vp.s * 100, 0)} %`);
    const { links, devices } = this.layer;
    links.replaceChildren();
    devices.replaceChildren();
    if (!this.ev) return;
    const px = (n) => this.vp.px(n);
    if (!this.simulating()) this.drawAps(links, devices, px);
    for (const d of this.ev.devices) {
      const c = d.connected;
      const g = el('g', { transform: `translate(${d.pos[0]} ${d.pos[1]})`, 'data-eval': d.key, style: 'cursor:pointer' }, devices);
      if (d.sticky) el('circle', { r: px(13), fill: 'none', stroke: 'var(--warn)', 'stroke-width': 3, 'vector-effect': 'non-scaling-stroke' }, g);
      if (this.selected === d.key) el('circle', { r: px(16), class: 'device-ring' }, g);
      el('circle', { r: px(8), fill: c ? RATING_COLOR[c.rating] : 'var(--dev-unmeasured)', stroke: 'var(--handle-fill)', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }, g);
      if (this.vp.s >= 0.5 || this.selected === d.key) {
        const t = el('text', { x: px(12), y: px(4), class: 'device-label', 'font-size': px(12) }, g);
        t.textContent = `${d.label}${c ? ` ${c.rssi}` : ''}`;
      }
    }
    for (const s of this.ev.survey || []) {   // Messpunkte vom Rundgang mit dem Handy (Rauten)
      const g = el('g', { transform: `translate(${s.pos[0]} ${s.pos[1]})` }, devices);
      el('rect', { x: -px(6), y: -px(6), width: px(12), height: px(12), transform: 'rotate(45)', fill: s.best ? RATING_COLOR[s.best.rating] : 'var(--dev-unmeasured)',
        stroke: 'var(--handle-fill)', 'stroke-width': 1.5, 'vector-effect': 'non-scaling-stroke' }, g);
      if (this.vp.s >= 0.7 && s.best) {
        const t = el('text', { x: px(10), y: px(4), class: 'device-label', 'font-size': px(11) }, g);
        t.textContent = `M${s.n} ${s.best.rssi}`;
      }
    }
    if (this.simulating()) this.drawSimAps(devices, px);   // obenauf, damit sie sich ziehen lassen
  }

  drawAps(links, devices, px) {
    const apPos = Object.fromEntries(this.ev.aps.map((a) => [a.key, a.pos]));
    // Zugangspunkte anderer Stockwerke nur, wenn ein Gerät hier daran hängt oder die Karte ihn zeigt
    const wanted = new Set(this.ev.devices.map((d) => d.connected?.ap).filter(Boolean));
    if (this.mapKey !== 'best') wanted.add(this.mapKey);
    for (const d of this.ev.devices) {
      const c = d.connected;
      if (c && apPos[c.ap]) {
        el('line', { x1: d.pos[0], y1: d.pos[1], x2: apPos[c.ap][0], y2: apPos[c.ap][1], stroke: RATING_COLOR[c.rating] || 'var(--wall-fallback)',
          'stroke-width': 2, 'stroke-dasharray': '6 4', 'vector-effect': 'non-scaling-stroke', opacity: 0.9 }, links);
      }
    }
    const placed = [];
    for (const a of this.ev.aps) {
      if (!a.same_floor && !wanted.has(a.key)) continue;
      const g = el('g', { transform: `translate(${a.pos[0]} ${a.pos[1]})` }, devices);
      if (a.same_floor) {
        el('circle', { r: px(11), fill: 'var(--dev-ap)', stroke: 'var(--handle-fill)', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }, g);
        el('circle', { r: px(4), fill: 'var(--handle-fill)' }, g);
      } else {
        el('circle', { r: px(11), fill: 'var(--handle-fill)', 'fill-opacity': 0.8, stroke: 'var(--dev-ap)', 'stroke-width': 2, 'stroke-dasharray': '4 3', 'vector-effect': 'non-scaling-stroke' }, g);
        el('circle', { r: px(4), fill: 'var(--dev-ap)' }, g);
      }
      // Zugangspunkte darüber: Beschriftung oben, darunter: unten; bei Überlappung vertikal staffeln
      const ty = staggerApLabel(placed, a.pos, a.same_floor ? px(4) : a.above ? px(-11) : px(17), a.above ? -1 : 1, px);
      const t = el('text', { x: px(14), y: ty, class: 'device-label', 'font-size': px(13) }, g);
      t.textContent = a.same_floor ? a.label : `${a.label} ${a.above ? '↑' : '↓'} ${a.floor}`;
    }
  }

  down(e, w) {
    if (this.simulating()) {   // Zugangspunkt dieses Stockwerks ziehen
      const ap = e.target.closest?.('[data-ap]');
      const a = ap && this.simResult.floor.aps.find((x) => x.key === ap.dataset.ap);
      if (a && a.same_floor && !a.off) {
        this.drag = { key: a.key, start: w, from: [...a.pos], g: ap, pos: null };
        return true;
      }
    }
    const g = e.target.closest?.('[data-eval]');
    if (g) {
      this.selected = g.dataset.eval;
      this.renderOverlay();
      this.renderPanel();
      document.getElementById(`ev-${this.selected}`)?.scrollIntoView({ block: 'nearest' });
      return true;
    }
    return 'pan';
  }

  move(e, w) {
    const d = this.drag;
    if (!d) return;
    d.pos = [d.from[0] + w[0] - d.start[0], d.from[1] + w[1] - d.start[1]];
    d.g.setAttribute('transform', `translate(${d.pos[0]} ${d.pos[1]})`);
  }

  up() {
    const d = this.drag;
    this.drag = null;
    if (!d?.pos) return;
    const pos = d.pos.map((v) => Math.round(v * 10) / 10);
    if (d.key.startsWith('neu:')) {
      const n = this.sim.added.find((x) => `neu:${x.id}` === d.key);
      if (n) Object.assign(n, { pos, floor_id: this.floor.id });
    } else {
      this.sim.moved[d.key] = { floor_id: this.floor.id, pos };
    }
    this.saveSim();
    this.runSim();
  }

  cancel() {
    this.drag = null;
    this.renderOverlay();
  }

  hover(e, w) {
    if (!this.floor?.scale) return;
    const ppm = this.floor.scale.px_per_m;
    this.ctx.status(`x ${G.fmt(w[0] / ppm, 2)} m · y ${G.fmt(w[1] / ppm, 2)} m`);
  }

  // --- Panel ------------------------------------------------------------------------------

  renderPanel() {
    const { ctx } = this;
    const p = ctx.panel;
    const scroll = p.scrollTop;
    p.replaceChildren();
    const floors = ctx.floorsSorted();
    const head = section(p, 'Auswertung');
    if (!floors.length) { div(head, 'muted', 'Noch keine Stockwerke.'); return; }
    const sel = document.createElement('select');
    for (const f of floors) sel.appendChild(new Option(`${f.name}${f.scale ? '' : ' (ohne Maßstab)'}`, f.id, false, f.id === this.floor.id));
    sel.addEventListener('change', () => ctx.navigate(`#/auswertung/${sel.value}`));
    head.appendChild(sel);

    if (this.error) {
      div(section(p, 'Hinweis'), 'callout', this.error.includes('Maßstab')
        ? `${this.error} Stockwerk öffnen und mit dem Werkzeug „Maßstab“ kalibrieren.` : this.error);
      if (this.error.includes('Maßstab')) button(p, `${this.floor.name} öffnen`, () => ctx.navigate(`#/stockwerk/${this.floor.id}`));
      p.scrollTop = scroll;
      return;
    }
    if (!this.ev) return;
    const ev = this.ev;

    const map = section(p, 'Karte');
    if (!ev.maps.length) {
      div(map, 'callout', 'Kein Zugangspunkt erreicht dieses Stockwerk. Router oder Repeater mit dem Werkzeug „Geräte“ (G) platzieren '
        + '(aus dem Messlauf oder als eigenes Gerät) und die Stockwerke ausrichten.');
    } else {
      if (this.simulating()) {
        div(map, 'small', 'Die Karte zeigt die Simulation: beste Versorgung aller Zugangspunkte.');
      } else {
        if (ev.maps5?.length) {
          const bands = div(map, 'row');
          for (const [b, label] of [['2.4', '2,4 GHz'], ['5', '5 GHz']]) {
            const btn = button(bands, label, () => this.setBand(b));
            if (this.shownBand() === b) btn.classList.add('active');
          }
        }
        const maps = this.bandMaps();
        const ms = document.createElement('select');
        if (maps.includes('best')) ms.appendChild(new Option('Beste Versorgung (alle Zugangspunkte)', 'best', false, this.mapKey === 'best'));
        for (const a of ev.aps) {
          if (maps.includes(a.key)) ms.appendChild(new Option(a.same_floor ? a.label : `${a.label} (${a.floor})`, a.key, false, this.mapKey === a.key));
        }
        ms.addEventListener('change', () => { this.mapKey = ms.value; this.renderStage(); });
        map.appendChild(ms);
      }
      slider(map, 'Deckkraft der Karte', this.heatOpacity, (v) => {
        this.heatOpacity = v;
        this.layer.heat.querySelector('image')?.setAttribute('opacity', v);
      });
      this.renderLegend(map, ev.legend);
      const five = this.shownBand() === '5';
      const c = five ? ev.coverage5 : ev.coverage;
      const shares = five ? ev.shares5 : ev.shares;
      if (c && !this.simulating()) {
        div(map, 'small', `Hausfläche ${G.fmt(c.flaeche_m2, 0)} m²${{ hull: ' (geschätzt)', outline: ' (eigener Umriss)' }[ev.area?.source] || ''}, `
          + `alle Zugangspunkte im Haus, ${five ? '5' : '2,4'} GHz:`);
        const kv = document.createElement('dl');
        kv.className = 'kv';
        for (const [label, limit] of [['gut', '≥ −60 dBm'], ['ausreichend', '≥ −70 dBm'], ['schwach', '≥ −80 dBm']]) {
          const dt = document.createElement('dt');
          dt.textContent = `${label === 'gut' ? 'gut' : `mind. ${label}`} (${limit})`;
          const dd = document.createElement('dd');
          dd.textContent = `${c[label]} %`;
          kv.append(dt, dd);
        }
        map.appendChild(kv);
        if (shares?.length) {
          div(map, 'small', 'Am stärksten: ' + shares.map((x) => `${x.label}${x.floor !== ev.floor ? ` (${x.floor})` : ''} ${x.share} %`).join(', '));
        }
      }
    }

    const hints = section(p, 'Hinweise');
    if (!ev.findings.length) div(hints, 'small muted', 'Keine Auffälligkeiten.');
    for (const f of ev.findings) div(hints, `finding ${f.level}`, f.text);

    this.renderSim(p);
    this.renderRecommend(p);

    const meas = section(p, 'Messlauf');
    if (this.ev?.measured_at) {
      const when = new Date(this.ev.measured_at).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
      div(meas, 'small', `Messwerte vom ${when}`);
    } else if (this.ev) {
      div(meas, 'small', 'Noch kein Messlauf: Planung mit Startwerten.');
    }
    const mb = button(meas, 'Neu messen', () => this.measure(mb));
    div(meas, 'small muted', 'Fragt FRITZ!Box und alle Shellys ab, inklusive WLAN-Scan. Dauert etwa eine Minute.');

    this.renderHouse(p);

    const devs = section(p, 'Geräte (gemessen)');
    const sorted = [...ev.devices].sort((x, y) => (x.connected?.rssi ?? 0) - (y.connected?.rssi ?? 0));
    for (const d of sorted) {
      const c = d.connected;
      const row = div(devs, `ev-device${this.selected === d.key ? ' selected' : ''}`);
      row.id = `ev-${d.key}`;
      const top = div(row, 'row');
      const dot = div(top, 'device-dot');
      dot.style.background = c ? RATING_COLOR[c.rating] : 'var(--dev-unmeasured)';
      const t = div(top, 'title', d.label);
      t.style.flex = '1';
      div(top, `rssi ${c?.rating || ''}`, c ? `${c.rssi} dBm` : '–');
      const sub = c ? `an ${c.ap_name}${c.ap_floor && c.ap_floor !== this.floor.name ? ` (${c.ap_floor})` : ''}${c.band ? `, ${c.band === '5' ? '5' : '2,4'} GHz` : ''}`
        : 'keine Messwerte im letzten Messlauf';
      const best = d.best ? ` · bester anderer: ${d.best.ap_name} ${d.best.rssi} dBm` : '';
      div(row, 'small muted', sub + best);
      row.addEventListener('click', () => {
        this.selected = d.key;
        this.vp.centerOn(d.pos, Math.max(this.vp.s, 0.9));
        this.renderPanel();
      });
    }

    this.renderModel(p, ev.model);
    p.scrollTop = scroll;
  }

  // --- Simulation -------------------------------------------------------------------------

  simulating() {
    return Boolean(this.sim.active && this.simResult?.floor);
  }

  saveSim() {
    sessionStorage.setItem(SIM_KEY, JSON.stringify(this.sim));
  }

  async runSim() {
    this.simBusy = true;
    this.renderPanel();
    try {
      this.simResult = await api.simulate({ floor_id: this.floor.id, moved: this.sim.moved, off: this.sim.off, added: this.sim.added });
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
    this.simBusy = false;
    this.renderStage();
    this.renderPanel();
  }

  drawSimAps(layer, px) {
    const placed = [];
    for (const a of this.simResult.floor.aps) {
      const color = a.off ? 'var(--dev-unmeasured)' : a.new ? 'var(--scale-color)' : 'var(--dev-ap)';
      const faint = a.same_floor ? 1 : 0.55;   // andere Stockwerke blasser
      if (a.orig) {   // alter Platz, gestrichelt verbunden
        el('line', { x1: a.orig[0], y1: a.orig[1], x2: a.pos[0], y2: a.pos[1], stroke: color, 'stroke-width': 2, 'stroke-dasharray': '6 4', 'vector-effect': 'non-scaling-stroke', opacity: faint }, layer);
        el('circle', { cx: a.orig[0], cy: a.orig[1], r: px(7), fill: 'var(--handle-fill)', 'fill-opacity': 0.6, stroke: color, 'stroke-width': 1.5, 'stroke-dasharray': '3 3', 'vector-effect': 'non-scaling-stroke', opacity: faint }, layer);
      }
      const drag = a.same_floor && !a.off;
      const g = el('g', { transform: `translate(${a.pos[0]} ${a.pos[1]})`, 'data-ap': a.key, style: drag ? 'cursor:grab' : '', opacity: faint }, layer);
      if (a.same_floor) {
        el('circle', { r: px(12), fill: color, stroke: 'var(--handle-fill)', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }, g);
        el('circle', { r: px(4), fill: 'var(--handle-fill)' }, g);
      } else {
        el('circle', { r: px(11), fill: 'var(--handle-fill)', 'fill-opacity': 0.8, stroke: color, 'stroke-width': 2, 'stroke-dasharray': '4 3', 'vector-effect': 'non-scaling-stroke' }, g);
        el('circle', { r: px(4), fill: color }, g);
      }
      if (a.off) {
        const r = px(9);
        el('path', { d: `M${-r} ${-r}L${r} ${r}M${r} ${-r}L${-r} ${r}`, stroke: 'var(--danger)', 'stroke-width': 3, 'vector-effect': 'non-scaling-stroke' }, g);
      }
      const ty = staggerApLabel(placed, a.pos, a.same_floor ? px(4) : a.above ? px(-11) : px(17), a.above ? -1 : 1, px);
      const t = el('text', { x: px(15), y: ty, class: 'device-label', 'font-size': px(13) }, g);
      const where = a.same_floor ? '' : ` ${a.above ? '↑' : '↓'} ${a.floor}`;
      const state = a.off ? ' (aus)' : a.new ? ' (neu)' : a.moved ? ` (${G.fmt(a.moved_m, 1)} m verschoben)` : '';
      t.textContent = a.label + where + state;
    }
  }

  renderSim(p) {
    const s = section(p, 'Simulation');
    if (!this.sim.active) {
      div(s, 'small muted', 'Zugangspunkte virtuell verschieben, abschalten oder ergänzen und sehen, wie sich die Versorgung im ganzen Haus ändert. Die echten Plätze bleiben unverändert.');
      button(s, 'Simulation starten', () => { this.sim.active = true; this.saveSim(); this.runSim(); }).className = 'primary';
      return;
    }
    div(s, 'small', 'Zugangspunkte in der Karte ziehen (blau: vorhanden, violett: neu). Die echten Plätze bleiben unverändert.');
    if (this.simBusy) div(s, 'small muted', 'Rechne …');
    const r = this.simResult;
    if (r) {
      div(s, 'small', `Versorgungswert ${G.fmt(r.score.before, 1)} → ${G.fmt(r.score.after, 1)} von 100`);
      const tbl = document.createElement('table');
      tbl.className = 'mini tight';
      tbl.innerHTML = '<tr><th>Stockwerk</th><th class="num">gut</th><th class="num">mind. ausr.</th></tr>';
      for (const f of r.floors) {
        if (!f.before || !f.after) continue;
        const tr = document.createElement('tr');
        if (f.id === this.floor.id) tr.className = 'current';
        tr.innerHTML = `<td></td><td class="num">${f.before.gut} → <b>${f.after.gut}</b> %</td>`
          + `<td class="num">${f.before.ausreichend} → <b>${f.after.ausreichend}</b> %</td>`;
        tr.firstChild.textContent = f.name;
        tbl.appendChild(tr);
      }
      s.appendChild(tbl);
      div(s, 'small', `Geräte unter −70 dBm: ${r.weak_devices.before} → ${r.weak_devices.after}`);
      for (const u of r.uplinks) {
        const basis = { measured: ' (gemessen)', calibrated: ' (Modell, abgeglichen an den gemessenen Funkstrecken)' }[u.basis] || '';
        div(s, `finding${u.ok ? '' : ' warn'}`, `${u.label}: Die FRITZ!Box kommt dort mit ${u.rssi} dBm an${basis}, `
          + (u.ok ? 'das reicht für die WLAN-Anbindung.' : 'zu schwach für die WLAN-Anbindung; besser per LAN anbinden.'));
      }
      for (const w of r.warnings) div(s, 'finding warn', w);
      if (this.lastRec?.kept?.length) div(s, 'small muted', `Laut Empfehlung bleiben, wo sie sind: ${this.lastRec.kept.join(', ')}.`);
      if (r.devices.length) {
        const det = document.createElement('details');
        det.className = 'more';
        det.open = r.devices.length <= 8;
        const sum = document.createElement('summary');
        sum.textContent = `Geräte mit Änderung (${r.devices.length})`;
        det.appendChild(sum);
        const dt = document.createElement('table');
        dt.className = 'mini tight';
        dt.innerHTML = '<tr><th>Gerät</th><th class="num">vorher</th><th class="num">nachher</th></tr>';
        for (const d of r.devices) {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><div></div><div class="muted"></div></td><td class="num">${d.before}</td><td class="num"><b>${d.after ?? '–'}</b></td>`;
          tr.querySelector('div').textContent = d.label + (d.floor !== this.floor.name ? ` (${d.floor})` : '');
          tr.querySelector('div.muted').textContent = d.after_ap && d.after_ap !== d.before_ap ? `${d.before_ap} → ${d.after_ap}` : (d.after_ap || d.before_ap || '');
          dt.appendChild(tr);
        }
        det.appendChild(dt);
        div(det, 'small muted', 'Bestes erwartetes Signal in dBm. Gemessene Werte werden um die berechnete Änderung verschoben.');
        s.appendChild(det);
      }
    }
    for (const a of this.ev.model.aps) {
      const row = div(s, 'row');
      const name = div(row, 'small', a.label);
      name.style.flex = '1';
      const off = this.sim.off.includes(a.key);
      const mv = this.sim.moved[a.key];
      div(name, 'muted', `${a.floor}${off ? ' · aus' : mv ? ' · verschoben' : ''}`);
      if (mv) button(row, 'zurück', () => { delete this.sim.moved[a.key]; this.saveSim(); this.runSim(); });
      button(row, off ? 'an' : 'aus', () => {
        this.sim.off = off ? this.sim.off.filter((k) => k !== a.key) : [...this.sim.off, a.key];
        this.saveSim();
        this.runSim();
      });
    }
    for (const n of this.sim.added) {
      const row = div(s, 'row');
      const name = div(row, 'small', n.label);
      name.style.flex = '1';
      const fl = this.ctx.floorsSorted().find((f) => f.id === n.floor_id);
      div(name, 'muted', `${fl?.name || ''} · neu`);
      button(row, 'entfernen', () => { this.sim.added = this.sim.added.filter((x) => x !== n); this.saveSim(); this.runSim(); });
    }
    const act = div(s, 'row');
    const add = button(act, 'Repeater hinzufügen', () => this.addRepeater());
    add.disabled = this.sim.added.length >= 5;
    button(act, 'Zurücksetzen', () => {
      Object.assign(this.sim, { moved: {}, off: [], added: [] });
      this.lastRec = null;
      this.saveSim();
      this.runSim();
    });
    button(act, 'Beenden', () => { this.sim.active = false; this.saveSim(); this.renderStage(); this.renderPanel(); });
  }

  renderRecommend(p) {
    const rs = section(p, 'Empfehlung');
    div(rs, 'small muted', 'Sucht für die angehakten Zugangspunkte den besten Platz auf ihrem Stockwerk: möglichst viel Hausfläche und alle Geräte mit mindestens −60 dBm. Repeater mit WLAN-Anbindung nur dort, wo die FRITZ!Box mit mindestens −65 dBm ankommt. Steckdosen und Netzwerkdosen kennt die App nicht.');
    const movable = new Set(this.movableKeys());
    for (const a of this.ev.model.aps) {
      const lab = document.createElement('label');
      lab.className = 'small';
      lab.style.display = 'block';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = movable.has(a.key);
      cb.addEventListener('change', () => {
        const set = new Set(this.movableKeys());
        if (cb.checked) set.add(a.key); else set.delete(a.key);
        this.sim.movable = [...set];
        this.saveSim();
      });
      const note = a.role === 'master' ? ' (hängt am Internetanschluss)' : a.uplink === 'LAN' ? ' (per LAN: braucht am neuen Platz eine Netzwerkdose)' : '';
      lab.append(cb, ` ${a.label}${note}`);
      rs.appendChild(lab);
    }
    const addRow = div(rs, 'row');
    div(addRow, 'small', 'Zusätzliche Repeater vorschlagen:');
    const sel = document.createElement('select');
    for (const n of [0, 1, 2]) sel.appendChild(new Option(String(n), String(n), false, (this.sim.add || 0) === n));
    sel.addEventListener('change', () => { this.sim.add = Number(sel.value); this.saveSim(); });
    addRow.appendChild(sel);
    const rb = button(rs, 'Empfehlung berechnen', () => this.recommend(rb));
    rb.className = 'primary';
  }

  movableKeys() {
    return this.sim.movable ?? this.ev.model.aps.filter((a) => a.role === 'slave').map((a) => a.key);
  }

  async recommend(btn) {
    btn.disabled = true;
    btn.textContent = 'Rechne … (bis etwa 30 s)';
    try {
      const rec = await api.recommend({ movable: this.movableKeys(), add: this.sim.add || 0 });
      Object.assign(this.sim, { active: true, moved: rec.moved, added: rec.added, off: [] });
      this.lastRec = rec;
      this.saveSim();
      const n = Object.keys(rec.moved).length + rec.added.length;
      this.ctx.toast(n ? `Empfehlung: ${n} Änderung${n > 1 ? 'en' : ''}, Versorgungswert ${G.fmt(rec.score.before, 1)} → ${G.fmt(rec.score.after, 1)}`
        : 'Keine deutlich bessere Aufstellung gefunden.', 'ok');
      await this.runSim();
    } catch (e) {
      this.ctx.toast(e.message, 'error');
      btn.disabled = false;
      btn.textContent = 'Empfehlung berechnen';
    }
  }

  addRepeater() {
    const r = this.ctx.svg.getBoundingClientRect();
    const pos = this.vp.toWorld(r.left + r.width / 2, r.top + r.height / 2).map((v) => Math.round(v * 10) / 10);
    const n = this.sim.added.length + 1;
    this.sim.added.push({ id: `n${Date.now() % 1000000}`, label: n > 1 ? `Neuer Repeater ${n}` : 'Neuer Repeater', floor_id: this.floor.id, pos });
    this.saveSim();
    this.runSim();
  }

  renderHouse(p) {
    const s = section(p, 'Haus');
    const ov = this.overview;
    if (!ov) { div(s, 'small muted', 'Wird berechnet …'); return; }
    const five = this.shownBand() === '5';
    const tbl = document.createElement('table');
    tbl.className = 'mini';
    tbl.innerHTML = `<tr><th>Stockwerk</th><th class="num">gut</th><th class="num">mind. ausr.</th><th class="num">Fläche</th></tr>`;
    for (const f0 of ov.floors) {
      const f = five ? { ...f0, coverage: f0.coverage5 } : f0;
      const tr = document.createElement('tr');
      tr.className = `link${f.id === this.floor.id ? ' current' : ''}`;
      const name = document.createElement('td');
      name.textContent = f.name;
      tr.appendChild(name);
      if (f.error || !f.coverage) {
        const td = document.createElement('td');
        td.colSpan = 3;
        td.className = 'muted';
        td.textContent = f.error || 'keine Hausfläche erkannt';
        tr.appendChild(td);
      } else {
        for (const v of [`${f.coverage.gut} %`, `${f.coverage.ausreichend} %`, `${G.fmt(f.coverage.flaeche_m2, 0)} m²`]) {
          const td = document.createElement('td');
          td.className = 'num';
          td.textContent = v;
          tr.appendChild(td);
        }
      }
      tr.addEventListener('click', () => this.ctx.navigate(`#/auswertung/${f.id}`));
      tbl.appendChild(tr);
    }
    s.appendChild(tbl);
    div(s, 'small muted', `Anteil der Hausfläche auf ${five ? '5' : '2,4'} GHz: gut ≥ −60 dBm, ausreichend ≥ −70 dBm. `
      + 'Berechnet aus allen Zugangspunkten im Haus. Das Band wählt man unter „Karte“.');
  }

  renderModel(p, mdl) {
    const s = section(p, 'Modell (alle Stockwerke)');
    const k = `Wandfaktor ${G.fmt(mdl.k, 2)}${mdl.k_at_bound ? ' (an der Grenze)' : ''}`;
    const c = `Decke ${G.fmt(mdl.c, 0)} dB${mdl.n_ceilings ? '' : ' (Startwert)'}`;
    div(s, 'small', mdl.n
      ? `Geeicht an ${mdl.n} Messpunkten, davon ${mdl.n_ceilings} über Stockwerke hinweg: ${k}, ${c}, mittlere Abweichung ${G.fmt(mdl.rmse, 1)} dB.`
      : `Noch keine Messpunkte, die Karte rechnet mit Startwerten (${k}, ${c}).`);
    if (mdl.up_db !== undefined) {
      const sign = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${G.fmt(Math.abs(v), 1)}`;
      div(s, 'small muted', `Sicht der FRITZ!Box (Signal am Zugangspunkt): ${sign(mdl.up_db)} dB gegenüber der Sicht der Geräte`
        + ` (${mdl.n_up} Messpunkte). 5 GHz: ${sign(mdl.band5_db)} dB gegenüber 2,4 GHz (${mdl.n5} Messpunkte)`
        + `${mdl.n_found ? `. Fundorte aus der Suche: ${mdl.n_found}` : ''}.`);
      const b5 = mdl.band5;
      if (b5?.n) {
        div(s, 'small muted', `5 GHz mit eigenem Modell aus ${b5.n} Messwerten: Wandfaktor ${G.fmt(b5.k, 2)}, Decke ${G.fmt(b5.c, 0)} dB, `
          + `mittlere Abweichung ${G.fmt(b5.rmse, 1)} dB.`);
      }
    }
    if (mdl.uplinks?.length) this.renderUplinks(s, mdl.uplinks);
    const aps = document.createElement('table');
    aps.className = 'mini tight';
    aps.innerHTML = '<tr><th>Zugangspunkt</th><th class="num">Signal in 1 m</th><th class="num">Mess­punkte</th></tr>';
    for (const a of mdl.aps) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><div></div><div class="muted"></div></td><td class="num">${G.fmt(a.p0, 0)} dBm</td><td class="num">${a.n}</td>`;
      tr.querySelector('div').textContent = a.label;
      tr.querySelector('div.muted').textContent = a.floor;
      aps.appendChild(tr);
    }
    s.appendChild(aps);
    if (mdl.samples.length) {
      const det = document.createElement('details');
      det.className = 'more';
      const sum = document.createElement('summary');
      sum.textContent = `Messpunkte auf diesem Stockwerk (${mdl.samples.length})`;
      det.appendChild(sum);
      // je Zugangspunkt eine kleine Tabelle, damit sie in die Seitenleiste passt
      const byAp = new Map();
      for (const smp of mdl.samples) {
        if (!byAp.has(smp.ap)) byAp.set(smp.ap, []);
        byAp.get(smp.ap).push(smp);
      }
      for (const rows of byAp.values()) {
        div(det, 'small', `${rows[0].ap_label} (${rows[0].ap_floor})`).style.fontWeight = '600';
        const tbl = document.createElement('table');
        tbl.className = 'mini tight';
        tbl.innerHTML = '<tr><th>Gerät</th><th class="num">m</th><th class="num">Decken</th><th class="num">gem.</th><th class="num">Modell</th></tr>';
        for (const smp of rows) {
          const tr = document.createElement('tr');
          if (!smp.used) tr.className = 'muted';
          tr.innerHTML = `<td></td><td class="num">${G.fmt(smp.distance_m, 1)}</td><td class="num">${smp.ceilings || '–'}</td>`
            + `<td class="num">${smp.measured}</td><td class="num">${G.fmt(smp.predicted, 0)}</td>`;
          tr.children[0].textContent = smp.label + (smp.used ? '' : ' *') + (smp.floor !== this.floor.name ? ` (${smp.floor})` : '');
          tbl.appendChild(tr);
        }
        det.appendChild(tbl);
      }
      div(det, 'small muted', 'm: Abstand im Raum; gem.: gemessen, Modell: berechnet (dBm).');
      if (mdl.samples.some((x) => !x.used)) div(det, 'small muted', '* näher als 1 m am Zugangspunkt, nicht zum Eichen verwendet.');
      s.appendChild(det);
    }
    div(s, 'small muted', `Signal = Wert in 1 m − 20·log10(Abstand) − Wandfaktor × Wandverluste − Dämpfung je Decke. Wandverluste: Startwerte je Material und Dicke. Geschosshöhe ${G.fmt(mdl.floor_height_m, 1)} m angenommen. Die Karten zeigen die Sicht der Geräte auf dem gewählten Band.`);
  }

  // Anbindung der Repeater per WLAN (Mesh-Liste): Signal je Band und Einschätzung von FRITZ!OS
  renderUplinks(s, uplinks) {
    const pos = { ok: 'in Ordnung', too_close: 'zu nah', too_far: 'zu weit weg' };
    const tbl = document.createElement('table');
    tbl.className = 'mini tight';
    tbl.innerHTML = '<tr><th>Repeater (WLAN)</th><th class="num">2,4 GHz</th><th class="num">5 GHz</th></tr>';
    for (const u of uplinks) {
      const tr = document.createElement('tr');
      const cell = (b) => {
        const v = u.bands[b];
        if (!v) return '–';
        const p = u.position?.[b];
        return `${v.down ?? '?'} / ${v.up ?? '?'} dBm${p ? `<div class="muted">${pos[p] || p}</div>` : ''}`;
      };
      tr.innerHTML = `<td><div></div><div class="muted"></div></td><td class="num">${cell('2.4')}</td><td class="num">${cell('5')}</td>`;
      tr.querySelector('div').textContent = u.label;
      tr.querySelector('div.muted').textContent = `an ${u.master_label}`;
      tbl.appendChild(tr);
    }
    s.appendChild(tbl);
    div(s, 'small muted', 'Funkstrecke laut FRITZ!Box: Signal am Repeater / an der FRITZ!Box, darunter die Einschätzung von FRITZ!OS zum Platz.');
  }

  renderLegend(parent, legend) {
    const stops = [...legend].sort((a, b) => a.dbm - b.dbm);
    const min = stops[0].dbm;
    const max = stops[stops.length - 1].dbm;
    const grad = stops.map((s) => `rgb(${s.rgb.join(',')}) ${((s.dbm - min) / (max - min)) * 100}%`).join(', ');
    const bar = div(parent, 'legend-bar');
    bar.style.background = `linear-gradient(to right, ${grad})`;
    const ticks = div(parent, 'legend-ticks');
    for (const s of stops) {
      const t = document.createElement('span');
      t.textContent = s.dbm;
      t.style.left = `${((s.dbm - min) / (max - min)) * 100}%`;
      ticks.appendChild(t);
    }
    div(parent, 'small muted', 'dBm – je näher an 0, desto stärker. Ab etwa −70 dBm wird es knapp, unter −80 dBm brechen Verbindungen ab.');
  }

  async measure(btn) {
    btn.disabled = true;
    btn.textContent = 'Messe … (ca. 1 Minute)';
    try {
      const res = await api.measure();
      this.ctx.toast(`Messlauf fertig: ${res.shellys} Shellys, ${res.scanned} mit Scan, ${res.clients} WLAN-Geräte`, 'ok');
      await this.load();
    } catch (e) {
      this.ctx.toast(e.message, 'error');
      btn.disabled = false;
      btn.textContent = 'Neu messen';
    }
  }
}
