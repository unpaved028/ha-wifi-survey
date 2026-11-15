// Ansicht „Pläne“: Plan hochladen, Seite anzeigen, Stockwerke als Ausschnitte festlegen.

import { api } from './api.js';
import { el, Viewport, isTyping } from './viewport.js';
import { normRect, fmt } from './geom.js';

const FLOOR_NAMES = ['Kellergeschoss', 'Erdgeschoss', '1. Obergeschoss', '2. Obergeschoss', 'Dachgeschoss', 'Garage'];
const LEVEL_GUESS = { Kellergeschoss: -1, Erdgeschoss: 0, '1. Obergeschoss': 1, '2. Obergeschoss': 2, Dachgeschoss: 2, Garage: 0 };

export class PlansView {
  constructor(ctx) {
    this.ctx = ctx;
    this.plan = null;
    this.pageIndex = 0;
    this.mode = 'select';
    this.selectedFloor = null;
    this.drag = null;
    this.pending = null;
  }

  async mount() {
    const { ctx } = this;
    this.vp = new Viewport(ctx.svg, { onChange: () => this.onViewChange() });
    this.vp.handler = this;
    this.layer = {
      image: el('g', {}, this.vp.world),
      crops: el('g', {}, this.vp.world),
      draft: el('g', {}, this.vp.world),
    };
    const plans = ctx.project.plans;
    const wanted = sessionStorage.getItem('ws-plan');
    this.plan = plans.find((p) => p.id === wanted) || plans[0] || null;
    this.keyHandler = (e) => this.onKey(e);
    window.addEventListener('keydown', this.keyHandler);
    this.renderPanel();
    this.renderStage(true);
  }

  async unmount() {
    window.removeEventListener('keydown', this.keyHandler);
    this.vp.destroy();
  }

  floorsOnPage() {
    if (!this.plan) return [];
    return this.ctx.project.floors.filter((f) => f.plan_id === this.plan.id && f.page === this.pageIndex);
  }

  // --- Panel ------------------------------------------------------------------------------

  renderPanel() {
    const { ctx } = this;
    const p = ctx.panel;
    p.replaceChildren();

    const up = section(p, 'Plan hochladen');
    const zone = div(up, 'dropzone', 'PDF oder Bild hierher ziehen oder');
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp';
    input.hidden = true;
    const pick = button(zone, 'Datei auswählen', () => input.click());
    pick.style.marginTop = '8px';
    zone.appendChild(input);
    input.addEventListener('change', () => input.files[0] && this.upload(input.files[0]));
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('over'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('over');
      if (e.dataTransfer.files[0]) this.upload(e.dataTransfer.files[0]);
    });

    const list = section(p, 'Pläne');
    if (!ctx.project.plans.length) div(list, 'muted', 'Noch kein Plan vorhanden.');
    for (const plan of ctx.project.plans) {
      const card = div(list, `card${this.plan?.id === plan.id ? ' selected' : ''}`);
      div(card, 'title', plan.name);
      const used = ctx.project.floors.filter((f) => f.plan_id === plan.id).length;
      div(card, 'small muted', `${plan.kind === 'pdf' ? 'PDF' : 'Bild'} · ${plan.pages.length} Seite(n) · ${used} Stockwerk(e)`);
      const row = div(card, 'row');
      if (this.plan?.id !== plan.id) button(row, 'Anzeigen', () => this.selectPlan(plan));
      const del = button(row, 'Löschen', async () => {
        if (!confirm(`Plan „${plan.name}“ löschen?`)) return;
        try {
          await api.deletePlan(plan.id);
          await ctx.refreshProject();
          if (this.plan?.id === plan.id) this.plan = ctx.project.plans[0] || null;
          this.renderPanel();
          this.renderStage(true);
        } catch (e) { ctx.toast(e.message, 'error'); }
      });
      del.classList.add('danger');
      del.disabled = used > 0;
      if (used > 0) del.title = 'Erst die Stockwerke dieses Plans löschen';
    }

    if (!this.plan) return;

    if (this.plan.pages.length > 1) {
      const pg = section(p, 'Seite');
      const sel = document.createElement('select');
      this.plan.pages.forEach((pg2, i) => {
        const o = document.createElement('option');
        o.value = i;
        o.textContent = `Seite ${i + 1}`;
        if (i === this.pageIndex) o.selected = true;
        sel.appendChild(o);
      });
      sel.addEventListener('change', () => {
        this.pageIndex = Number(sel.value);
        this.selectedFloor = null;
        this.renderPanel();
        this.renderStage(true);
      });
      pg.appendChild(sel);
    }

    const tools = section(p, 'Werkzeug');
    const tb = div(tools, 'toolbar');
    this.toolButton(tb, 'select', 'Auswählen', 'V');
    this.toolButton(tb, 'crop', 'Ausschnitt', 'C');
    const fitBtn = button(tb, 'Ganze Seite', () => this.vp.fit());
    fitBtn.insertAdjacentHTML('beforeend', '<span class="key">F</span>');

    if (this.pending) {
      const form = section(p, 'Neues Stockwerk');
      const used = new Set(ctx.project.floors.map((f) => f.name));
      const suggestion = FLOOR_NAMES.find((n) => !used.has(n)) || '';
      const name = field(form, 'Name', 'text', suggestion);
      name.setAttribute('list', 'floor-names');
      const dl = document.createElement('datalist');
      dl.id = 'floor-names';
      FLOOR_NAMES.forEach((n) => { const o = document.createElement('option'); o.value = n; dl.appendChild(o); });
      form.appendChild(dl);
      const level = field(form, 'Ebene (−1 Keller, 0 Erdgeschoss, 1 …)', 'number', LEVEL_GUESS[suggestion] ?? 0);
      name.addEventListener('input', () => { if (name.value in LEVEL_GUESS) level.value = LEVEL_GUESS[name.value]; });
      div(form, 'small muted', `Ausschnitt ${fmt(this.pending.w, 0)} × ${fmt(this.pending.h, 0)} (Seiteneinheiten)`);
      const row = div(form, 'row');
      const ok = button(row, 'Stockwerk anlegen', () => this.createFloor(name.value.trim(), Number(level.value)));
      ok.classList.add('primary');
      button(row, 'Abbrechen', () => { this.pending = null; this.renderPanel(); this.renderStage(); });
      setTimeout(() => name.focus(), 0);
    }

    const floors = section(p, 'Stockwerke auf dieser Seite');
    const onPage = this.floorsOnPage();
    if (!onPage.length) div(floors, 'muted small', 'Werkzeug „Ausschnitt“ wählen und ein Rechteck um ein Stockwerk ziehen.');
    for (const f of onPage.sort((a, b) => a.level - b.level)) {
      const card = div(floors, `card${this.selectedFloor === f.id ? ' selected' : ''}`);
      div(card, 'title', f.name);
      div(card, 'small muted', `Ebene ${f.level} · ${f.walls.length} Wände · ${f.scale ? 'Maßstab gesetzt' : 'ohne Maßstab'}`);
      const row = div(card, 'row');
      const open = button(row, 'Öffnen', () => ctx.navigate(`#/stockwerk/${f.id}`));
      open.classList.add('primary');
      button(row, this.selectedFloor === f.id ? 'Fertig' : 'Ausschnitt ändern', () => {
        this.selectedFloor = this.selectedFloor === f.id ? null : f.id;
        this.setMode('select');
      });
      const del = button(row, 'Löschen', () => this.deleteFloor(f));
      del.classList.add('danger');
    }

    this.renderTransfer(p);
  }

  // Projekt sichern oder auf einen anderen Server übertragen (z. B. in die Home-Assistant-App)
  renderTransfer(p) {
    const s = section(p, 'Projekt');
    const row = div(s, 'row');
    const a = document.createElement('a');
    a.href = api.exportUrl();
    a.download = '';
    a.className = 'button-link';
    a.textContent = 'Exportieren';
    a.title = 'Pläne, Stockwerke, Wände, Geräte, Messpunkte und Messläufe als ZIP-Datei';
    row.appendChild(a);
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.zip,application/zip';
    input.hidden = true;
    input.addEventListener('change', () => input.files[0] && this.importProject(input.files[0]));
    button(row, 'Importieren …', () => input.click());
    s.appendChild(input);
    div(s, 'small muted', 'Zum Sichern oder Übertragen auf einen anderen Server. Beim Import wird das bisherige Projekt ersetzt und auf dem Server aufbewahrt.');
  }

  async importProject(file) {
    const { ctx } = this;
    const count = ctx.project.floors.length;
    if (count && !confirm(`Das aktuelle Projekt (${count} Stockwerke) durch „${file.name}“ ersetzen? Es bleibt auf dem Server als Sicherung erhalten.`)) return;
    ctx.toast(`Importiere „${file.name}“ …`);
    try {
      const r = await api.importProject(file);
      for (const k of ['ws-plan', 'ws-eval-floor', 'ws-sim']) sessionStorage.removeItem(k);   // alte IDs
      const n = (k, one, many) => `${k} ${k === 1 ? one : many}`;
      ctx.toast(`Importiert: ${n(r.plans, 'Plan', 'Pläne')}, ${n(r.floors, 'Stockwerk', 'Stockwerke')}, `
        + `${n(r.measurements_added, 'neuer Messlauf', 'neue Messläufe')}`, 'ok');
      ctx.navigate('#/plaene');
    } catch (e) {
      ctx.toast(e.message, 'error');
    }
  }

  toolButton(parent, mode, label, key) {
    const b = button(parent, label, () => this.setMode(mode));
    b.insertAdjacentHTML('beforeend', `<span class="key">${key}</span>`);
    if (this.mode === mode) b.classList.add('active');
    return b;
  }

  setMode(mode) {
    this.mode = mode;
    this.drag = null;
    this.ctx.svg.classList.toggle('tool-crop', mode === 'crop');
    this.ctx.hint(mode === 'crop'
      ? 'Rechteck um ein Stockwerk ziehen. Mausrad zoomt, Leertaste + Ziehen verschiebt.'
      : 'Ausschnitt anklicken, um ihn zu verschieben oder an den Ecken zu ändern. Ziehen auf freier Fläche verschiebt die Ansicht.');
    this.renderPanel();
    this.renderStage();
  }

  selectPlan(plan) {
    this.plan = plan;
    this.pageIndex = 0;
    this.selectedFloor = null;
    this.pending = null;
    sessionStorage.setItem('ws-plan', plan.id);
    this.renderPanel();
    this.renderStage(true);
  }

  async upload(file) {
    const { ctx } = this;
    ctx.toast(`Lade „${file.name}“ hoch …`);
    try {
      const plan = await api.uploadPlan(file);
      await ctx.refreshProject();
      ctx.toast(`Plan „${plan.name}“ übernommen`, 'ok');
      this.selectPlan(ctx.project.plans.find((p) => p.id === plan.id));
      this.setMode('crop');
    } catch (e) {
      ctx.toast(`Hochladen fehlgeschlagen: ${e.message}`, 'error');
    }
  }

  async createFloor(name, level) {
    const { ctx } = this;
    if (!name) { ctx.toast('Bitte einen Namen eingeben', 'error'); return; }
    try {
      const floor = await api.createFloor({ name, level, plan_id: this.plan.id, page: this.pageIndex, crop: this.pending });
      this.pending = null;
      await ctx.refreshProject();
      ctx.toast(`„${floor.name}“ angelegt – jetzt öffnen, Maßstab setzen und Wände erkennen lassen`, 'ok');
      this.renderPanel();
      this.renderStage();
    } catch (e) {
      ctx.toast(e.message, 'error');
    }
  }

  async deleteFloor(f) {
    const { ctx } = this;
    if (!confirm(`Stockwerk „${f.name}“ mit ${f.walls.length} Wänden löschen?`)) return;
    try {
      await api.deleteFloor(f.id);
      await ctx.refreshProject();
      this.selectedFloor = null;
      this.renderPanel();
      this.renderStage();
    } catch (e) { ctx.toast(e.message, 'error'); }
  }

  // --- Zeichenfläche ----------------------------------------------------------------------

  renderStage(fit = false) {
    const { image } = this.layer;
    image.replaceChildren();
    if (!this.plan) {
      this.ctx.hint('Zuerst einen Plan hochladen (PDF oder Bild).');
      this.renderCrops();
      return;
    }
    const page = this.plan.pages[this.pageIndex];
    el('rect', { x: 0, y: 0, width: page.width, height: page.height, fill: 'var(--plan-paper)', class: 'plan-paper' }, image);
    el('image', { href: api.pagePreviewUrl(this.plan.id, this.pageIndex), x: 0, y: 0, width: page.width, height: page.height, class: 'plan-img' }, image);
    if (fit) {
      this.vp.contentBox = { x: 0, y: 0, w: page.width, h: page.height };
      requestAnimationFrame(() => this.vp.fit());
    }
    this.renderCrops();
    if (!this.ctx.hintEl.textContent || fit) this.setModeHintOnly();
  }

  setModeHintOnly() {
    this.ctx.hint(this.mode === 'crop'
      ? 'Rechteck um ein Stockwerk ziehen. Mausrad zoomt, Leertaste + Ziehen verschiebt.'
      : 'Werkzeug „Ausschnitt“ (C) wählen, um ein Stockwerk festzulegen. Ziehen verschiebt die Ansicht, Mausrad zoomt.');
  }

  renderCrops() {
    const g = this.layer.crops;
    g.replaceChildren();
    const fontSize = this.vp.px(14);
    for (const f of this.floorsOnPage()) {
      const c = this.drag?.floorId === f.id ? this.drag.rect : f.crop;
      const selected = this.selectedFloor === f.id;
      el('rect', { x: c.x, y: c.y, width: c.w, height: c.h, class: `crop-rect${selected ? ' selected' : ''}`, 'data-floor': f.id }, g);
      const t = el('text', { x: c.x + this.vp.px(6), y: c.y + fontSize * 1.2, class: 'crop-label', 'font-size': fontSize }, g);
      t.textContent = f.name;
      if (selected) {
        for (const [corner, x, y] of [['nw', c.x, c.y], ['ne', c.x + c.w, c.y], ['sw', c.x, c.y + c.h], ['se', c.x + c.w, c.y + c.h]]) {
          el('circle', { cx: x, cy: y, r: this.vp.px(7), class: 'handle', 'data-corner': corner, 'data-floor': f.id }, g);
        }
      }
    }
    const d = this.layer.draft;
    d.replaceChildren();
    const r = this.drag?.kind === 'new' ? this.drag.rect : this.pending;
    if (r) el('rect', { x: r.x, y: r.y, width: r.w, height: r.h, class: 'box-select' }, d);
  }

  onViewChange() {
    this.ctx.status(undefined, `Zoom ${fmt(this.vp.s * 100, 0)} %`);
    this.renderCrops();
  }

  // --- Bedienung --------------------------------------------------------------------------

  down(e, w) {
    if (e.button !== 0) return false;
    if (this.mode === 'crop') {
      this.pending = null;
      this.drag = { kind: 'new', start: w, rect: normRect(w, w) };
      return true;
    }
    const corner = e.target.dataset?.corner;
    const floorId = e.target.dataset?.floor;
    if (floorId) {
      const f = this.ctx.project.floors.find((x) => x.id === floorId);
      if (corner && this.selectedFloor === floorId) {
        this.drag = { kind: 'resize', floorId, corner, start: w, orig: { ...f.crop }, rect: { ...f.crop } };
        return true;
      }
      if (this.selectedFloor !== floorId) {
        this.selectedFloor = floorId;
        this.renderPanel();
        this.renderCrops();
        return true;
      }
      this.drag = { kind: 'move', floorId, start: w, orig: { ...f.crop }, rect: { ...f.crop } };
      this.ctx.svg.classList.add('tool-move');
      return true;
    }
    if (this.selectedFloor) {
      this.selectedFloor = null;
      this.renderPanel();
      this.renderCrops();
    }
    return 'pan';
  }

  hover(e, w) {
    this.ctx.status(`x ${fmt(w[0], 0)} · y ${fmt(w[1], 0)}`);
  }

  move(e, w) {
    const d = this.drag;
    if (!d) return;
    if (d.kind === 'new') {
      d.rect = normRect(d.start, w);
    } else if (d.kind === 'move') {
      d.rect = { ...d.orig, x: d.orig.x + w[0] - d.start[0], y: d.orig.y + w[1] - d.start[1] };
    } else if (d.kind === 'resize') {
      const o = d.orig;
      let x0 = o.x, y0 = o.y, x1 = o.x + o.w, y1 = o.y + o.h;
      if (d.corner.includes('w')) x0 = w[0];
      if (d.corner.includes('e')) x1 = w[0];
      if (d.corner.includes('n')) y0 = w[1];
      if (d.corner.includes('s')) y1 = w[1];
      d.rect = normRect([x0, y0], [x1, y1]);
    }
    this.renderCrops();
  }

  async up() {
    const d = this.drag;
    this.drag = null;
    this.ctx.svg.classList.remove('tool-move');
    if (!d) return;
    if (d.kind === 'new') {
      if (d.rect.w < 20 || d.rect.h < 20) { this.renderCrops(); return; }
      this.pending = d.rect;
      this.renderPanel();
      this.renderCrops();
      return;
    }
    const moved = Math.abs(d.rect.x - d.orig.x) + Math.abs(d.rect.y - d.orig.y) + Math.abs(d.rect.w - d.orig.w) + Math.abs(d.rect.h - d.orig.h);
    if (moved < 1) { this.renderCrops(); return; }
    try {
      this.ctx.setSaveState('saving');
      await api.updateFloor(d.floorId, { crop: d.rect });
      await this.ctx.refreshProject();
      this.ctx.setSaveState('saved');
      this.ctx.toast('Ausschnitt geändert, Wände wurden mitverschoben', 'ok');
    } catch (e) {
      this.ctx.setSaveState('error');
      this.ctx.toast(e.message, 'error');
    }
    this.renderPanel();
    this.renderCrops();
  }

  cancel() {
    this.drag = null;
    this.renderCrops();
  }

  onKey(e) {
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'v' || e.key === 'V') this.setMode('select');
    else if (e.key === 'c' || e.key === 'C') this.setMode('crop');
    else if (e.key === 'f' || e.key === 'F') this.vp.fit();
    else if (e.key === 'Escape') {
      this.drag = null;
      this.pending = null;
      this.selectedFloor = null;
      this.renderPanel();
      this.renderCrops();
    }
  }
}

// --- kleine DOM-Helfer (auch von anderen Ansichten genutzt) --------------------------------

export function section(parent, title) {
  const s = document.createElement('div');
  s.className = 'section';
  if (title) {
    const h = document.createElement('h2');
    h.textContent = title;
    s.appendChild(h);
  }
  parent.appendChild(s);
  return s;
}

export function div(parent, cls = '', text = '') {
  const d = document.createElement('div');
  if (cls) d.className = cls;
  if (text) d.textContent = text;
  parent.appendChild(d);
  return d;
}

export function button(parent, label, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.textContent = label;
  b.addEventListener('click', onClick);
  parent.appendChild(b);
  return b;
}

export function field(parent, label, type = 'text', value = '') {
  const l = document.createElement('label');
  l.textContent = label;
  const i = document.createElement('input');
  i.type = type;
  if (type === 'number') i.step = 'any';
  i.value = value;
  l.appendChild(i);
  parent.appendChild(l);
  return i;
}
