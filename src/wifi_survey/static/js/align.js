// Ansicht „Ausrichten“: ein Stockwerk über einem Bezugsstockwerk ausrichten.
// Weltkoordinaten in Metern (Gebäudesystem). Bildpixel -> Meter: /px_per_m, Drehung, Verschiebung.

import { api } from './api.js';
import { el, Viewport, isTyping } from './viewport.js';
import * as G from './geom.js';
import { section, div, button, field } from './plans.js';
import { slider } from './floor.js';

const HINTS = {
  move: 'Ziehen verschiebt das ausgewählte Stockwerk (blau). Drehung über die Felder links. Mausrad zoomt, Leertaste + Ziehen verschiebt die Ansicht.',
  pairs: 'Punktpaare: erst einen Punkt im blauen Stockwerk anklicken, dann dieselbe Stelle im Bezugsstockwerk (grau). Nach zwei Paaren wird ausgerichtet.',
  pan: 'Ziehen verschiebt die Ansicht.',
};

const toLocal = (floor, p) => {
  // Welt (m) -> Bildpixel des Stockwerks
  const t = floor.transform;
  const q = G.rotate([p[0] - t.dx_m, p[1] - t.dy_m], -t.rot_deg);
  return [q[0] * floor.scale.px_per_m, q[1] * floor.scale.px_per_m];
};

const toWorld = (floor, p, transform = floor.transform) => {
  const q = G.rotate([p[0] / floor.scale.px_per_m, p[1] / floor.scale.px_per_m], transform.rot_deg);
  return [q[0] + transform.dx_m, q[1] + transform.dy_m];
};

export class AlignView {
  constructor(ctx) {
    this.ctx = ctx;
    this.tool = 'move';
    this.drag = null;
    this.pairs = [];
    this.saveTimer = null;
    this.saving = null;
    this.dirty = false;
    this.opts = { refOpacity: 0.55, curOpacity: 0.55 };
  }

  isDirty() {
    return this.dirty || !!this.saving;
  }

  async mount() {
    const floors = this.ctx.floorsSorted().filter((f) => f.scale);
    this.vp = new Viewport(this.ctx.svg, { onChange: () => this.onViewChange() });
    this.vp.handler = this;
    this.keyHandler = (e) => this.onKey(e);
    window.addEventListener('keydown', this.keyHandler);
    if (floors.length < 2) {
      this.renderPanel();
      this.ctx.hint('Zum Ausrichten brauchen mindestens zwei Stockwerke einen Maßstab.');
      return;
    }
    const saved = sessionStorage.getItem('ws-align-floor');
    this.cur = floors.find((f) => f.id === saved) || floors.find((f) => f.level !== 0) || floors[1];
    this.ref = this.pickRef(floors);
    this.layer = { paper: el('g', {}, this.vp.world), ref: el('g', {}, this.vp.world), cur: el('g', {}, this.vp.world), marks: el('g', {}, this.vp.world) };
    this.setTool('move');
    this.renderFloors();
    this.renderPanel();
    requestAnimationFrame(() => this.fit());
  }

  async unmount() {
    window.removeEventListener('keydown', this.keyHandler);
    await this.flush();
    this.vp.destroy();
  }

  pickRef(floors) {
    const byId = (id) => floors.find((f) => f.id === id && f.id !== this.cur.id);
    return byId(this.cur.reference_floor) || floors.find((f) => f.level === 0 && f.id !== this.cur.id)
      || floors.find((f) => f.id !== this.cur.id);
  }

  setTool(tool) {
    this.tool = tool;
    this.pairs = [];
    this.ctx.svg.classList.toggle('tool-move', tool === 'move');
    this.ctx.svg.classList.toggle('tool-draw', tool === 'pairs');
    this.ctx.hint(HINTS[tool]);
    if (this.layer) this.renderMarks();
    this.renderPanel();
  }

  fit() {
    const pts = [];
    for (const f of [this.ref, this.cur]) {
      for (const c of [[0, 0], [f.image_w, 0], [0, f.image_h], [f.image_w, f.image_h]]) pts.push(toWorld(f, c));
    }
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    this.vp.fit({ x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) });
  }

  // --- Darstellung ------------------------------------------------------------------------

  groupTransform(f) {
    const t = f.transform;
    return `translate(${t.dx_m} ${t.dy_m}) rotate(${t.rot_deg}) scale(${1 / f.scale.px_per_m})`;
  }

  ensureFilters() {
    if (this.ctx.svg.querySelector('#tint-cur')) return;
    // Graustufenbild einfärben: Weiß bleibt weiß, Schwarz wird zur Farbe (out = c + (1 - c) · L)
    const defs = el('defs', {}, this.ctx.svg);
    for (const [id, [r, g, b]] of [['tint-cur', [0.12, 0.44, 0.92]], ['tint-ref', [0.35, 0.35, 0.35]]]) {
      const f = el('filter', { id, 'color-interpolation-filters': 'sRGB' }, defs);
      el('feColorMatrix', { type: 'matrix', values: `${1 - r} 0 0 0 ${r}  0 ${1 - g} 0 0 ${g}  0 0 ${1 - b} 0 ${b}  0 0 0 1 0` }, f);
    }
  }

  renderFloors() {
    this.ensureFilters();
    this.layer.paper.replaceChildren();
    for (const [key, f, color, opacity] of [['ref', this.ref, 'var(--align-ref)', this.opts.refOpacity], ['cur', this.cur, 'var(--align-cur)', this.opts.curOpacity]]) {
      el('rect', { x: 0, y: 0, width: f.image_w, height: f.image_h, fill: 'var(--plan-paper)', class: `plan-paper paper-${key}`, transform: this.groupTransform(f) }, this.layer.paper);
      const g = this.layer[key];
      g.replaceChildren();
      g.setAttribute('transform', this.groupTransform(f));
      el('image', { href: api.floorImageUrl(f), x: 0, y: 0, width: f.image_w, height: f.image_h, opacity, filter: `url(#tint-${key})`, style: 'mix-blend-mode:multiply' }, g);
      const walls = el('g', { class: 'align-floor-walls' }, g);
      for (const w of f.walls) {
        el('line', { x1: w.a[0], y1: w.a[1], x2: w.b[0], y2: w.b[1], stroke: color, 'stroke-width': w.thickness_px, 'stroke-opacity': 0.45 }, walls);
      }
    }
    this.renderMarks();
  }

  updateTransforms() {
    const tf = this.groupTransform(this.cur);
    this.layer.cur.setAttribute('transform', tf);
    this.layer.paper.querySelector('.paper-cur')?.setAttribute('transform', tf);
    this.renderMarks();
  }

  renderMarks() {
    const g = this.layer?.marks;
    if (!g) return;
    g.replaceChildren();
    const r = this.vp.px(7);
    this.pairs.forEach((p, i) => {
      const w = p.kind === 'cur' ? toWorld(this.cur, p.local) : p.world;
      el('circle', { cx: w[0], cy: w[1], r, class: 'snap-mark', stroke: p.kind === 'cur' ? 'var(--align-cur)' : 'var(--align-ref)' }, g);
      const t = el('text', { x: w[0] + r * 1.3, y: w[1] - r * 1.3, class: 'scale-label', 'font-size': this.vp.px(13) }, g);
      t.textContent = `${p.kind === 'cur' ? 'B' : 'G'}${Math.floor(i / 2) + 1}`;
    });
  }

  onViewChange() {
    this.ctx.status(undefined, `Zoom ${G.fmt(this.vp.s, 1)} px/m`);
    this.renderMarks();
  }

  renderPanel() {
    const { ctx } = this;
    const p = ctx.panel;
    p.replaceChildren();
    const floors = ctx.floorsSorted().filter((f) => f.scale);
    if (floors.length < 2) {
      const s = section(p, 'Ausrichten');
      div(s, 'callout', 'Mindestens zwei Stockwerke brauchen einen Maßstab. Stockwerk öffnen, Werkzeug „Maßstab“ wählen und an einer Bemaßung kalibrieren.');
      const missing = ctx.floorsSorted().filter((f) => !f.scale);
      for (const f of missing) button(s, `${f.name} öffnen`, () => ctx.navigate(`#/stockwerk/${f.id}`));
      return;
    }
    const s = section(p, 'Stockwerke');
    const sel = (label, value, onChange, exclude) => {
      const l = document.createElement('label');
      l.textContent = label;
      const sl = document.createElement('select');
      for (const f of floors) if (f.id !== exclude) sl.appendChild(new Option(f.name, f.id, false, f.id === value));
      sl.addEventListener('change', () => onChange(sl.value));
      l.appendChild(sl);
      s.appendChild(l);
    };
    sel('Ausrichten (blau)', this.cur.id, async (id) => {
      await this.flush();
      this.cur = floors.find((f) => f.id === id);
      sessionStorage.setItem('ws-align-floor', id);
      if (this.ref.id === id) this.ref = this.pickRef(floors);
      this.pairs = [];
      this.renderFloors();
      this.renderPanel();
    });
    sel('an Bezug (grau)', this.ref.id, (id) => {
      this.ref = floors.find((f) => f.id === id);
      this.cur.reference_floor = id;
      this.markDirty();
      this.renderFloors();
      this.renderPanel();
    }, this.cur.id);

    const tools = section(p, 'Werkzeug');
    const tb = div(tools, 'toolbar');
    for (const [tool, label] of [['move', 'Verschieben'], ['pairs', 'Punktpaare'], ['pan', 'Ansicht']]) {
      const b = button(tb, label, () => this.setTool(tool));
      if (this.tool === tool) b.classList.add('active');
    }
    if (this.tool === 'pairs') {
      const n = this.pairs.length;
      const next = ['Punkt 1 im blauen Stockwerk', 'dieselbe Stelle im grauen Stockwerk', 'Punkt 2 im blauen Stockwerk', 'dieselbe Stelle im grauen Stockwerk'][n] || '';
      div(tools, 'small', next ? `Als Nächstes: ${next}` : '');
      div(tools, 'small muted', 'Gute Punkte: Außenecken des Hauses oder Ecken des Treppenhauses, möglichst weit auseinander.');
    }

    const t = this.cur.transform;
    const tf = section(p, 'Lage (blau)');
    const grid = div(tf, 'grid2');
    const dx = field(grid, 'Verschiebung x (m)', 'text', G.fmt(t.dx_m, 3));
    const dy = field(grid, 'Verschiebung y (m)', 'text', G.fmt(t.dy_m, 3));
    const rot = field(tf, 'Drehung (Grad, um die Bildmitte)', 'text', G.fmt(t.rot_deg, 2));
    const initial = { dx: dx.value, dy: dy.value, rot: rot.value };
    const apply = () => {
      const nx = G.parseNumber(dx.value);
      const ny = G.parseNumber(dy.value);
      const nr = G.parseNumber(rot.value);
      if ([nx, ny, nr].some((v) => !Number.isFinite(v))) return;
      // Nur geänderte Felder übernehmen; die Anzeige ist gerundet
      if (rot.value !== initial.rot) this.rotateAboutCenter(nr);
      if (dx.value !== initial.dx) this.cur.transform.dx_m = nx;
      if (dy.value !== initial.dy) this.cur.transform.dy_m = ny;
      this.afterTransform();
    };
    for (const i of [dx, dy, rot]) i.addEventListener('change', apply);
    const row = div(tf, 'row');
    for (const step of [-1, -0.1, 0.1, 1]) {
      button(row, `${step > 0 ? '+' : '−'}${G.fmt(Math.abs(step), step % 1 ? 1 : 0)}°`, () => {
        this.rotateAboutCenter(this.cur.transform.rot_deg + step);
        this.afterTransform();
      });
    }
    button(tf, 'Lage zurücksetzen', () => {
      this.cur.transform = { dx_m: 0, dy_m: 0, rot_deg: 0 };
      this.afterTransform();
    });
    if (this.lastPairError !== undefined) {
      div(tf, 'small muted', `Letzte Punktpaar-Ausrichtung: Abstände weichen um ${G.fmt(this.lastPairError * 100, 1)} cm ab (Maßstäbe beider Stockwerke prüfen, wenn das mehr als einige Zentimeter sind).`);
    }

    const view = section(p, 'Darstellung');
    slider(view, 'Bezug (grau)', this.opts.refOpacity, (v) => { this.opts.refOpacity = v; this.layer.ref.querySelector('image')?.setAttribute('opacity', v); });
    slider(view, 'Stockwerk (blau)', this.opts.curOpacity, (v) => { this.opts.curOpacity = v; this.layer.cur.querySelector('image')?.setAttribute('opacity', v); });
    button(view, 'Ansicht einpassen', () => this.fit());
  }

  // --- Lage ändern ------------------------------------------------------------------------

  rotateAboutCenter(newRot) {
    const f = this.cur;
    const c = [f.image_w / 2, f.image_h / 2];
    const before = toWorld(f, c);
    f.transform.rot_deg = Math.round(newRot * 1000) / 1000;
    const after = toWorld(f, c);
    f.transform.dx_m += before[0] - after[0];
    f.transform.dy_m += before[1] - after[1];
  }

  afterTransform() {
    this.updateTransforms();
    this.markDirty();
    this.renderPanel();
  }

  alignFromPairs() {
    // Paare: [B1, G1, B2, G2]; B in Bildpixeln des blauen Stockwerks, G in Weltmetern
    const f = this.cur;
    const P = [this.pairs[0].local, this.pairs[2].local].map((p) => [p[0] / f.scale.px_per_m, p[1] / f.scale.px_per_m]);
    const Q = [this.pairs[1].world, this.pairs[3].world];
    const angP = Math.atan2(P[1][1] - P[0][1], P[1][0] - P[0][0]);
    const angQ = Math.atan2(Q[1][1] - Q[0][1], Q[1][0] - Q[0][0]);
    const rot = ((angQ - angP) * 180) / Math.PI;
    const mp = G.mid(P[0], P[1]);
    const mq = G.mid(Q[0], Q[1]);
    const rp = G.rotate(mp, rot);
    f.transform = { dx_m: mq[0] - rp[0], dy_m: mq[1] - rp[1], rot_deg: Math.round(rot * 1000) / 1000 };
    this.lastPairError = Math.abs(G.dist(P[0], P[1]) - G.dist(Q[0], Q[1]));
    this.pairs = [];
    this.afterTransform();
    this.ctx.toast(`Ausgerichtet: Drehung ${G.fmt(rot, 2)}°, Abweichung ${G.fmt(this.lastPairError * 100, 1)} cm`, 'ok');
  }

  markDirty() {
    this.dirty = true;
    this.ctx.setSaveState('dirty');
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.save(), 500);
  }

  async save() {
    clearTimeout(this.saveTimer);
    if (this.saving) await this.saving;
    if (!this.dirty) return;
    this.dirty = false;
    const f = this.cur;
    this.ctx.setSaveState('saving');
    this.saving = api.updateFloor(f.id, { transform: f.transform, reference_floor: this.ref.id })
      .then(() => { this.retryDelay = 0; if (!this.dirty) this.ctx.setSaveState('saved'); })
      .catch((e) => {
        if (!this.retryDelay) this.ctx.toast(`Speichern fehlgeschlagen, neuer Versuch läuft: ${e.message}`, 'error');
        this.dirty = true;
        this.retryDelay = Math.min(30000, (this.retryDelay || 1500) * 2);
        this.ctx.setSaveState('error', `Speichern fehlgeschlagen – neuer Versuch in ${Math.round(this.retryDelay / 1000)} s`);
        clearTimeout(this.saveTimer);
        this.saveTimer = setTimeout(() => this.save(), this.retryDelay);
      })
      .finally(() => { this.saving = null; });
    await this.saving;
  }

  async flush() {
    clearTimeout(this.saveTimer);
    if (this.dirty) await this.save();
    else if (this.saving) await this.saving;
  }

  // --- Zeiger -----------------------------------------------------------------------------

  down(e, w) {
    if (e.button !== 0 || !this.cur) return false;
    if (this.tool === 'pan') return 'pan';
    if (this.tool === 'pairs') {
      const expectCur = this.pairs.length % 2 === 0;
      this.pairs.push(expectCur ? { kind: 'cur', local: toLocal(this.cur, w) } : { kind: 'ref', world: w });
      if (this.pairs.length === 4) this.alignFromPairs();
      else { this.renderMarks(); this.renderPanel(); }
      return true;
    }
    this.drag = { start: w, orig: { ...this.cur.transform } };
    return true;
  }

  hover(e, w) {
    this.ctx.status(`x ${G.fmt(w[0], 2)} m · y ${G.fmt(w[1], 2)} m`);
  }

  move(e, w) {
    if (!this.drag) return;
    this.cur.transform = { ...this.drag.orig, dx_m: this.drag.orig.dx_m + w[0] - this.drag.start[0], dy_m: this.drag.orig.dy_m + w[1] - this.drag.start[1] };
    this.updateTransforms();
  }

  up() {
    if (!this.drag) return;
    this.drag = null;
    this.afterTransform();
  }

  cancel() {
    if (this.drag) {
      this.cur.transform = this.drag.orig;
      this.drag = null;
      this.updateTransforms();
    }
  }

  onKey(e) {
    if (isTyping(e) || !this.cur) return;
    if (e.key === 'Escape') { this.pairs = []; this.renderMarks(); this.renderPanel(); }
    else if (e.key === 'f' || e.key === 'F') this.fit();
    else if (e.key.startsWith('Arrow')) {
      const step = e.shiftKey ? 0.1 : 0.01;
      const t = this.cur.transform;
      if (e.key === 'ArrowLeft') t.dx_m -= step;
      if (e.key === 'ArrowRight') t.dx_m += step;
      if (e.key === 'ArrowUp') t.dy_m -= step;
      if (e.key === 'ArrowDown') t.dy_m += step;
      e.preventDefault();
      this.afterTransform();
    }
  }
}
