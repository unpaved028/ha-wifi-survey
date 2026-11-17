// Ansicht „Stockwerk“: Wände auf dem Grundriss prüfen, korrigieren und zeichnen.
// Koordinaten = Pixel des Stockwerkbilds. Änderungen werden automatisch gespeichert.

import { api } from './api.js';
import { el, Viewport, isTyping } from './viewport.js';
import * as G from './geom.js';
import { section, div, button, field } from './plans.js';

const SNAP_PX = 10;      // Fangradius in Bildschirmpixeln
const UNCERTAIN = 0.75;  // automatisch erkannte Wände unter dieser Sicherheit werden markiert
const SAVE_DELAY = 600;
const isCoarse = () => window.matchMedia?.('(pointer: coarse)').matches;

const TEXTS = {
  addWallMode: '+ Weitere Wand wählen',
  clearSel: 'Auswahl aufheben',
  endDraw: 'Linienzug beenden',
  drawActive: 'Linienzug läuft: nächste Ecke tippen oder beenden.',
  finishArea: 'Umriss schließen',
  cancel: 'Abbrechen',
  deleteVertex: 'Ecke löschen',
  showInPlan: 'Im Plan zeigen',
};

const TOOL_ICONS = {
  select: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M13.64 21.97A1.5 1.5 0 0 1 11.7 21l-2.18-5.02-4.02 3.47V2.6l14 11.9h-5.82l2.19 5.03a1.5 1.5 0 0 1-.83 1.96l-1.4.48Z"/></svg>',
  draw: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M20.71 7.04c.39-.39.39-1.04 0-1.41l-2.34-2.34c-.37-.39-1.02-.39-1.41 0l-1.84 1.83 3.75 3.75M3 17.25V21h3.75L17.81 9.93l-3.75-3.75L3 17.25Z"/></svg>',
  split: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M9.64 7.64c.23-.5.36-1.05.36-1.64a4 4 0 1 0-4 4c.59 0 1.14-.13 1.64-.36L10 12l-2.36 2.36C7.14 14.13 6.59 14 6 14a4 4 0 1 0 4 4c0-.59-.13-1.14-.36-1.64L12 14l7 7h3v-1L9.64 7.64M6 8a2 2 0 1 1 0-4 2 2 0 0 1 0 4m0 10a2 2 0 1 1 0-4 2 2 0 0 1 0 4m6-5.5a.5.5 0 1 1 0-1 .5.5 0 0 1 0 1M19 3l-6 6 2 2 7-7V3h-3Z"/></svg>',
  scale: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M21 6H3a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h18a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2m0 10H3V8h2v4h2V8h2v2h2V8h2v4h2V8h2v2h2V8h2v8Z"/></svg>',
  devices: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M12 3C7.79 3 3.7 4.41.38 7L2 9.06C4.88 6.81 8.43 5.5 12 5.5s7.12 1.31 10 3.56L23.62 7C20.3 4.41 16.22 3 12 3m0 5c-2.87 0-5.64.96-7.9 2.71l1.62 2.06A10.42 10.42 0 0 1 12 10.5c2.27 0 4.48.74 6.28 2.27l1.62-2.06C17.64 8.96 14.87 8 12 8m5 7h-4v-3h-2v3H7a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2m-8 4H7v-2h2v2m4 0h-2v-2h2v2m4 0h-2v-2h2v2Z"/></svg>',
  area: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M3 3h6v2H5v4H3V3m12 0h6v6h-2V5h-4V3M3 15h2v4h4v2H3v-6m16 0h2v6h-6v-2h4v-4M7 7h10v10H7V7m2 2v6h6V9H9Z"/></svg>',
  rooms: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M3 3h18v18H3V3Zm2 2v14h14V5H5Zm6 0h2v5h-2V5Zm0 9h2v5h-2v-5Z"/></svg>',
  fit: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M15 3l2.3 2.3-2.89 2.87 1.42 1.42L18.7 6.7 21 9V3h-6M3 9l2.3-2.3 2.87 2.89 1.42-1.42L6.7 5.3 9 3H3v6m6 12l-2.3-2.3 2.89-2.87-1.42-1.42L5.3 17.3 3 15v6h6m12-6l-2.3 2.3-2.87-2.89-1.42 1.42 2.89 2.87L15 21h6v-6Z"/></svg>',
};

const HINTS = {
  select: 'Klick wählt eine Wand, Umschalt+Klick erweitert die Auswahl, Umschalt+Ziehen wählt per Rahmen. '
    + 'Enden ziehen ändert die Länge (Umschalt: 45°-Raster), Wand ziehen verschiebt. Entf löscht. Ziehen auf freier Fläche verschiebt die Ansicht.',
  draw: 'Klick setzt den Anfang, jeder weitere Klick eine Ecke. Doppelklick, Esc oder Rechtsklick beendet. '
    + 'Winkel rasten in 45°-Schritten ein (Alt: frei), Enden rasten an anderen Wänden ein.',
  split: 'Klick auf eine Wand teilt sie an dieser Stelle in zwei Wände. Für eine Fenster- oder Türöffnung zweimal teilen und das Mittelstück löschen.',
  devices: 'Gerät in der Liste links wählen, dann auf den Plan klicken. Platzierte Geräte lassen sich ziehen, Entf entfernt sie.',
  area: 'Hausfläche: Ecken ziehen, „+“ auf einer Kante fügt eine Ecke ein, Entf löscht die gewählte Ecke oder Fläche. '
    + 'Gezählt wird die Fläche innerhalb der Umrisse ohne Wände; sie geht in Abdeckung und Suche ein.',
  rooms: 'Räume entstehen aus den Wänden; Türöffnungen bis 1,2 m gelten als geschlossen. Klick in einen Raum wählt ihn, '
    + 'links den Namen eintragen. Fehlt eine Trennung, die Wand zeichnen (Werkzeug „Wand zeichnen“).',
  scale: 'Zwei Punkte einer bekannten Bemaßung anklicken, z. B. die Enden einer Maßkette, dann die Länge in Metern eingeben. '
    + 'Umschalt hält die Linie waagrecht oder senkrecht.',
};

function loadOpts() {
  const defaults = { imageOpacity: 1, wallOpacity: 0.55, showUncertain: true, showDeviceLabels: true, newMaterial: 'hochlochziegel',
    newThicknessCm: 11.5, newThicknessPx: 10, angleSnap: true, shortCm: 30, shortPx: 25 };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem('ws-floor-opts') || '{}') };
  } catch {
    return defaults;
  }
}

export class FloorView {
  constructor(ctx, floor) {
    this.ctx = ctx;
    this.floor = floor;
    this.walls = structuredClone(floor.walls);
    this.devices = structuredClone(floor.devices || []);
    this.catalog = null;      // Geräteliste aus dem letzten Messlauf
    this.placing = null;      // Katalogeintrag, der beim nächsten Klick gesetzt wird
    this.selDevice = null;
    this.devQuery = '';
    this.devKind = 'all';
    this.selection = new Set();
    this.multiSelect = false;
    this.shortPinned = false;
    this.tool = 'select';
    this.undoStack = [];
    this.redoStack = [];
    this.saveTimer = null;
    this.saving = null;
    this.dirty = false;
    this.drag = null;
    this.draft = null;        // Zeichnen: { start, cur, snap }
    this.scaleDraft = null;   // Maßstab: { a, b, cur }
    this.uncertainIndex = -1;
    this.opts = loadOpts();
    this.outline = structuredClone(floor.outline || null);   // eigene Hausfläche (Umrisse) oder null = automatisch
    this.savedOutline = JSON.stringify(this.outline);
    this.outlineInfo = null;  // Vorschlag, Flächen und Umrisse anderer Stockwerke (GET …/outline)
    this.outlineDraft = null; // neuer Umriss: { pts, cur }
    this.selVertex = null;    // { pi, vi }
    this.selPoly = null;
    this.previewOthers = null;
    this.matColor = Object.fromEntries(ctx.materials.map((m) => [m.id, m.color]));
  }

  get ppm() {
    return this.floor.scale ? this.floor.scale.px_per_m : null;
  }

  isDirty() {
    return this.dirty || !!this.saving;
  }

  async mount() {
    const { ctx, floor } = this;
    this.vp = new Viewport(ctx.svg, { onChange: () => this.onViewChange() });
    this.vp.handler = this;
    this.vp.wantsRightClick = false;
    const w = this.vp.world;
    this.layer = {
      image: el('g', {}, w),
      area: el('g', {}, w),
      rooms: el('g', {}, w),
      walls: el('g', {}, w),
      warn: el('g', {}, w),
      hits: el('g', {}, w),
      scale: el('g', {}, w),
      devices: el('g', {}, w),
      sel: el('g', {}, w),
      draft: el('g', {}, w),
      areaTop: el('g', {}, w),
      roomsTop: el('g', {}, w),
    };
    el('rect', { x: 0, y: 0, width: floor.image_w, height: floor.image_h, fill: 'var(--plan-paper)', class: 'plan-paper' }, this.layer.image);
    this.imageEl = el('image', { href: api.floorImageUrl(floor), x: 0, y: 0, width: floor.image_w, height: floor.image_h, opacity: this.opts.imageOpacity, class: 'plan-img' }, this.layer.image);
    this.vp.contentBox = { x: 0, y: 0, w: floor.image_w, h: floor.image_h };

    this.keyHandler = (e) => this.onKey(e);
    this.dblHandler = () => {
      if (this.tool === 'draw') this.endDraw();
      else if (this.tool === 'area' && this.outlineDraft) this.finishOutline();
    };
    window.addEventListener('keydown', this.keyHandler);
    ctx.svg.addEventListener('dblclick', this.dblHandler);
    this.setTool(this.walls.length || this.ppm ? 'select' : 'scale', false);
    this.renderAll();
    requestAnimationFrame(() => this.vp.fit());
    ctx.setSaveState('saved');
  }

  async unmount() {
    window.removeEventListener('keydown', this.keyHandler);
    this.ctx.svg.removeEventListener('dblclick', this.dblHandler);
    await this.flush();
    this.vp.destroy();
  }

  // --- Änderungen, Rückgängig, Speichern --------------------------------------------------

  snapshot() {
    return JSON.stringify({ w: this.walls, d: this.devices, o: this.outline });
  }

  restore(snap) {
    const s = JSON.parse(snap);
    this.walls = s.w;
    this.devices = s.d;
    this.outline = s.o ?? null;
  }

  commit(before) {
    if (before === this.snapshot()) return;
    this.undoStack.push(before);
    if (this.undoStack.length > 200) this.undoStack.shift();
    this.redoStack = [];
    this.markDirty();
  }

  change(mutator) {
    const before = this.snapshot();
    mutator();
    this.commit(before);
    this.renderAll();
  }

  // Bearbeitete automatische Wände gelten als geprüft: Eine neue Erkennung überschreibt sie nicht.
  touch(wall) {
    if (wall.source === 'auto') {
      wall.source = 'manual';
      wall.confidence = null;
    }
  }

  undo() {
    if (!this.undoStack.length) return;
    this.redoStack.push(this.snapshot());
    this.restore(this.undoStack.pop());
    this.afterHistory();
  }

  redo() {
    if (!this.redoStack.length) return;
    this.undoStack.push(this.snapshot());
    this.restore(this.redoStack.pop());
    this.afterHistory();
  }

  afterHistory() {
    const ids = new Set(this.walls.map((w) => w.id));
    this.selection = new Set([...this.selection].filter((id) => ids.has(id)));
    if (this.selDevice && !this.devices.some((d) => d.id === this.selDevice)) this.selDevice = null;
    this.selVertex = null;
    if (!this.outline?.[this.selPoly]) this.selPoly = null;
    this.markDirty();
    this.renderAll();
  }

  markDirty() {
    this.dirty = true;
    this.ctx.setSaveState('dirty');
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.save(), SAVE_DELAY);
  }

  async save() {
    clearTimeout(this.saveTimer);
    if (this.saving) await this.saving;
    if (!this.dirty) return;
    this.dirty = false;
    const walls = structuredClone(this.walls);
    const devices = structuredClone(this.devices);
    const outline = structuredClone(this.outline);
    const outlineJson = JSON.stringify(outline);
    this.ctx.setSaveState('saving');
    this.saving = api.putWalls(this.floor.id, walls)
      .then(() => api.putDevices(this.floor.id, devices))
      .then(async (f) => {
        this.floor.walls = f.walls;
        this.floor.devices = f.devices;
        const pf = this.ctx.project.floors.find((x) => x.id === f.id);
        if (pf) { pf.walls = f.walls; pf.devices = f.devices; }
        if (outlineJson !== this.savedOutline) {
          const r = await api.putOutline(this.floor.id, outline);
          this.savedOutline = outlineJson;
          this.floor.outline = r.user;
          if (pf) pf.outline = r.user;
          if (this.outlineInfo) Object.assign(this.outlineInfo, { user: r.user, area_m2: r.area_m2 });
          if (this.tool === 'area') this.renderPanel();
        }
        this.retryDelay = 0;
        if (!this.dirty) this.ctx.setSaveState('saved');
      })
      .catch((e) => {
        if (e.status === 409 || e.status === 400 || e.status === 422) {
          // inhaltlicher Fehler (z. B. Gerät schon anderswo platziert): nicht endlos wiederholen
          this.ctx.setSaveState('error');
          this.ctx.toast(`Nicht gespeichert: ${e.message}`, 'error');
          return;
        }
        // z. B. kurzer Neustart des Dienstes: Änderungen behalten und selbst erneut speichern
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

  // --- Werkzeuge --------------------------------------------------------------------------

  setTool(tool, render = true) {
    this.tool = tool;
    this.draft = null;
    if (tool !== 'scale') this.scaleDraft = null;
    const svg = this.ctx.svg;
    svg.classList.toggle('tool-draw', tool === 'draw');
    svg.classList.toggle('tool-scale', tool === 'scale');
    svg.classList.toggle('tool-devices', tool === 'devices');
    svg.classList.toggle('tool-split', tool === 'split');
    svg.classList.toggle('tool-area', tool === 'area');
    svg.classList.toggle('tool-rooms', tool === 'rooms');
    if (tool !== 'select') this.multiSelect = false;
    if (tool !== 'devices') this.placing = null;
    if (tool === 'devices' && !this.catalog) this.loadCatalog();
    if (tool !== 'area') Object.assign(this, { outlineDraft: null, selVertex: null, selPoly: null, previewOthers: null });
    else {
      this.selDevice = null;
      this.selection.clear();
      this.loadOutline();
    }
    if (tool === 'rooms') {
      this.selDevice = null;
      this.selection.clear();
      this.loadRooms();
    } else this.selRoom = null;
    this.ctx.hint(HINTS[tool]);
    if (render) this.renderAll();
  }

  newThicknessPx() {
    return this.ppm ? (this.opts.newThicknessCm / 100) * this.ppm : this.opts.newThicknessPx;
  }

  saveOpts() {
    localStorage.setItem('ws-floor-opts', JSON.stringify(this.opts));
  }

  snapPoint(p, { exclude = new Set(), from = null, angle = false } = {}) {
    const r = this.vp.px(SNAP_PX);
    let best = null;
    let bd = r;
    for (const w of this.walls) {
      if (exclude.has(w.id)) continue;
      for (const q of [w.a, w.b]) {
        const d = G.dist(p, q);
        if (d < bd) { bd = d; best = { pt: q.slice(), kind: 'end' }; }
      }
    }
    if (best) return best;
    let q = p;
    if (from && angle) q = G.snapAngle(from, p, 45);
    bd = r;
    for (const w of this.walls) {
      if (exclude.has(w.id)) continue;
      let cand;
      if (from && angle) {
        cand = intersectRaySegment(from, q, w.a, w.b);
        if (cand && G.dist(cand, q) >= bd) cand = null;
      } else {
        const pr = G.projectOnSegment(q, w.a, w.b);
        cand = pr.d < bd ? pr.pt : null;
      }
      if (cand) { bd = G.dist(cand, q); best = { pt: cand, kind: 'line' }; }
    }
    return best || { pt: q, kind: from && angle ? 'angle' : 'free' };
  }

  // --- Zeiger -----------------------------------------------------------------------------

  down(e, w) {
    if (e.button !== 0) return false;
    if (this.tool === 'draw') return this.drawClick(e, w);
    if (this.tool === 'scale') return this.scaleClick(e, w);
    if (this.tool === 'split') return this.splitClick(e, w);
    if (this.tool === 'area') return this.areaDown(e, w);
    if (this.tool === 'rooms') return this.roomsDown(e, w);

    const t = e.target;
    const devEl = t.closest?.('[data-dev]');
    if (devEl) {
      const dev = this.devices.find((x) => x.id === devEl.dataset.dev);
      this.selDevice = dev.id;
      this.selection.clear();
      this.drag = { kind: 'device', dev, start: w, orig: dev.pos.slice(), before: this.snapshot(), moved: false };
      this.renderAll();
      return true;
    }
    if (this.tool === 'devices') {
      if (this.placing) {
        const entry = this.placing;
        const dev = { id: G.newId('d'), key: entry.key, kind: entry.kind, label: entry.label, pos: [round2(w[0]), round2(w[1])] };
        if (entry.role) Object.assign(dev, { role: entry.role, uplink: entry.uplink || null });
        this.placing = null;
        this.selDevice = dev.id;
        this.change(() => { this.devices.push(dev); });
        this.ctx.hint(HINTS.devices);
        return true;
      }
      if (this.selDevice) { this.selDevice = null; this.renderAll(); }
      return 'pan';
    }
    if (this.selDevice) this.selDevice = null;
    const id = t.dataset?.id;
    if (t.classList.contains('handle') && id) {
      const wall = this.walls.find((x) => x.id === id);
      const end = t.dataset.end;
      const pos = wall[end];
      // Enden anderer Wände, die genau hier liegen, wandern mit (Ecken bleiben geschlossen)
      const linked = [];
      for (const o of this.walls) {
        if (o.id === id) continue;
        for (const k of ['a', 'b']) if (G.dist(o[k], pos) < 0.75) linked.push([o, k]);
      }
      this.drag = { kind: 'end', wall, end, linked, before: this.snapshot(), moved: false };
      return true;
    }
    if (id) {
      if (e.shiftKey || this.multiSelect) {
        if (this.selection.has(id)) this.selection.delete(id);
        else this.selection.add(id);
        this.renderAll();
        return true;
      }
      if (!this.selection.has(id)) this.selection = new Set([id]);
      const origs = new Map(this.walls.filter((x) => this.selection.has(x.id)).map((x) => [x.id, { a: x.a.slice(), b: x.b.slice() }]));
      this.drag = { kind: 'move', start: w, origs, before: this.snapshot(), moved: false };
      this.ctx.svg.classList.add('tool-move');
      this.renderAll();
      return true;
    }
    if (e.shiftKey) {
      this.drag = { kind: 'box', start: w, rect: G.normRect(w, w) };
      return true;
    }
    if (this.selection.size) {
      this.selection.clear();
      this.renderAll();
    }
    return 'pan';
  }

  hover(e, w) {
    const pos = this.ppm
      ? `x ${G.fmt(w[0] / this.ppm, 2)} m · y ${G.fmt(w[1] / this.ppm, 2)} m`
      : `x ${G.fmt(w[0], 0)} px · y ${G.fmt(w[1], 0)} px`;
    this.ctx.status(pos);
    if (this.tool === 'draw') {
      const s = this.snapPoint(w, { from: this.draft?.start, angle: this.opts.angleSnap && !e.altKey });
      this.draft = { ...(this.draft || {}), cur: s.pt, snap: s.kind };
      if (this.draft.start) {
        const len = G.dist(this.draft.start, s.pt);
        this.ctx.hint(`Länge ${G.fmtLength(len, this.ppm)} – Klick setzt die Ecke, Doppelklick/Esc beendet.`);
      }
      this.renderDraft();
    } else if (this.tool === 'split') {
      this.splitPreview = this.splitTarget(w);
      this.renderDraft();
    } else if (this.tool === 'scale' && this.scaleDraft && !this.scaleDraft.b) {
      this.scaleDraft.cur = e.shiftKey ? G.snapAngle(this.scaleDraft.a, w, 90) : w;
      this.renderDraft();
    } else if (this.tool === 'area' && this.outlineDraft) {
      const pts = this.outlineDraft.pts;
      this.outlineDraft.cur = this.areaSnap(e, w, pts[pts.length - 1]);
      if (pts.length) {
        this.ctx.hint(`Kante ${G.fmtLength(G.dist(pts[pts.length - 1], this.outlineDraft.cur), this.ppm)} – Klick setzt die Ecke, `
          + 'Enter, Doppelklick oder Klick auf die erste Ecke schließt den Umriss, Esc bricht ab.');
      }
      this.renderArea();
    }
  }

  move(e, w) {
    const d = this.drag;
    if (!d) return;
    if (d.kind === 'end') {
      const other = d.end === 'a' ? d.wall.b : d.wall.a;
      const exclude = new Set([d.wall.id, ...d.linked.map(([o]) => o.id)]);
      const s = this.snapPoint(w, { exclude, from: other, angle: e.shiftKey });
      d.wall[d.end] = s.pt;
      for (const [o, k] of d.linked) o[k] = s.pt.slice();
      d.moved = true;
      d.snap = s;
      this.renderAll(false);
    } else if (d.kind === 'move') {
      const dx = w[0] - d.start[0];
      const dy = w[1] - d.start[1];
      if (!d.moved && Math.hypot(dx, dy) < this.vp.px(3)) return;
      for (const x of this.walls) {
        const o = d.origs.get(x.id);
        if (!o) continue;
        x.a = [o.a[0] + dx, o.a[1] + dy];
        x.b = [o.b[0] + dx, o.b[1] + dy];
      }
      d.moved = true;
      this.renderAll(false);
    } else if (d.kind === 'box') {
      d.rect = G.normRect(d.start, w);
      this.renderDraft();
    } else if (d.kind === 'device') {
      const dx = w[0] - d.start[0];
      const dy = w[1] - d.start[1];
      if (!d.moved && Math.hypot(dx, dy) < this.vp.px(3)) return;
      d.dev.pos = [round2(d.orig[0] + dx), round2(d.orig[1] + dy)];
      d.moved = true;
      this.renderDevices();
    } else if (d.kind === 'vertex') {
      const pg = this.outline[d.pi];
      pg[d.vi] = this.areaSnap(e, w, pg[(d.vi - 1 + pg.length) % pg.length]);
      d.moved = true;
      this.renderArea();
      this.updateAreaStats();
    }
  }

  up(e) {
    const d = this.drag;
    this.drag = null;
    this.ctx.svg.classList.remove('tool-move');
    if (!d) return;
    if (d.kind === 'box') {
      if (!e.shiftKey) this.selection.clear();
      for (const w of this.walls) if (G.inRect(G.mid(w.a, w.b), d.rect)) this.selection.add(w.id);
      this.renderAll();
      return;
    }
    if (d.kind === 'device' || d.kind === 'vertex') {
      if (d.moved) this.commit(d.before);
      this.renderAll();
      if (!d.moved && window.innerWidth <= 820) {
        document.getElementById(d.kind === 'device' ? 'dev-panel' : 'area-panel')?.scrollIntoView({ block: 'nearest' });
      }
      return;
    }
    if (d.moved) {
      if (d.kind === 'end') {
        this.touch(d.wall);
        for (const [o] of d.linked) this.touch(o);
      } else {
        for (const x of this.walls) if (d.origs.has(x.id)) this.touch(x);
      }
      this.commit(d.before);
    }
    this.renderAll();
    if (!d.moved && d.kind === 'move' && window.innerWidth <= 820) {
      document.getElementById('sel-panel')?.scrollIntoView({ block: 'nearest' });
    }
  }

  cancel() {
    if (this.drag && this.drag.before) {
      this.restore(this.drag.before);
    }
    this.drag = null;
    this.renderAll();
  }

  rightClick() {
    if (this.tool === 'draw') this.endDraw();
    else if (this.tool === 'area' && this.outlineDraft) this.finishOutline();
    else if (this.tool === 'scale') { this.scaleDraft = null; this.renderAll(); }
  }

  drawClick(e, w) {
    const s = this.snapPoint(w, { from: this.draft?.start, angle: this.opts.angleSnap && !e.altKey });
    if (!this.draft?.start) {
      this.draft = { start: s.pt, cur: s.pt, snap: s.kind };
      this.renderDraft();
      this.renderPanel();
      return true;
    }
    const a = this.draft.start;
    const b = s.pt;
    if (G.dist(a, b) < 1) return true;
    const wall = { id: G.newId('w'), a, b, thickness_px: round2(this.newThicknessPx()), material: this.opts.newMaterial, source: 'manual', confidence: null };
    this.change(() => { this.walls.push(wall); });
    this.draft = { start: b, cur: b, snap: s.kind };
    this.renderDraft();
    this.renderPanel();
    return true;
  }

  endDraw() {
    this.draft = null;
    this.ctx.hint(HINTS.draw);
    this.renderDraft();
    this.renderPanel();
  }

  scaleClick(e, w) {
    if (!this.scaleDraft || this.scaleDraft.b) {
      this.scaleDraft = { a: w, cur: w };
    } else {
      const b = e.shiftKey ? G.snapAngle(this.scaleDraft.a, w, 90) : w;
      if (G.dist(this.scaleDraft.a, b) < 5) return true;
      this.scaleDraft.b = b;
      this.renderPanel();
      setTimeout(() => document.getElementById('scale-length')?.focus(), 0);
    }
    this.renderDraft();
    return true;
  }

  async applyScale(lengthStr) {
    const length = G.parseNumber(lengthStr);
    if (!(length > 0)) {
      this.ctx.toast('Bitte eine Länge in Metern eingeben, z. B. 7,76', 'error');
      return;
    }
    const { a, b } = this.scaleDraft;
    try {
      const f = await api.setScale(this.floor.id, { a, b, length_m: length });
      this.floor.scale = f.scale;
      const pf = this.ctx.project.floors.find((x) => x.id === f.id);
      if (pf) pf.scale = f.scale;
      this.scaleDraft = null;
      this.ctx.toast(`Maßstab gesetzt: 1 m = ${G.fmt(f.scale.px_per_m, 1)} px`, 'ok');
      this.setTool('select');
      this.onViewChange();
    } catch (err) {
      this.ctx.toast(err.message, 'error');
    }
  }

  async runDetection() {
    const auto = this.walls.filter((w) => w.source === 'auto').length;
    if (auto && !confirm(`${auto} automatisch erkannte Wände werden ersetzt. Gezeichnete und bereits korrigierte Wände bleiben erhalten. Fortfahren?`)) return;
    await this.flush();
    const before = this.snapshot();
    this.ctx.setSaveState('saving', 'Erkenne Wände …');
    try {
      const res = await api.detect(this.floor.id, { mode: 'replace_auto', snap_thickness: true, style: this.opts.wallStyle || 'auto' });
      this.walls = structuredClone(res.floor.walls);
      this.floor.walls = res.floor.walls;
      this.undoStack.push(before);
      this.redoStack = [];
      this.selection.clear();
      this.ctx.setSaveState('saved');
      const unsure = this.walls.filter((w) => this.isUncertain(w)).length;
      const st = res.stats;
      const cleaned = st.raw_segments ? ` Aus ${st.raw_segments} Rohstücken: ${st.merged} verbunden, ${st.joined} Enden angeschlossen, ${st.dropped} verworfen.` : '';
      const asOutline = st.hatch_direction === 'Umriss' ? ' Wände als Umrisslinien erkannt.' : '';
      const skipped = st.skipped_covered ? ` ${st.skipped_covered} Vorschläge lagen auf bearbeiteten Wänden und wurden weggelassen.` : '';
      this.ctx.toast(`${res.added} Wände erkannt${res.removed ? `, ${res.removed} ersetzt` : ''}, ${unsure} unsicher (orange).${cleaned}${skipped}${asOutline}`, 'ok');
      this.renderAll();
    } catch (e) {
      this.ctx.setSaveState('error');
      this.ctx.toast(`Erkennung fehlgeschlagen: ${e.message}`, 'error');
    }
  }

  snapThickness(walls) {
    if (!this.ppm) return;
    const classes = this.ctx.classes;
    let n = 0;
    this.change(() => {
      for (const w of walls) {
        const cm = (w.thickness_px / this.ppm) * 100;
        const best = classes.reduce((p, c) => (Math.abs(c - cm) < Math.abs(p - cm) ? c : p), classes[0]);
        const px = round2((best / 100) * this.ppm);
        if (Math.abs(px - w.thickness_px) > 0.01) { w.thickness_px = px; n += 1; }
      }
    });
    this.ctx.toast(`${n} Wanddicken auf Normmaß gerundet`, 'ok');
  }

  isUncertain(w) {
    return w.source === 'auto' && w.confidence !== null && w.confidence < UNCERTAIN;
  }

  nextUncertain() {
    const list = this.walls.filter((w) => this.isUncertain(w))
      .sort((p, q) => G.mid(p.a, p.b)[1] - G.mid(q.a, q.b)[1] || G.mid(p.a, p.b)[0] - G.mid(q.a, q.b)[0]);
    if (!list.length) {
      this.ctx.toast('Keine unsicheren Wände mehr', 'ok');
      return;
    }
    this.uncertainIndex = (this.uncertainIndex + 1) % list.length;
    const w = list[this.uncertainIndex];
    this.selection = new Set([w.id]);
    this.vp.centerOn(G.mid(w.a, w.b), Math.max(this.vp.s, 1.2));
    this.renderAll();
  }

  // --- Korrektur-Werkzeuge -----------------------------------------------------------------

  // Wand unter dem Zeiger und Schnittpunkt darauf (für „Teilen“)
  splitTarget(p) {
    let best = null;
    for (const w of this.walls) {
      const pr = G.projectOnSegment(p, w.a, w.b);
      const reach = Math.max(w.thickness_px / 2, this.vp.px(SNAP_PX));
      if (pr.d <= reach && (!best || pr.d < best.d)) best = { wall: w, pt: pr.pt, t: pr.t, d: pr.d };
    }
    if (!best) return null;
    const len = G.dist(best.wall.a, best.wall.b);
    const margin = Math.min(len / 2 - 0.5, this.vp.px(4));
    if (best.t * len < margin || (1 - best.t) * len < margin) return null;  // zu nah am Ende
    return best;
  }

  splitClick(e, w) {
    const target = this.splitTarget(w);
    if (!target) return 'pan';
    const { wall, pt } = target;
    const piece = { ...structuredClone(wall), id: G.newId('w'), a: [round2(pt[0]), round2(pt[1])] };
    this.change(() => {
      wall.b = [round2(pt[0]), round2(pt[1])];
      this.touch(wall);
      this.touch(piece);
      this.walls.splice(this.walls.indexOf(wall) + 1, 0, piece);
    });
    this.selection = new Set([wall.id, piece.id]);
    this.splitPreview = null;
    this.renderAll();
    return true;
  }

  mergeSelected() {
    const sel = this.walls.filter((w) => this.selection.has(w.id));
    if (sel.length < 2) {
      this.ctx.toast('Zum Zusammenführen mindestens zwei Wände auswählen (Umschalt+Klick)', 'error');
      return;
    }
    const len = (w) => G.dist(w.a, w.b);
    const ref = sel.reduce((p, q) => (len(q) > len(p) ? q : p));
    const u = G.unit(ref.a, ref.b);
    const n = [-u[1], u[0]];
    const maxT = Math.max(...sel.map((w) => w.thickness_px));
    for (const w of sel) {
      if (Math.abs(G.cross(u, G.unit(w.a, w.b))) > Math.sin((8 * Math.PI) / 180)) {
        this.ctx.toast('Die Wände laufen nicht in dieselbe Richtung. Zusammenführen geht nur für Stücke auf einer Linie – für Ecken „Ecke schließen“ nutzen.', 'error');
        return;
      }
    }
    const offs = sel.map((w) => G.dot(G.sub(G.mid(w.a, w.b), ref.a), n));
    const spread = Math.max(...offs) - Math.min(...offs);
    if (spread > maxT) {
      this.ctx.toast(`Die Wände liegen nicht auf einer Linie (seitlicher Versatz ${G.fmtLength(spread, this.ppm)}).`, 'error');
      return;
    }
    const along = sel.flatMap((w) => [w.a, w.b].map((q) => G.dot(G.sub(q, ref.a), u)));
    const tMin = Math.min(...along);
    const tMax = Math.max(...along);
    const total = sel.reduce((s, w) => s + len(w), 0) || 1;
    const off = sel.reduce((s, w, i) => s + offs[i] * len(w), 0) / total;
    const thick = sel.reduce((s, w) => s + w.thickness_px * len(w), 0) / total;
    const byMat = {};
    for (const w of sel) byMat[w.material] = (byMat[w.material] || 0) + len(w);
    const material = Object.entries(byMat).sort((x, y) => y[1] - x[1])[0][0];
    const base = [ref.a[0] + n[0] * off, ref.a[1] + n[1] * off];
    const merged = {
      id: G.newId('w'),
      a: [round2(base[0] + u[0] * tMin), round2(base[1] + u[1] * tMin)],
      b: [round2(base[0] + u[0] * tMax), round2(base[1] + u[1] * tMax)],
      thickness_px: round2(thick), material, source: 'manual', confidence: null,
    };
    const ids = new Set(sel.map((w) => w.id));
    const at = this.walls.findIndex((w) => ids.has(w.id));
    this.change(() => {
      this.walls = this.walls.filter((w) => !ids.has(w.id));
      this.walls.splice(at, 0, merged);
    });
    this.selection = new Set([merged.id]);
    this.renderAll();
    this.ctx.toast(`${sel.length} Stücke zu einer Wand zusammengeführt (${G.fmtLength(len(merged), this.ppm)})`, 'ok');
  }

  joinCorner() {
    const sel = this.walls.filter((w) => this.selection.has(w.id));
    if (sel.length !== 2) {
      this.ctx.toast('Für „Ecke schließen“ genau zwei Wände auswählen', 'error');
      return;
    }
    const [A, B] = sel;
    const ua = G.unit(A.a, A.b);
    const ub = G.unit(B.a, B.b);
    if (Math.abs(G.cross(ua, ub)) < Math.sin((15 * Math.PI) / 180)) {
      this.ctx.toast('Die Wände laufen (fast) parallel – dafür „Zusammenführen“ nutzen.', 'error');
      return;
    }
    const P = G.lineIntersection(A.a, A.b, B.a, B.b);
    const plan = [];
    for (const [W, other] of [[A, B], [B, A]]) {
      const L = G.dist(W.a, W.b);
      const t = G.dot(G.sub(P, W.a), G.unit(W.a, W.b)) / L;
      if (t > 0.05 && t < 0.95) continue;  // Schnittpunkt liegt in dieser Wand: sie läuft durch (T-Stoß)
      const end = G.dist(W.a, P) <= G.dist(W.b, P) ? 'a' : 'b';
      const far = end === 'a' ? W.b : W.a;
      const dir = G.unit(far, P);
      // bis zur Außenkante der anderen Wand, damit die Ecke geschlossen aussieht
      const target = [P[0] + dir[0] * (other.thickness_px / 2), P[1] + dir[1] * (other.thickness_px / 2)];
      const shift = G.dist(W[end], target);
      const limit = Math.max(this.ppm ? 2 * this.ppm : 170, L);
      if (shift > limit) {
        this.ctx.toast(`Der Schnittpunkt liegt zu weit weg (${G.fmtLength(shift, this.ppm)}). Sind das die richtigen Wände?`, 'error');
        return;
      }
      plan.push([W, end, target]);
    }
    if (!plan.length) {
      this.ctx.toast('Die Wände kreuzen sich bereits.', 'error');
      return;
    }
    this.change(() => {
      for (const [W, end, target] of plan) {
        W[end] = [round2(target[0]), round2(target[1])];
        this.touch(W);
      }
    });
    this.ctx.toast(plan.length === 2 ? 'Ecke geschlossen' : 'Wand an die durchlaufende Wand angeschlossen', 'ok');
  }

  deleteSelection() {
    if (this.selDevice) {
      const id = this.selDevice;
      this.selDevice = null;
      this.change(() => { this.devices = this.devices.filter((d) => d.id !== id); });
      return;
    }
    if (!this.selection.size) return;
    const doomed = new Set(this.selection);
    this.selection.clear();
    this.change(() => { this.walls = this.walls.filter((w) => !doomed.has(w.id)); });
  }

  onKey(e) {
    if (isTyping(e)) {
      if (e.key === 'Enter' && e.target.id === 'scale-length') this.applyScale(e.target.value);
      return;
    }
    if (this.tool === 'area' && this.onAreaKey(e)) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); if (e.shiftKey) this.redo(); else this.undo(); return; }
    if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); this.redo(); return; }
    if ((e.ctrlKey || e.metaKey) && k === 'a') { e.preventDefault(); this.selection = new Set(this.walls.map((w) => w.id)); this.renderAll(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (k === 'v') this.setTool('select');
    else if (k === 'w') this.setTool('draw');
    else if (k === 'm') this.setTool('scale');
    else if (k === 'g') this.setTool('devices');
    else if (k === 't') this.setTool('split');
    else if (k === 'h') this.setTool('area');
    else if (k === 'r') this.setTool('rooms');
    else if (k === 'z') this.mergeSelected();
    else if (k === 'e') this.joinCorner();
    else if (k === 'f') this.vp.fit();
    else if (k === 'n') this.nextUncertain();
    else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); this.deleteSelection(); }
    else if (e.key === 'Escape') {
      if (this.placing) { this.placing = null; this.ctx.hint(HINTS.devices); this.renderPanel(); }
      else if (this.draft?.start) this.endDraw();
      else if (this.scaleDraft) { this.scaleDraft = null; this.renderAll(); }
      else if (this.selection.size) { this.selection.clear(); this.renderAll(); }
    }
  }

  // --- Räume (Entscheidung 0014) -------------------------------------------------------------

  async loadRooms() {
    if (!this.ppm) { this.roomsInfo = null; return; }
    await this.flush();
    try {
      this.roomsInfo = await api.rooms(this.floor.id);
    } catch (e) {
      this.roomsInfo = { error: e.message };
    }
    if (this.tool === 'rooms') this.renderAll();
  }

  roomColors() {
    const rooms = this.roomsInfo?.rooms;
    if (!rooms?.length) return [];
    if (!this.roomsInfo._colors) {
      const gap = this.ppm ? this.ppm * 1.4 : 60;
      this.roomsInfo._colors = G.assignRoomColors(rooms, gap, 6);
    }
    return this.roomsInfo._colors;
  }

  roomsDown(e, w) {
    const hit = (this.roomsInfo?.rooms || []).find((r) => G.inRoomContours(w, r.contours));
    this.selRoom = hit ? hit.id : null;
    this.renderRooms();
    this.renderPanel();
    const row = hit && document.querySelector(`#panel .room-row[data-room='${hit.id}']`);
    if (row) {
      row.scrollIntoView({ block: 'nearest' });
      if (e.pointerType !== 'touch' && window.innerWidth > 760) row.querySelector('input')?.focus();
    }
    return 'pan';
  }

  renderRooms() {
    const g = this.layer.rooms;
    const top = this.layer.roomsTop;
    g.replaceChildren();
    top.replaceChildren();
    if (this.tool !== 'rooms' || !this.roomsInfo?.rooms) return;
    const rooms = this.roomsInfo.rooms;
    const colors = this.roomColors();
    const px = (n) => this.vp.px(n);

    // Zuerst alle nicht gewählten Räume, danach den gewählten Raum samt Kontur-Rahmen obenauf
    const order = rooms.map((r, i) => ({ r, ci: colors[i] ?? (i % 6) }));
    for (const { r, ci } of order) {
      if (this.selRoom === r.id) continue;
      for (const pg of r.contours) {
        el('polygon', { points: G.pointsAttr(pg), class: `room-poly room-color-${ci}`, 'data-room': r.id }, g);
      }
    }
    for (const { r, ci } of order) {
      if (this.selRoom !== r.id) continue;
      for (const pg of r.contours) {
        el('polygon', { points: G.pointsAttr(pg), class: 'room-poly-casing' }, g);
        el('polygon', { points: G.pointsAttr(pg), class: `room-poly room-color-${ci} selected`, 'data-room': r.id }, g);
      }
    }

    // Sperrflächen durch Geräte und deren Beschriftung vormerken
    const boxes = [];
    const showDevLabels = this.opts.showDeviceLabels !== false && (this.vp.s >= 0.55 || this.tool === 'devices');
    for (const d of this.devices) {
      const dr = px(12);
      boxes.push({ x0: d.pos[0] - dr, y0: d.pos[1] - dr, x1: d.pos[0] + dr, y1: d.pos[1] + dr });
      if (showDevLabels || d.kind === 'ap') {
        const tw = d.label.length * px(6.8);
        boxes.push({ x0: d.pos[0] + px(11), y0: d.pos[1] - px(8), x1: d.pos[0] + px(15) + tw, y1: d.pos[1] + px(8) });
      }
    }

    // Raumnamen als Pillen überlappungs- und wandfrei platzieren (gewählter Raum hat Vorrang)
    const labelOrder = [...rooms].sort((a, b) => (b.id === this.selRoom) - (a.id === this.selRoom) || b.area_m2 - a.area_m2);
    let selLabel = null;
    for (const r of labelOrder) {
      const isSel = this.selRoom === r.id;
      const grp = el('g', { class: `room-label-group${isSel ? ' current' : ''}` }, top);
      const pill = el('rect', { class: 'room-label-pill', rx: px(5), ry: px(5) }, grp);
      const t = el('text', { x: 0, y: 0, class: 'room-label', 'font-size': px(12) }, grp);
      t.textContent = r.name;
      const tw = (typeof t.getComputedTextLength === 'function' ? t.getComputedTextLength() : 0) || r.name.length * px(7.2);
      const pw = tw + px(14);
      const ph = px(20);
      const [cx, cy] = G.placeRoomLabel(boxes, r, pw, ph, px, this.walls);
      pill.setAttribute('x', cx - pw / 2);
      pill.setAttribute('y', cy - ph / 2);
      pill.setAttribute('width', pw);
      pill.setAttribute('height', ph);
      t.setAttribute('x', cx);
      t.setAttribute('y', cy);
      if (isSel) selLabel = grp;
    }
    if (selLabel) top.appendChild(selLabel);
  }

  // Eigener Name für einen Raum: ein Namensschild an seinem Ankerpunkt; andere Schilder im selben Raum fallen weg
  async saveRoomName(room, name) {
    const labels = (this.floor.room_labels || []).filter((_, i) => !room.labels.includes(i));
    const n = name.trim();
    if (n) labels.push({ pos: room.anchor, name: n.slice(0, 40) });
    try {
      this.roomsInfo = await api.putRoomLabels(this.floor.id, labels);
      this.floor.room_labels = labels;
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
    this.renderAll();
  }

  renderRoomsPanel(p) {
    const s = section(p, 'Räume');
    if (!this.ppm) {
      div(s, 'callout', 'Für Räume braucht das Stockwerk einen Maßstab (Werkzeug „Maßstab“).');
      return;
    }
    const info = this.roomsInfo;
    if (!info) { div(s, 'small muted', 'Lade Räume …'); return; }
    if (info.error) { div(s, 'callout', info.error); return; }

    const hintBox = div(s, 'callout room-split-hint');
    div(hintBox, 'small', 'Zusammenhängende Räume trennen? Im Werkzeug „Wand zeichnen“ einfach eine Wand dazwischen einzeichnen '
      + `(Öffnungen bis ${G.fmt(info.door_m, 1)} m gelten als Tür).`);
    button(hintBox, 'Wand zeichnen (W)', () => this.setTool('draw'));

    if (!info.rooms.length) {
      div(s, 'small muted', 'Noch keine geschlossenen Räume erkannt. Zeichne Außen- und Innenwände oder starte die Erkennung.');
      return;
    }

    const colors = this.roomColors();
    const list = div(s, 'list');
    const selectRow = (id) => {
      if (this.selRoom === id) return;
      this.selRoom = id;
      this.renderRooms();
      for (const n of list.querySelectorAll('.room-row')) {
        n.classList.toggle('selected', Number(n.dataset.room) === id);
      }
    };
    const srcMeta = {
      user: ['eigener Name', 'ok'],
      ha: ['aus Home Assistant', 'ha'],
      auto: ['automatisch', ''],
    };

    for (let i = 0; i < info.rooms.length; i += 1) {
      const r = info.rooms[i];
      const ci = colors[i] ?? (i % 6);
      const [srcLabel, srcCls] = srcMeta[r.source] || ['automatisch', ''];
      const row = div(list, `room-row${this.selRoom === r.id ? ' selected' : ''}`);
      row.dataset.room = r.id;

      const head = div(row, 'room-row-head');
      div(head, `room-swatch room-color-${ci}`);
      div(head, 'room-row-title', r.name);
      div(head, 'room-area-badge', `${G.fmt(r.area_m2, 1)} m²`);
      div(head, `badge${srcCls ? ` ${srcCls}` : ''}`, srcLabel);

      const wrap = div(row, 'room-row-input-wrap');
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.maxLength = 40;
      inp.value = r.source === 'user' ? r.name : '';
      inp.placeholder = r.source === 'user' ? '' : `Eigenen Namen vergeben (${r.name})`;
      inp.setAttribute('aria-label', `Name für ${r.name}`);
      inp.addEventListener('focus', () => selectRow(r.id));
      inp.addEventListener('change', () => this.saveRoomName(r, inp.value));
      wrap.appendChild(inp);

      if (r.source === 'user') {
        const rst = button(wrap, '↺', () => this.saveRoomName(r, ''));
        rst.classList.add('room-reset-btn');
        rst.title = 'Eigenen Namen zurücksetzen';
        rst.setAttribute('aria-label', `Eigenen Namen für ${r.name} zurücksetzen`);
      }

      row.addEventListener('click', (ev) => {
        selectRow(r.id);
        if (ev.target !== inp && !ev.target.closest('button') && window.matchMedia?.('(pointer: fine)').matches) inp.focus();
      });
    }
    div(s, 'small muted', 'Namen kommen vorrangig von dir, sonst aus den Home-Assistant-Bereichen der Geräte.');
  }

  // --- Hausfläche ---------------------------------------------------------------------------

  async loadOutline() {
    if (!this.ppm) { this.outlineInfo = null; return; }
    await this.flush();
    try {
      this.outlineInfo = await api.outline(this.floor.id);
    } catch (e) {
      this.outlineInfo = { error: e.message };
    }
    if (this.tool === 'area') this.renderAll();
  }

  polyAreaM2(pg) {
    let a = 0;
    for (let i = 0; i < pg.length; i += 1) {
      const p = pg[i];
      const q = pg[(i + 1) % pg.length];
      a += p[0] * q[1] - q[0] * p[1];
    }
    return Math.abs(a) / 2 / (this.ppm * this.ppm);
  }

  areaSnap(e, w, prev) {
    if (e.altKey) return [round2(w[0]), round2(w[1])];
    const s = this.snapPoint(w, { from: prev, angle: e.shiftKey && !!prev });
    return [round2(s.pt[0]), round2(s.pt[1])];
  }

  areaDown(e, w) {
    const t = e.target;
    const dr = this.outlineDraft;
    if (dr) {
      if (dr.pts.length >= 3 && G.dist(w, dr.pts[0]) < this.vp.px(SNAP_PX)) {
        this.finishOutline();
        return true;
      }
      const p = this.areaSnap(e, w, dr.pts[dr.pts.length - 1]);
      if (!dr.pts.length || G.dist(p, dr.pts[dr.pts.length - 1]) > 1) dr.pts.push(p);
      dr.cur = p;
      this.renderArea();
      this.renderPanel();
      return true;
    }
    const ref = t.dataset?.pv || t.dataset?.pm;
    if (ref && this.outline) {
      const [pi, vi] = ref.split(':').map(Number);
      const pg = this.outline[pi];
      const before = this.snapshot();
      let v = vi;
      if (t.dataset.pm) {      // „+“ auf einer Kante: neue Ecke einfügen und gleich ziehen
        v = vi + 1;
        pg.splice(v, 0, G.mid(pg[vi], pg[(vi + 1) % pg.length]).map(round2));
      }
      this.selVertex = { pi, vi: v };
      this.selPoly = pi;
      this.drag = { kind: 'vertex', pi, vi: v, before, moved: !!t.dataset.pm };
      this.renderArea();
      return true;
    }
    if (t.dataset?.poly !== undefined) {
      this.selPoly = Number(t.dataset.poly);
      this.selVertex = null;
      this.renderAll();
      return 'pan';
    }
    if (this.selPoly !== null || this.selVertex) {
      this.selPoly = null;
      this.selVertex = null;
      this.renderAll();
    }
    return 'pan';
  }

  onAreaKey(e) {
    if (e.key === 'Enter' && this.outlineDraft) { this.finishOutline(); return true; }
    if (e.key === 'Escape' && this.outlineDraft) {
      this.outlineDraft = null;
      this.ctx.hint(HINTS.area);
      this.renderArea();
      return true;
    }
    if (e.key === 'Delete' || e.key === 'Backspace') {   // hier nie Wände löschen
      e.preventDefault();
      this.deleteAreaSelection();
      return true;
    }
    return false;
  }

  startOutline() {
    this.outlineDraft = { pts: [], cur: null };
    this.selPoly = null;
    this.selVertex = null;
    this.ctx.hint('Klick setzt eine Ecke. Klick auf die erste Ecke, Doppelklick oder Enter schließt den Umriss, Esc bricht ab. '
      + 'Ecken rasten an Wänden ein (Alt: frei), Umschalt hält 45°-Winkel.');
    this.renderAll();
  }

  finishOutline() {
    const pts = this.outlineDraft?.pts || [];
    this.outlineDraft = null;
    this.ctx.hint(HINTS.area);
    if (pts.length < 3) {
      if (pts.length) this.ctx.toast('Ein Umriss braucht mindestens drei Ecken.', 'error');
      this.renderAll();
      return;
    }
    this.change(() => { this.outline = [...(this.outline || []), pts]; });
    this.selPoly = this.outline.length - 1;
    this.renderAll();
  }

  adoptOutline(polys, what) {
    if (this.outline && !confirm(`Den eigenen Umriss durch ${what} ersetzen?`)) return;
    this.previewOthers = null;
    this.selPoly = null;
    this.selVertex = null;
    this.change(() => { this.outline = polys.map((pg) => pg.map((q) => [round2(q[0]), round2(q[1])])); });
  }

  resetOutline() {
    if (!confirm('Eigenen Umriss löschen? Die Hausfläche wird dann wieder automatisch bestimmt.')) return;
    this.selPoly = null;
    this.selVertex = null;
    this.change(() => { this.outline = null; });
  }

  deleteAreaSelection() {
    if (this.selVertex) {
      const { pi, vi } = this.selVertex;
      const pg = this.outline?.[pi];
      if (!pg) return;
      if (pg.length <= 3) {
        this.ctx.toast('Ein Umriss braucht mindestens drei Ecken. Ganze Fläche löschen: Fläche anklicken, dann Entf.', 'error');
        return;
      }
      this.selVertex = null;
      this.change(() => { pg.splice(vi, 1); });
      return;
    }
    if (this.selPoly !== null && this.outline?.[this.selPoly]) {
      const pi = this.selPoly;
      this.selPoly = null;
      this.change(() => {
        this.outline.splice(pi, 1);
        if (!this.outline.length) this.outline = null;   // keine Fläche mehr: wieder automatisch
      });
    }
  }

  areaStatsText() {
    const m2 = (v) => (v === null || v === undefined ? '–' : `${G.fmt(v, 1)} m²`);
    const gross = (this.outline || []).reduce((a, pg) => a + this.polyAreaM2(pg), 0);
    const saved = JSON.stringify(this.outline) === this.savedOutline;
    return `Innerhalb der Umrisse ${m2(gross)}, gezählt ohne Wände ${saved ? m2(this.outlineInfo?.area_m2) : '…'}`;
  }

  updateAreaStats() {
    const n = document.getElementById('area-stats');
    if (n) n.textContent = this.areaStatsText();
  }

  renderArea() {
    const g = this.layer.area;
    const top = this.layer.areaTop;
    g.replaceChildren();
    top.replaceChildren();
    if (this.tool !== 'area') return;
    const px = (n) => this.vp.px(n);
    // Messpunkte und Fundorte: Dort war jemand, die Stelle gehört meist zum Haus
    for (const q of [...(this.floor.survey || []), ...(this.floor.found || [])]) {
      el('circle', { cx: q.pos[0], cy: q.pos[1], r: px(4), class: 'area-point' }, top);
    }
    for (const pg of this.previewOthers || []) el('polygon', { points: G.pointsAttr(pg), class: 'area-preview' }, top);
    if (!this.outline) {
      for (const pg of this.outlineInfo?.auto?.polygons || []) el('polygon', { points: G.pointsAttr(pg), class: 'area-auto' }, g);
    } else {
      this.outline.forEach((pg, pi) => {
        el('polygon', { points: G.pointsAttr(pg), class: `area-poly${this.selPoly === pi ? ' selected' : ''}`, 'data-poly': pi }, g);
      });
      const midR = px(isCoarse() ? 8 : 4.5);
      const vtxR = px(isCoarse() ? 10 : 6);
      this.outline.forEach((pg, pi) => {
        pg.forEach((q, vi) => {
          const n = pg[(vi + 1) % pg.length];
          if (G.dist(q, n) < px(30)) return;
          const m = G.mid(q, n);
          el('circle', { cx: m[0], cy: m[1], r: midR, class: 'area-mid', 'data-pm': `${pi}:${vi}` }, top);
        });
        pg.forEach((q, vi) => {
          const sel = this.selVertex?.pi === pi && this.selVertex?.vi === vi;
          el('circle', { cx: q[0], cy: q[1], r: vtxR, class: `handle area-vertex${sel ? ' selected' : ''}`, 'data-pv': `${pi}:${vi}` }, top);
        });
      });
    }
    const dr = this.outlineDraft;
    if (dr && dr.pts.length) {
      el('polyline', { points: G.pointsAttr(dr.cur ? [...dr.pts, dr.cur] : dr.pts), class: 'draft-line' }, top);
      dr.pts.forEach((q, i) => el('circle', { cx: q[0], cy: q[1], r: px(i === 0 ? 7 : 4), class: 'snap-mark' }, top));
    }
  }

  renderAreaPanel(p) {
    const s = section(p, 'Hausfläche');
    s.id = 'area-panel';
    if (!this.ppm) {
      div(s, 'callout', 'Für die Hausfläche braucht das Stockwerk einen Maßstab (Werkzeug „Maßstab“).');
      return;
    }
    const info = this.outlineInfo;
    if (!info) { div(s, 'small muted', 'Lade Hausfläche …'); return; }
    if (info.error) { div(s, 'callout', info.error); return; }
    if (this.outlineDraft) {
      const box = div(s, 'callout');
      div(box, 'small', 'Ecken auf den Plan tippen. Ab 3 Ecken lässt sich der Umriss schließen.');
      const act = div(box, 'row');
      act.style.marginTop = '6px';
      const fin = button(act, TEXTS.finishArea, () => this.finishOutline());
      fin.classList.add('primary');
      fin.disabled = this.outlineDraft.pts.length < 3;
      button(act, TEXTS.cancel, () => { this.outlineDraft = null; this.ctx.hint(HINTS.area); this.renderAll(); });
    }
    const m2 = (v) => (v === null || v === undefined ? '–' : `${G.fmt(v, 1)} m²`);
    if (this.outline) {
      const n = this.outline.length;
      div(s, '', `Eigener Umriss (${n === 1 ? 'eine Fläche' : `${n} Flächen`})`);
      div(s, 'small', this.areaStatsText()).id = 'area-stats';
      div(s, 'small muted', `Automatisch wären es ${m2(info.auto?.area_m2)}.`);
      const row = div(s, 'row');
      button(row, 'Weitere Fläche zeichnen', () => this.startOutline());
      if (this.selVertex) button(row, TEXTS.deleteVertex, () => this.deleteAreaSelection()).classList.add('danger');
      else if (this.selPoly !== null) button(row, 'Fläche löschen', () => this.deleteAreaSelection()).classList.add('danger');
      button(s, 'Zurück zur automatischen Hausfläche', () => this.resetOutline());
    } else {
      div(s, '', `Automatisch: ${m2(info.area_m2)}`);
      const src = { walls: 'Aus den Außenwänden bestimmt (grau gestrichelt).',
        hull: 'Geschätzt: Die Außenwände fehlen, der Vorschlag ist die Hülle um Wände und Messpunkte (grau gestrichelt).' }[info.auto?.source];
      if (src) div(s, 'small muted', src);
      const row = div(s, 'row');
      if (info.auto?.polygons?.length) {
        button(row, 'Vorschlag übernehmen', () => this.adoptOutline(info.auto.polygons, 'den Vorschlag')).classList.add('primary');
      }
      button(row, 'Neu zeichnen', () => this.startOutline());
    }
    for (const o of info.others || []) {
      const b = button(s, `Umriss von „${o.name}“ übernehmen`, () => this.adoptOutline(o.polygons, `den Umriss von „${o.name}“`));
      b.title = o.user ? 'Umriss, den der Anwender dort gezeichnet hat' : 'automatischer Vorschlag dieses Stockwerks';
      b.addEventListener('mouseenter', () => { this.previewOthers = o.polygons; this.renderArea(); });
      b.addEventListener('mouseleave', () => { this.previewOthers = null; this.renderArea(); });
    }
    div(s, 'small muted', 'Gezählt wird die Fläche innerhalb der Umrisse ohne Wände; sie geht in Abdeckung und Suche ein. '
      + 'Grüne Punkte: Messpunkte und Fundorte.');
  }

  // --- Darstellung ------------------------------------------------------------------------

  onViewChange() {
    this.ctx.status(undefined, `Zoom ${G.fmt(this.vp.s * 100, 0)} %`,
      this.ppm ? `Maßstab 1 m = ${G.fmt(this.ppm, 1)} px` : 'kein Maßstab');
    this.renderOverlays();
  }

  renderAll(panel = true) {
    this.renderWalls();
    this.renderOverlays();
    if (panel) this.renderPanel();
  }

  renderWalls() {
    const { walls, warn } = this.layer;
    walls.replaceChildren();
    warn.replaceChildren();
    for (const w of this.walls) {
      el('line', {
        x1: w.a[0], y1: w.a[1], x2: w.b[0], y2: w.b[1], class: 'wall', 'data-id': w.id,
        stroke: this.matColor[w.material] || 'var(--wall-fallback)', 'stroke-width': w.thickness_px, 'stroke-opacity': this.opts.wallOpacity,
      }, walls);
      if (this.opts.showUncertain && this.isUncertain(w)) {
        el('polygon', { points: G.pointsAttr(G.wallCorners(w)), class: 'warn-outline' }, warn);
      }
    }
    if (this.highlightShort) {
      for (const w of this.shortWalls()) {
        const c = G.wallCorners(w);
        const m = G.mid(w.a, w.b);
        const r = Math.max(this.vp.px(9), w.thickness_px);
        el('circle', { cx: m[0], cy: m[1], r, class: 'short-mark' }, warn);
        el('polygon', { points: G.pointsAttr(c), class: 'short-mark' }, warn);
      }
    }
  }

  renderOverlays() {
    const { hits, sel } = this.layer;
    hits.replaceChildren();
    sel.replaceChildren();
    const minHit = this.vp.px(14);
    for (const w of this.walls) {
      el('line', { x1: w.a[0], y1: w.a[1], x2: w.b[0], y2: w.b[1], class: 'hit', 'data-id': w.id, 'stroke-width': Math.max(w.thickness_px, minHit) }, hits);
    }
    const r = this.vp.px(isCoarse() ? 11 : 7);
    const showHandles = this.tool === 'select' && this.selection.size === 1;
    for (const w of this.walls) {
      if (!this.selection.has(w.id)) continue;
      el('polygon', { points: G.pointsAttr(G.wallCorners(w)), class: 'sel-outline' }, sel);
      if (showHandles) {
        el('circle', { cx: w.a[0], cy: w.a[1], r, class: 'handle', 'data-id': w.id, 'data-end': 'a' }, sel);
        el('circle', { cx: w.b[0], cy: w.b[1], r, class: 'handle', 'data-id': w.id, 'data-end': 'b' }, sel);
      }
    }
    if (this.drag?.kind === 'end' && this.drag.snap && this.drag.snap.kind !== 'free') {
      const p = this.drag.snap.pt;
      el('circle', { cx: p[0], cy: p[1], r: this.vp.px(9), class: 'snap-mark' }, sel);
    }
    this.renderScale();
    this.renderDevices();
    this.renderDraft();
    this.renderArea();
    this.renderRooms();
  }

  renderDevices() {
    const g = this.layer.devices;
    g.replaceChildren();
    const px = (n) => this.vp.px(n);
    const showLabels = this.opts.showDeviceLabels !== false && (this.vp.s >= 0.55 || this.tool === 'devices');
    for (const d of this.devices) {
      const sel = d.id === this.selDevice;
      const grp = el('g', { class: `device kind-${d.kind}`, 'data-dev': d.id, transform: `translate(${d.pos[0]} ${d.pos[1]})` }, g);
      if (sel) el('circle', { r: px(15), class: 'device-ring' }, grp);
      if (d.kind === 'ap') {
        el('circle', { r: px(10), class: 'device-shape' }, grp);
        el('circle', { r: px(3.5), fill: 'var(--handle-fill)' }, grp);
      } else if (d.kind === 'shelly') {
        el('rect', { x: -px(7), y: -px(7), width: px(14), height: px(14), rx: px(3), class: 'device-shape' }, grp);
      } else {
        el('polygon', { points: `0,${-px(8)} ${px(8)},0 0,${px(8)} ${-px(8)},0`, class: 'device-shape' }, grp);
      }
      if (showLabels || sel || (this.opts.showDeviceLabels !== false && d.kind === 'ap')) {
        const attrs = { x: px(13), y: px(4), class: 'device-label', 'font-size': px(12) };
        if (this.tool !== 'devices' && !sel) attrs.opacity = 0.78;
        const t = el('text', attrs, grp);
        t.textContent = d.label;
      }
    }
  }

  async loadCatalog() {
    try {
      this.catalog = await api.catalog();
    } catch (e) {
      this.catalog = { measured_at: null, devices: [] };
      this.ctx.toast(`Geräteliste nicht verfügbar: ${e.message}`, 'error');
    }
    if (this.tool === 'devices') this.renderPanel();
  }

  placedElsewhere() {
    const map = new Map();
    for (const f of this.ctx.project.floors) {
      if (f.id === this.floor.id) continue;
      for (const d of f.devices || []) map.set(d.key, f.name);
    }
    return map;
  }

  // Eigene Geräte ohne Messlauf (Planung): Router, Repeater, Zugangspunkt per LAN, sonstiges Gerät
  renderManualPanel(p) {
    const s = section(p, 'Eigene Geräte');
    const types = [
      ['Router', 'ap', 'master', null, 'Router mit Internetanschluss'],
      ['Repeater', 'ap', 'slave', 'WLAN', 'per WLAN angebunden'],
      ['Zugangspunkt', 'ap', 'slave', 'LAN', 'per Netzwerkkabel angebunden'],
      ['Gerät', 'other', null, null, 'z. B. Fernseher, Kamera, Steckdose'],
    ];
    const row = div(s, 'row');
    for (const [label, kind, role, uplink, title] of types) {
      const b = button(row, `+ ${label}`, () => {
        const all = this.ctx.project.floors.filter((f) => f.id !== this.floor.id).flatMap((f) => f.devices || []).concat(this.devices);
        const n = all.filter((d) => d.key.startsWith('manual:') && d.label.startsWith(label)).length;
        this.placing = { key: G.newId('manual').replace('manual_', 'manual:'), kind, role, uplink, label: n ? `${label} ${n + 1}` : label };
        this.ctx.hint(`Klick auf den Plan setzt „${this.placing.label}“. Esc bricht ab.`);
        this.renderPanel();
      });
      b.title = title;
    }
    div(s, 'small muted', 'Für die Planung ohne Messlauf, z. B. Router und Repeater, die es noch nicht gibt, oder Geräte, die keine Messwerte liefern. '
      + 'Name und Art lassen sich nach dem Platzieren ändern.');
  }

  renderDevicesPanel(p) {
    const s = section(p, 'Geräte platzieren');
    if (!this.catalog) { div(s, 'small muted', 'Lade Geräteliste …'); return; }
    const cat = this.catalog;
    if (this.placing) {
      const box = div(s, 'callout row');
      div(box, 'small', `Klick auf den Plan setzt „${this.placing.label}“.`).style.flex = '1';
      button(box, TEXTS.cancel, () => { this.placing = null; this.ctx.hint(HINTS.devices); this.renderPanel(); });
    }
    if (!cat.devices.length) {
      div(s, 'small muted', 'Noch kein Messlauf: Die Geräteliste aus FRITZ!Box und Shellys ist leer. Eigene Geräte lassen sich trotzdem platzieren.');
      this.renderManualPanel(p);
      return;
    }
    const when = cat.measured_at ? new Date(cat.measured_at).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : '?';
    const elsewhere = this.placedElsewhere();
    const here = new Map(this.devices.map((d) => [d.key, d]));
    div(s, 'small muted', `Geräte aus dem Messlauf vom ${when}. ${here.size} hier, ${elsewhere.size} auf anderen Stockwerken platziert.`);
    const q = document.createElement('input');
    q.type = 'text';
    q.placeholder = 'Suchen (Name, Raum, Modell) …';
    q.value = this.devQuery;
    s.appendChild(q);
    const kinds = div(s, 'row');
    for (const [k, label] of [['all', 'Alle'], ['ap', 'Zugangspunkte'], ['shelly', 'Shellys'], ['client', 'Sonstige']]) {
      const b = button(kinds, label, () => { this.devKind = k; this.renderPanel(); });
      if (this.devKind === k) b.classList.add('active');
    }
    const list = div(s, 'list device-list');
    const fill = () => {
      list.replaceChildren();
      const needle = this.devQuery.trim().toLowerCase();
      const items = cat.devices.filter((d) => (this.devKind === 'all' || d.kind === this.devKind)
        && (!needle || `${d.label} ${d.area} ${d.detail}`.toLowerCase().includes(needle)));
      if (!items.length) div(list, 'small muted', 'Keine Treffer.');
      for (const d of items) {
        const item = div(list, `device-item${this.placing?.key === d.key ? ' selected' : ''}`);
        const head = div(item, 'row');
        div(head, `device-dot kind-${d.kind}`);
        const title = div(head, 'title', d.label);
        title.style.flex = '1';
        if (here.has(d.key)) div(head, 'badge ok', 'hier');
        else if (elsewhere.has(d.key)) div(head, 'badge', elsewhere.get(d.key));
        div(item, 'small muted', [d.area, d.detail].filter(Boolean).join(' · '));
        item.addEventListener('click', () => {
          if (here.has(d.key)) {
            const dev = here.get(d.key);
            this.selDevice = dev.id;
            this.vp.centerOn(dev.pos, Math.max(this.vp.s, 1));
            this.renderAll();
          } else if (elsewhere.has(d.key)) {
            this.ctx.toast(`„${d.label}“ ist schon im Stockwerk „${elsewhere.get(d.key)}“ platziert. Dort entfernen, um es hier zu setzen.`, 'error');
          } else {
            this.placing = d;
            this.ctx.hint(`Klick auf den Plan setzt „${d.label}“${d.area ? ` (${d.area})` : ''}. Esc bricht ab.`);
            this.renderPanel();
          }
        });
      }
    };
    q.addEventListener('input', () => { this.devQuery = q.value; fill(); });
    fill();
    this.renderManualPanel(p);
  }

  renderDevicePanel(p) {
    const d = this.devices.find((x) => x.id === this.selDevice);
    if (!d) return;
    const s = section(p, 'Ausgewähltes Gerät');
    s.id = 'dev-panel';
    if (d.key.startsWith('manual:')) {
      this.renderManualDevice(s, d);
      return;
    }
    div(s, 'title', d.label);
    const info = this.catalog?.devices.find((c) => c.key === d.key);
    if (info) div(s, 'small muted', [info.area, info.detail].filter(Boolean).join(' · '));
    div(s, 'small', this.ppm ? `Position x ${G.fmt(d.pos[0] / this.ppm, 2)} m, y ${G.fmt(d.pos[1] / this.ppm, 2)} m` : 'Position ohne Maßstab');
    const del = button(s, 'Entfernen', () => this.deleteSelection());
    del.classList.add('danger');
  }

  renderManualDevice(s, d) {
    const name = field(s, 'Name', 'text', d.label);
    name.id = 'device-name';
    name.addEventListener('change', () => {
      const v = name.value.trim();
      if (v && v !== d.label) this.change(() => { d.label = v.slice(0, 80); });
    });
    const kindLabel = document.createElement('label');
    kindLabel.textContent = 'Art';
    const kind = document.createElement('select');
    kind.id = 'device-kind';
    const kinds = [['master', 'Router mit Internetanschluss'], ['WLAN', 'Repeater (per WLAN)'], ['LAN', 'Zugangspunkt (per LAN)'], ['other', 'Gerät']];
    const cur = d.kind !== 'ap' ? 'other' : d.role === 'master' ? 'master' : d.uplink || 'WLAN';
    for (const [v, t] of kinds) kind.appendChild(new Option(t, v, false, v === cur));
    kind.addEventListener('change', () => this.change(() => {
      const v = kind.value;
      Object.assign(d, v === 'other' ? { kind: 'other', role: null, uplink: null }
        : v === 'master' ? { kind: 'ap', role: 'master', uplink: null } : { kind: 'ap', role: 'slave', uplink: v });
    }));
    kindLabel.appendChild(kind);
    s.appendChild(kindLabel);
    div(s, 'small', this.ppm ? `Position x ${G.fmt(d.pos[0] / this.ppm, 2)} m, y ${G.fmt(d.pos[1] / this.ppm, 2)} m` : 'Position ohne Maßstab');
    div(s, 'small muted', 'Eigenes Gerät ohne Messwerte. Die Auswertung rechnet für Zugangspunkte mit Startwerten, bis Messpunkte vom Handy sie eichen.');
    if (d.kind === 'ap') {
      const n = d.bssids?.length || 0;
      div(s, 'small', n ? `${n} ${n === 1 ? 'Netz' : 'Netze'} zugeordnet (Ansicht „Messen“).`
        : 'Noch kein Netz zugeordnet: in der Ansicht „Messen“ mit der Android-App die Netze dieses Geräts auswählen.');
    }
    button(s, 'Entfernen', () => this.deleteSelection()).classList.add('danger');
  }

  renderScale() {
    const g = this.layer.scale;
    g.replaceChildren();
    const s = this.floor.scale;
    if (!s || this.scaleDraft) return;
    drawMeasure(g, s.a, s.b, `${G.fmt(s.length_m, 2)} m`, this.vp);
  }

  renderDraft() {
    const g = this.layer.draft;
    g.replaceChildren();
    if (this.tool === 'draw' && this.draft) {
      const { start, cur, snap } = this.draft;
      if (start && cur) {
        el('line', { x1: start[0], y1: start[1], x2: cur[0], y2: cur[1], class: 'draft', 'stroke-width': this.newThicknessPx() }, g);
      }
      if (cur && snap && snap !== 'free' && snap !== 'angle') {
        el('circle', { cx: cur[0], cy: cur[1], r: this.vp.px(9), class: 'snap-mark' }, g);
      } else if (cur && !start) {
        el('circle', { cx: cur[0], cy: cur[1], r: this.vp.px(3), class: 'snap-mark' }, g);
      }
    }
    if (this.tool === 'scale' && this.scaleDraft) {
      const { a } = this.scaleDraft;
      const b = this.scaleDraft.b || this.scaleDraft.cur;
      if (a && b) {
        const len = G.dist(a, b);
        drawMeasure(g, a, b, `${G.fmt(len, 0)} px`, this.vp);
      }
    }
    if (this.drag?.kind === 'box') {
      const r = this.drag.rect;
      el('rect', { x: r.x, y: r.y, width: r.w, height: r.h, class: 'box-select' }, g);
    }
    if (this.tool === 'split' && this.splitPreview) {
      const { wall, pt } = this.splitPreview;
      const u = G.unit(wall.a, wall.b);
      const h = wall.thickness_px / 2 + this.vp.px(6);
      el('line', { x1: pt[0] - u[1] * h, y1: pt[1] + u[0] * h, x2: pt[0] + u[1] * h, y2: pt[1] - u[0] * h, class: 'split-mark' }, g);
    }
  }

  renderPanel() {
    const { ctx, floor } = this;
    const p = ctx.panel;
    const scrollTop = p.scrollTop;
    p.replaceChildren();

    const tools = section(p, 'Werkzeug');
    const tb = div(tools, 'toolbar');
    for (const [tool, label, key] of [['select', 'Auswählen', 'V'], ['draw', 'Wand zeichnen', 'W'], ['split', 'Teilen', 'T'],
      ['scale', 'Maßstab', 'M'], ['devices', 'Geräte', 'G'], ['area', 'Hausfläche', 'H'], ['rooms', 'Räume', 'R']]) {
      const b = button(tb, '', () => this.setTool(tool));
      b.innerHTML = `<span class="tool-top">${TOOL_ICONS[tool]}<span class="key">${key}</span></span><span>${label}</span>`;
      if (this.tool === tool) b.classList.add('active');
    }
    const f = button(tb, '', () => this.vp.fit());
    f.innerHTML = `<span class="tool-top">${TOOL_ICONS.fit}<span class="key">F</span></span><span>Ganzes Bild</span>`;
    const tb2 = div(tools, 'toolbar two');
    const u = button(tb2, 'Rückgängig', () => this.undo());
    u.insertAdjacentHTML('beforeend', '<span class="key">Strg+Z</span>');
    u.disabled = !this.undoStack.length;
    const r = button(tb2, 'Wiederholen', () => this.redo());
    r.insertAdjacentHTML('beforeend', '<span class="key">Strg+Y</span>');
    r.disabled = !this.redoStack.length;

    // Maßstab (ausführlich nur wenn noch offen, im Entwurf oder Werkzeug Maßstab aktiv)
    if (!this.ppm || this.scaleDraft?.b || this.tool === 'scale') {
      const sc = section(p, 'Maßstab');
      if (this.scaleDraft?.b) {
        const len = G.dist(this.scaleDraft.a, this.scaleDraft.b);
        div(sc, 'small', `Strecke: ${G.fmt(len, 0)} px. Wie lang ist sie in Wirklichkeit?`);
        const inp = field(sc, 'Länge in Metern', 'text', this.floor.scale ? G.fmt(this.floor.scale.length_m, 2) : '');
        inp.id = 'scale-length';
        inp.inputMode = 'decimal';
        inp.placeholder = 'z. B. 7,76';
        const row = div(sc, 'row');
        const ok = button(row, 'Übernehmen', () => this.applyScale(inp.value));
        ok.classList.add('primary');
        button(row, 'Abbrechen', () => { this.scaleDraft = null; this.renderAll(); });
      } else if (this.ppm) {
        const s = this.floor.scale;
        div(sc, '', `1 m = ${G.fmt(s.px_per_m, 1)} px`);
        div(sc, 'small muted', `gemessen an ${G.fmt(s.length_m, 2)} m. Zwei Punkte im Plan anklicken, um neu zu eichen.`);
      } else {
        div(sc, 'callout', 'Noch kein Maßstab. Werkzeug „Maßstab“ wählen, zwei Punkte einer bekannten Bemaßung anklicken und die Länge eingeben. Danach werden Längen und Dicken in Metern bzw. Zentimetern angezeigt.');
      }
    }

    // Auswahl oder Vorgaben für das aktive Werkzeug (auf dem Handy ohne Scrollen erreichbar)
    const selected = this.walls.filter((w) => this.selection.has(w.id));
    if (this.selDevice) this.renderDevicePanel(p);
    if (this.tool === 'area') this.renderAreaPanel(p);
    else if (this.tool === 'rooms') this.renderRoomsPanel(p);
    else if (this.tool === 'devices') this.renderDevicesPanel(p);
    else if (selected.length) this.renderSelectionPanel(p, selected);
    else this.renderNewWallPanel(p);

    // Erkennung und Prüfung
    const det = section(p, 'Automatische Erkennung');
    const styleLabel = document.createElement('label');
    styleLabel.textContent = 'Wände im Plan';
    const style = document.createElement('select');
    style.id = 'wall-style';
    for (const [v, t] of [['auto', 'automatisch erkennen'], ['filled', 'schraffiert oder gefüllt'], ['outline', 'nur als Umrisslinien']]) {
      style.appendChild(new Option(t, v, false, v === (this.opts.wallStyle || 'auto')));
    }
    style.addEventListener('change', () => { this.opts.wallStyle = style.value; this.saveOpts(); });
    styleLabel.appendChild(style);
    det.appendChild(styleLabel);
    const d = button(det, 'Wände erkennen', () => this.runDetection());
    d.classList.add('primary');
    div(det, 'small muted', 'Ersetzt nur unveränderte automatisch erkannte Wände. Gezeichnete und bearbeitete Wände bleiben.'
      + (this.ppm ? ' Dicken werden auf übliche Mauermaße gerundet.' : ' Tipp: vorher den Maßstab setzen, dann werden die Dicken auf Mauermaße gerundet.'));
    if (this.ppm && this.walls.length) {
      button(det, 'Alle Dicken auf Normmaß runden', () => this.snapThickness(this.walls));
    }
    const unsure = this.walls.filter((w) => this.isUncertain(w)).length;
    const chk = section(p, 'Prüfen');
    div(chk, 'small', unsure ? `${unsure} unsichere Wände (orange gestrichelt)` : 'Keine unsicheren Wände.');
    if (unsure) {
      const nb = button(chk, 'Nächste unsichere zeigen', () => this.nextUncertain());
      nb.insertAdjacentHTML('beforeend', ' <span class="key">N</span>');
    }
    const showU = checkbox(chk, 'Unsichere Wände markieren', this.opts.showUncertain, (v) => {
      this.opts.showUncertain = v; this.saveOpts(); this.renderWalls();
    });
    showU.title = 'Automatisch erkannte Wände, die ihr Rechteck nur zum Teil füllen';

    const view = section(p, 'Darstellung');
    slider(view, 'Grundriss', this.opts.imageOpacity, (v) => {
      this.opts.imageOpacity = v; this.saveOpts(); this.imageEl.setAttribute('opacity', v);
    });
    slider(view, 'Wände', this.opts.wallOpacity, (v) => {
      this.opts.wallOpacity = v; this.saveOpts();
      for (const n of this.layer.walls.children) n.setAttribute('stroke-opacity', v);
    });
    checkbox(view, 'Geräte-Namen im Plan', this.opts.showDeviceLabels !== false, (v) => {
      this.opts.showDeviceLabels = v; this.saveOpts(); this.renderDevices();
    });

    const head = section(p, 'Stockwerk');
    const nameRow = div(head, 'grid2');
    const name = field(nameRow, 'Name', 'text', floor.name);
    const level = field(nameRow, 'Ebene', 'number', floor.level);
    const saveMeta = async () => {
      const body = { name: name.value.trim() || floor.name, level: Math.round(G.parseNumber(level.value) || 0) };
      try {
        const f2 = await api.updateFloor(floor.id, body);
        Object.assign(floor, { name: f2.name, level: f2.level });
        await ctx.refreshProject();
      } catch (e) { ctx.toast(e.message, 'error'); }
    };
    name.addEventListener('change', saveMeta);
    level.addEventListener('change', saveMeta);
    const autoCount = this.walls.filter((w) => w.source === 'auto').length;
    const scaleNote = this.ppm ? ` · 1 m = ${G.fmt(this.ppm, 1)} px` : '';
    div(head, 'small muted', `${this.walls.length} Wände · ${autoCount} automatisch · ${this.walls.length - autoCount} bearbeitet${scaleNote}`);

    const help = document.createElement('details');
    help.className = 'more';
    help.innerHTML = '<summary>Tasten &amp; Kürzel</summary>';
    div(help, 'small muted', 'V Auswählen · W Zeichnen · T Teilen · M Maßstab · G Geräte · H Hausfläche · R Räume · F Ganzes Bild · Z Zusammenführen · E Ecke schließen · N nächste unsichere Wand · Entf Löschen · Esc Abbrechen · Strg+A alles · Strg+Z/Y Rückgängig/Wiederholen · Mausrad Zoom · Leertaste/mittlere Taste + Ziehen verschiebt');
    p.appendChild(help);
    p.scrollTop = scrollTop;
  }

  renderSelectionPanel(p, sel) {
    const s = section(p, sel.length === 1 ? 'Ausgewählte Wand' : `${sel.length} Wände ausgewählt`);
    s.id = 'sel-panel';
    const unit = this.ppm ? 'cm' : 'px';
    const toUnit = (px) => (this.ppm ? (px / this.ppm) * 100 : px);
    const fromUnit = (v) => (this.ppm ? (v / 100) * this.ppm : v);
    if (sel.length === 1) {
      const w = sel[0];
      const kv = document.createElement('dl');
      kv.className = 'kv';
      const add = (k, v) => { const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = v; kv.append(dt, dd); };
      add('Länge', G.fmtLength(G.dist(w.a, w.b), this.ppm));
      add('Quelle', w.source === 'auto' ? 'automatisch erkannt' : 'gezeichnet/korrigiert');
      if (w.source === 'auto' && w.confidence !== null) add('Sicherheit', `${G.fmt(w.confidence * 100, 0)} %`);
      s.appendChild(kv);
    }
    const same = (fn) => (sel.every((w) => fn(w) === fn(sel[0])) ? fn(sel[0]) : null);
    const grid = div(s, 'grid2');
    const th = same((w) => w.thickness_px);
    const thick = field(grid, `Dicke (${unit})`, 'text', th === null ? '' : G.fmt(toUnit(th), this.ppm ? 1 : 1));
    thick.inputMode = 'decimal';
    thick.placeholder = th === null ? 'gemischt' : '';
    thick.addEventListener('change', () => {
      const v = G.parseNumber(thick.value);
      if (!(v > 0)) return;
      this.change(() => { for (const w of sel) { w.thickness_px = round2(fromUnit(v)); this.touch(w); } });
    });
    const matLabel = document.createElement('label');
    matLabel.textContent = 'Material';
    const mat = document.createElement('select');
    const m0 = same((w) => w.material);
    if (m0 === null) mat.appendChild(new Option('gemischt', '', true, true));
    for (const m of this.ctx.materials) mat.appendChild(new Option(m.name, m.id, false, m.id === m0));
    mat.addEventListener('change', () => {
      if (!mat.value) return;
      this.change(() => { for (const w of sel) { w.material = mat.value; this.touch(w); } });
    });
    matLabel.appendChild(mat);
    grid.appendChild(matLabel);
    if (this.ppm) {
      const classes = div(s, 'row');
      for (const c of this.ctx.classes) {
        button(classes, `${G.fmt(c, 1)}`, () => this.change(() => { for (const w of sel) { w.thickness_px = round2((c / 100) * this.ppm); this.touch(w); } }));
      }
      div(s, 'small muted', 'Schnellwahl Dicke in cm');
    }
    const ops = div(s, 'row');
    const multi = button(ops, TEXTS.addWallMode, () => { this.multiSelect = !this.multiSelect; this.renderPanel(); });
    if (this.multiSelect) multi.classList.add('active');
    if (sel.length >= 2) {
      const m = button(ops, 'Zusammenführen', () => this.mergeSelected());
      m.title = 'Stücke auf einer Linie zu einer Wand verbinden (Taste Z)';
      m.insertAdjacentHTML('beforeend', ' <span class="key">Z</span>');
    }
    if (sel.length === 2) {
      const c = button(ops, 'Ecke schließen', () => this.joinCorner());
      c.title = 'Beide Wände bis zum Schnittpunkt verlängern oder kürzen (Taste E)';
      c.insertAdjacentHTML('beforeend', ' <span class="key">E</span>');
    }
    const row = div(s, 'row');
    if (sel.some((w) => w.source === 'auto')) {
      button(row, 'Als geprüft markieren', () => this.change(() => { for (const w of sel) this.touch(w); }));
    }
    button(row, TEXTS.clearSel, () => { this.selection.clear(); this.multiSelect = false; this.renderAll(); });
    const del = button(row, 'Löschen', () => this.deleteSelection());
    del.classList.add('danger');
  }

  async selectExterior() {
    await this.flush();
    try {
      const res = await api.exterior(this.floor.id);
      this.selection = new Set(res.ids);
      this.setTool('select', false);
      this.renderAll();
      this.ctx.toast(`${res.ids.length} Außenwände ausgewählt – Material oder Dicke jetzt für alle setzen`, 'ok');
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
  }

  shortThreshold() {
    return this.ppm ? (this.opts.shortCm / 100) * this.ppm : this.opts.shortPx;
  }

  shortWalls() {
    const limit = this.shortThreshold();
    return this.walls.filter((w) => G.dist(w.a, w.b) < limit);
  }

  renderCleanupPanel(p) {
    const s = section(p, 'Aufräumen');
    const unit = this.ppm ? 'cm' : 'px';
    const row = div(s, 'grid2');
    const inp = field(row, `Kürzer als (${unit})`, 'text', G.fmt(this.ppm ? this.opts.shortCm : this.opts.shortPx, 0));
    inp.inputMode = 'decimal';
    const btn = button(row, '', () => {
      const doomed = new Set(this.shortWalls().map((w) => w.id));
      if (!doomed.size) return;
      this.shortPinned = false;
      this.highlightShort = false;
      this.change(() => { this.walls = this.walls.filter((w) => !doomed.has(w.id)); });
      this.ctx.toast(`${doomed.size} kurze Stücke gelöscht (Strg+Z macht es rückgängig)`, 'ok');
    });
    btn.style.alignSelf = 'end';
    const act = div(s, 'row');
    const peek = button(act, TEXTS.showInPlan, () => {
      this.shortPinned = !this.shortPinned;
      this.highlightShort = this.shortPinned;
      this.renderWalls();
      this.renderPanel();
    });
    if (this.shortPinned) peek.classList.add('active');
    const update = () => {
      const n = this.shortWalls().length;
      btn.textContent = n ? `${n} Stücke löschen` : 'Keine Stücke';
      btn.disabled = !n;
      btn.classList.toggle('danger', n > 0);
      peek.disabled = !n;
    };
    inp.addEventListener('input', () => {
      const v = G.parseNumber(inp.value);
      if (!(v > 0)) return;
      if (this.ppm) this.opts.shortCm = v; else this.opts.shortPx = v;
      this.saveOpts();
      update();
      if (this.highlightShort) this.renderWalls();
    });
    const showShort = (on) => { this.highlightShort = on || this.shortPinned; this.renderWalls(); };
    btn.addEventListener('mouseenter', () => showShort(true));
    btn.addEventListener('mouseleave', () => showShort(false));
    btn.addEventListener('focus', () => showShort(true));
    btn.addEventListener('blur', () => showShort(false));
    inp.addEventListener('focus', () => showShort(true));
    inp.addEventListener('blur', () => showShort(false));
    update();
    div(s, 'small muted', 'Mit „Im Plan zeigen“ werden die betroffenen Stücke rot markiert.');
  }

  renderNewWallFields(p) {
    const s = section(p, 'Neue Wände');
    const grid = div(s, 'grid2');
    const unit = this.ppm ? 'cm' : 'px';
    const val = this.ppm ? this.opts.newThicknessCm : this.opts.newThicknessPx;
    const thick = field(grid, `Dicke (${unit})`, 'text', G.fmt(val, 1));
    thick.inputMode = 'decimal';
    thick.addEventListener('change', () => {
      const v = G.parseNumber(thick.value);
      if (!(v > 0)) return;
      if (this.ppm) this.opts.newThicknessCm = v; else this.opts.newThicknessPx = v;
      this.saveOpts();
    });
    const matLabel = document.createElement('label');
    matLabel.textContent = 'Material';
    const mat = document.createElement('select');
    for (const m of this.ctx.materials) mat.appendChild(new Option(m.name, m.id, false, m.id === this.opts.newMaterial));
    mat.addEventListener('change', () => { this.opts.newMaterial = mat.value; this.saveOpts(); });
    matLabel.appendChild(mat);
    grid.appendChild(matLabel);
    checkbox(s, 'Winkel in 45°-Schritten (Alt: frei)', this.opts.angleSnap, (v) => { this.opts.angleSnap = v; this.saveOpts(); });
  }

  renderNewWallPanel(p) {
    if (this.tool === 'draw') {
      if (this.draft?.start) {
        const box = div(section(p, 'Zeichnen'), 'callout row');
        div(box, 'small', TEXTS.drawActive).style.flex = '1';
        button(box, TEXTS.endDraw, () => this.endDraw()).classList.add('primary');
      }
      this.renderNewWallFields(p);
    }
    const pick = section(p, 'Auswählen');
    const row = div(pick, 'row');
    const multi = button(row, TEXTS.addWallMode, () => {
      this.multiSelect = !this.multiSelect;
      this.setTool('select');
    });
    if (this.multiSelect) multi.classList.add('active');
    button(row, 'Außenwände', () => this.selectExterior()).title = 'Wände, die an den Außenraum grenzen (Vorschlag, bitte prüfen)';
    button(row, 'Alle Wände', () => { this.selection = new Set(this.walls.map((w) => w.id)); this.setTool('select', false); this.renderAll(); });
    div(pick, 'small muted', 'Danach Material oder Dicke für alle ausgewählten Wände auf einmal setzen oder Ecken verbinden.');
    this.renderCleanupPanel(p);
    if (this.tool !== 'draw') this.renderNewWallFields(p);
  }
}

// --- Hilfen --------------------------------------------------------------------------------

function round2(v) {
  return Math.round(v * 100) / 100;
}

function intersectRaySegment(from, through, a, b) {
  // Schnitt der Geraden from→through mit der Strecke a–b
  const r = [through[0] - from[0], through[1] - from[1]];
  const s = [b[0] - a[0], b[1] - a[1]];
  const den = r[0] * s[1] - r[1] * s[0];
  if (Math.abs(den) < 1e-9) return null;
  const q = [a[0] - from[0], a[1] - from[1]];
  const t = (q[0] * s[1] - q[1] * s[0]) / den;
  const u = (q[0] * r[1] - q[1] * r[0]) / den;
  if (u < 0 || u > 1 || t <= 0) return null;
  return [from[0] + t * r[0], from[1] + t * r[1]];
}

function drawMeasure(g, a, b, label, vp) {
  el('line', { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: 'scale-line' }, g);
  const len = G.dist(a, b) || 1;
  const nx = (-(b[1] - a[1]) / len) * vp.px(8);
  const ny = ((b[0] - a[0]) / len) * vp.px(8);
  for (const p of [a, b]) {
    el('line', { x1: p[0] - nx, y1: p[1] - ny, x2: p[0] + nx, y2: p[1] + ny, class: 'scale-line' }, g);
  }
  const m = G.mid(a, b);
  const t = el('text', { x: m[0] + nx * 1.6, y: m[1] + ny * 1.6, class: 'scale-label', 'font-size': vp.px(13), 'text-anchor': 'middle' }, g);
  t.textContent = label;
}

function checkbox(parent, label, value, onChange) {
  const l = document.createElement('label');
  l.className = 'inline';
  const i = document.createElement('input');
  i.type = 'checkbox';
  i.checked = !!value;
  i.addEventListener('change', () => onChange(i.checked));
  l.append(i, document.createTextNode(label));
  parent.appendChild(l);
  return l;
}

function slider(parent, label, value, onInput) {
  const l = document.createElement('label');
  l.textContent = label;
  const i = document.createElement('input');
  i.type = 'range';
  i.min = 0;
  i.max = 1;
  i.step = 0.05;
  i.value = value;
  i.addEventListener('input', () => onInput(Number(i.value)));
  l.appendChild(i);
  parent.appendChild(l);
  return l;
}

export { checkbox, slider };
