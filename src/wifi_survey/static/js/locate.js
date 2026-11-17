// Ansicht „Suchen“: Wo ist mein Handy? Die FRITZ!Box kennt nur den Zugangspunkt eines Geräts und das
// Signal, mit dem er es empfängt. Der Server rechnet daraus mit dem geeichten Modell eine Wahrscheinlichkeit
// über alle Stockwerke (Bereich statt Punkt, Entscheidung 0009) und je Raum (Entscheidung 0014). Gefunden? Fundort antippen und speichern:
// er geht als Messpunkt in die Eichung ein und zeigt, wie gut die Schätzung lag.

import { api } from './api.js';
import { el, Viewport, isTyping } from './viewport.js';
import * as G from './geom.js';
import { section, div, button } from './plans.js';

const TAP_PX = 10;               // weiter bewegt: Verschieben statt Antippen
const FLOOR_HEIGHT_M = 2.8;
const Z_STRETCH = 2.4;           // Stockwerke in 3D weiter auseinander, damit man hineinsieht
const VIOLET = 'var(--locate-violet)';
const FOUND = 'var(--locate-found)';

const bandLabel = (b) => (b === '2.4' ? '2,4' : b || '?');
const when = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
};
const toM = (f, p) => {        // Bildpixel -> Gebäude (m), wie evaluate.Building.to_m
  const q = G.rotate([p[0] / f.scale.px_per_m, p[1] / f.scale.px_per_m], f.transform.rot_deg);
  return [q[0] + f.transform.dx_m, q[1] + f.transform.dy_m];
};

export class LocateView {
  constructor(ctx, floorId) {
    this.ctx = ctx;
    this.floorId = floorId;
    this.list = null;            // {source, measured_at, error, devices}
    this.filter = '';
    this.device = null;          // gewähltes Gerät (aus der Liste)
    this.result = null;          // Antwort von api/locate
    this.room = null;            // gewählter Raum aus der Liste (Schlüssel floor_id:id)
    this.mode = '3d';            // '3d' | '2d'
    this.marking = false;        // Fundort antippen
    this.foundPos = null;
    this.busy = '';
    this.rot = { x: 56, z: -30 };
  }

  async mount() {
    const { ctx } = this;
    this.floors = ctx.floorsSorted().filter((f) => f.scale);
    this.floor = this.floors.find((f) => f.id === this.floorId) || this.floors.find((f) => f.level === 0) || this.floors[0] || null;
    this.vp = new Viewport(ctx.svg, { onChange: () => this.renderOverlay() });
    this.vp.handler = this;
    this.keyHandler = (e) => {
      if (isTyping(e) || (e.key !== 'f' && e.key !== 'F')) return;
      if (this.mode === '2d') this.vp.fit();
      else this.reset3d();
    };
    window.addEventListener('keydown', this.keyHandler);
    this.scene = document.createElement('div');
    this.scene.id = 'scene3d';
    ctx.svg.parentElement.appendChild(this.scene);
    this.bind3d();
    // Antippen in 2D (Fundort oder Raumauswahl): Finger kaum bewegt; Verschieben und Zoomen übernimmt der Viewport
    this.onPointerDown = (e) => { this.tap = e.isPrimary ? { x: e.clientX, y: e.clientY, multi: false } : { ...this.tap, multi: true }; };
    this.onPointerUp = (e) => {
      const t = this.tap;
      this.tap = null;
      if (!t || t.multi || !e.isPrimary || Math.hypot(e.clientX - t.x, e.clientY - t.y) > TAP_PX) return;
      const w = this.vp.toWorld(e.clientX, e.clientY);
      if (this.marking) {
        this.foundPos = w.map((v) => Math.round(v * 10) / 10);
        this.renderOverlay();
        this.renderPanel();
        return;
      }
      if (this.mode === '2d') {
        const fr = this.floorResult(this.floor?.id);
        const hit = (fr?.rooms || []).find((rm) => rm.contours.some((pg) => G.inPolygon(w, pg)));
        if (hit) {
          this.room = `${this.floor.id}:${hit.id}`;
          this.render2d();
          this.renderPanel();
          document.querySelector(`#panel ol.room-rank li[data-room='${this.room}']`)?.scrollIntoView({ block: 'nearest' });
        }
      }
    };
    ctx.svg.addEventListener('pointerdown', this.onPointerDown);
    ctx.svg.addEventListener('pointerup', this.onPointerUp);
    this.onResize = () => { if (this.mode === '3d') this.render3d(); };
    window.addEventListener('resize', this.onResize);
    if (this.floor) this.build2d();
    this.show();
    this.renderPanel();
    if (this.floors.length) await this.loadDevices(false);
  }

  async unmount() {
    window.removeEventListener('keydown', this.keyHandler);
    window.removeEventListener('resize', this.onResize);
    this.ctx.svg.removeEventListener('pointerdown', this.onPointerDown);
    this.ctx.svg.removeEventListener('pointerup', this.onPointerUp);
    this.ctx.svg.style.visibility = '';
    this.scene.remove();
    this.vp.destroy();
  }

  // --- Daten ------------------------------------------------------------------------------

  async loadDevices(refresh) {
    this.busy = refresh ? 'list' : '';
    this.renderPanel();
    try {
      this.list = await api.locateDevices(refresh);
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
    this.busy = '';
    this.renderPanel();
  }

  async search(dev, basis = 'auto') {
    this.device = dev;
    this.result = null;
    this.marking = false;
    this.foundPos = null;
    this.busy = 'locate';
    this.renderPanel();
    try {
      this.result = await api.locate(dev.key, basis);
      this.room = this.result.rooms?.[0]?.key || null;
      const best = this.floors.find((f) => f.id === this.result.best.floor_id);
      if (best && best.id !== this.floor?.id) this.setFloor(best, false);
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
    this.busy = '';
    this.toTop = true;           // Ergebnis oben im Panel zeigen (auf dem Handy wäre es sonst weit unten)
    this.renderPanel();
    this.renderStage();
  }

  async saveFound(force = false) {
    const { ctx } = this;
    if (!this.foundPos || !this.result) return;
    try {
      const fp = await api.addFound(this.floor.id, {
        device: this.device.key, label: this.device.label, pos: this.foundPos, reading: this.result.reading, force,
        scan_t: this.result.scan?.t || null,
      });
      await ctx.refreshProject();
      this.floors = ctx.floorsSorted().filter((f) => f.scale);
      this.floor = this.floors.find((f) => f.id === this.floor.id);
      this.marking = false;
      this.foundPos = null;
      const dist = fp.error_m != null ? `${G.fmt(fp.error_m, 1)} m von der wahrscheinlichsten Stelle, ` : '';
      const region = fp.in_region ? 'im wahrscheinlichen Bereich' : 'außerhalb des wahrscheinlichen Bereichs';
      const scan = fp.survey_point ? ' Der Scan des Handys zählt dort als Messpunkt.' : '';
      ctx.toast(`Fundort gespeichert: ${dist}${region}. Danke – er fließt in die Eichung ein.${scan}`, 'ok');
      this.build2d();
      this.updateHint();
      this.renderStage();
      this.renderPanel();
    } catch (e) {
      if (e.code === 'unchanged' && !force) {
        if (confirm(e.message)) await this.saveFound(true);
        return;
      }
      ctx.toast(e.message, 'error');
    }
  }

  async deleteFound(floor, fp) {
    if (!confirm(`Fundort von „${fp.label || fp.device}“ löschen?`)) return;
    try {
      await api.deleteFound(floor.id, fp.id);
      await this.ctx.refreshProject();
      this.floors = this.ctx.floorsSorted().filter((f) => f.scale);
      this.floor = this.floors.find((f) => f.id === this.floor?.id) || this.floor;
      this.build2d();
      this.renderStage();
      this.renderPanel();
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
  }

  // --- Panel ------------------------------------------------------------------------------

  renderPanel() {
    const p = this.ctx.panel;
    const scroll = p.scrollTop;
    p.replaceChildren();
    if (!this.floors.length) {
      const s = section(p, 'Gerät suchen');
      div(s, 'muted', 'Zum Suchen braucht mindestens ein Stockwerk einen Maßstab, Wände und platzierte Zugangspunkte.');
      return;
    }
    if (this.result) this.renderResult(p);     // Ergebnis zuerst: auf dem Handy sofort ohne Scrollen sichtbar
    const s = section(p, 'Gerät suchen');
    if (this.busy === 'locate' && this.device && !this.result) {
      div(s, 'muted', `Suche „${this.device.label}“ …`);
    }
    const row = div(s, 'row');
    const refresh = button(row, this.busy === 'list' ? 'Frage FRITZ!Box …' : 'Liste aktualisieren', () => this.loadDevices(true));
    refresh.disabled = !!this.busy;
    if (this.list) {
      const src = this.list.source === 'live' ? `Stand ${when(this.list.measured_at)} (FRITZ!Box)`
        : this.list.source === 'beispiel' ? 'Geräte des Beispielhauses' : `Stand des Messlaufs vom ${when(this.list.measured_at)}`;
      div(s, 'small muted', src);
      if (this.list.error) div(s, 'small callout', `FRITZ!Box nicht erreichbar: ${this.list.error}`);
    }
    this.renderList(p);
    this.renderFound(p);
    div(section(p, 'So funktioniert die Suche'), 'small muted', 'Die FRITZ!Box weiß, an welchem Zugangspunkt ein Gerät hängt und wie stark er es empfängt. '
      + 'Daraus schätzt die App, in welchen Räumen es am ehesten liegt. Genauer wird es mit „findbar“: '
      + 'Ein Android-Handy mit der App meldet im Ruhen alle Zugangspunkte (Ansicht „Messen“).');
    p.scrollTop = this.toTop ? 0 : scroll;
    this.toTop = false;
  }

  renderList(p) {
    if (!this.list) return;
    const s = section(p, this.result ? 'Anderes Gerät' : 'Geräte im WLAN');
    const input = document.createElement('input');
    input.type = 'search';
    input.placeholder = 'Gerät filtern (Name, Zugangspunkt)';
    input.value = this.filter;
    input.addEventListener('input', () => {
      this.filter = input.value;
      this.renderListItems(list);
    });
    s.appendChild(input);
    const list = div(s, 'device-list');
    this.renderListItems(list);
  }

  renderListItems(list) {
    list.replaceChildren();
    const q = this.filter.trim().toLowerCase();
    const devs = this.list.devices.filter((d) => !q || `${d.label} ${d.ap_label} ${d.placed || ''}`.toLowerCase().includes(q));
    if (!devs.length) div(list, 'small muted', 'Kein Gerät im WLAN gefunden.');
    for (const d of devs) {
      const item = div(list, `device-item${this.device?.key === d.key ? ' selected' : ''}`);
      item.dataset.dev = d.key;
      div(item, 'title', d.label);
      div(item, 'small muted', `an ${d.ap_label} · ${bandLabel(d.band)} GHz · ${d.rssi} dBm${d.placed ? ` · platziert: ${d.placed}` : ''}`
        + `${d.findable ? ` · findbar, gemeldet ${when(d.findable.t)} (${Object.keys(d.findable.aps || {}).length} Zugangspunkte)` : ''}`);
      item.addEventListener('click', () => { if (!this.busy) this.search(d); });
    }
  }

  renderResult(p) {
    const r = this.result;
    const s = section(p, `Wo ist „${this.device.label}“?`);
    if (this.busy === 'locate') div(s, 'muted', 'Rechne …');
    if (r.rooms?.length) {
      div(s, 'room-rank-head', 'Wo zuerst nachsehen:');
      const ol = document.createElement('ol');
      ol.className = 'room-rank';
      r.rooms.slice(0, 5).forEach((rm, idx) => {
        const li = document.createElement('li');
        const cls = [];
        if (idx === 0) cls.push('top');
        if (this.room === rm.key) cls.push('current');
        li.className = cls.join(' ');
        li.dataset.room = rm.key;
        div(li, 'room-rank-num', String(idx + 1));
        const info = div(li, 'room-rank-info');
        div(info, 'room-rank-name', rm.name);
        div(info, 'room-rank-floor', rm.floor);
        const bar = div(li, 'room-rank-bar');
        const track = div(bar, 'share-track');
        const fill = div(track, 'share-bar');
        fill.style.width = `${Math.min(100, Math.max(rm.share, rm.share > 0 ? 2 : 0))}%`;
        div(li, 'room-rank-pct num', `${rm.share} %`);
        li.addEventListener('click', () => {
          this.room = rm.key;
          this.setFloor(this.floors.find((x) => x.id === rm.floor_id), true);
        });
        ol.appendChild(li);
      });
      s.appendChild(ol);
    }
    const views = div(s, 'row');
    const b3 = button(views, '3D-Ansicht', () => { this.mode = '3d'; this.marking = false; this.show(); this.renderPanel(); });
    const b2 = button(views, 'Stockwerk', () => { this.mode = '2d'; this.show(); this.renderPanel(); });
    (this.mode === '3d' ? b3 : b2).classList.add('active');
    if (this.mode === '3d') {
      const rBtn = button(views, 'Drehung zurücksetzen', () => this.reset3d());
      rBtn.title = 'Standard-Blickwinkel wiederherstellen (Taste F)';
    }
    if (!this.marking) {
      const f = button(s, 'Gefunden – Fundort antippen', () => {
        this.marking = true;
        this.foundPos = null;
        this.mode = '2d';
        this.show();
        this.renderPanel();
      });
      f.classList.add('primary');
    } else {
      div(s, 'callout', `Tippe auf die Stelle, an der „${this.device.label}“ lag. Das Stockwerk wählst du in der Tabelle darunter.`);
      const row = div(s, 'row');
      const ok = button(row, 'Fundort speichern', () => this.saveFound());
      ok.classList.add('primary');
      ok.disabled = !this.foundPos;
      button(row, 'Abbrechen', () => { this.marking = false; this.foundPos = null; this.updateHint(); this.renderOverlay(); this.renderPanel(); });
    }
    const tbl = document.createElement('table');
    tbl.className = 'mini share-table';
    for (const f of r.floors) {
      const tr = tbl.insertRow();
      tr.className = `link${f.id === this.floor?.id && this.mode === '2d' ? ' current' : ''}`;
      tr.insertCell().textContent = f.name;
      const bar = tr.insertCell();
      bar.className = 'share-cell';
      const track = div(bar, 'share-track');
      const fill = div(track, 'share-bar');
      fill.style.width = `${Math.min(100, Math.max(f.share, f.share > 0 ? 2 : 0))}%`;
      const td = tr.insertCell();
      td.className = 'num';
      td.textContent = `${f.share} %`;
      tr.addEventListener('click', () => this.setFloor(this.floors.find((x) => x.id === f.id), true));
    }
    s.appendChild(tbl);
    const at = r.source === 'live' ? `abgefragt ${when(r.reading.measured_at)}` : `aus dem Messlauf vom ${when(r.reading.measured_at)}`;
    div(s, 'small', `${r.reading.rssi} dBm an ${this.device.ap_label} (${bandLabel(r.reading.band)} GHz, ${at}). `
      + `Wahrscheinlicher Bereich (${Math.round(r.region_mass * 100)} %): etwa ${G.fmt(r.area_m2, 0)} m².`);
    if (r.source === 'beispiel') {
      div(s, 'small muted', 'Beispielhaus: Die Werte stammen aus dem erzeugten Messlauf, die Geräte liegen dort, wo das Beispiel sie hinlegt.');
    } else if (r.source !== 'live') {
      div(s, 'small callout', 'Kein aktueller Wert der FRITZ!Box: Ein Fundort passt nur dazu, wenn das Gerät seit dem Messlauf dort lag.');
    } else if (r.previous?.unchanged) {
      div(s, 'small callout', `Gleicher Wert wie beim letzten Fundort (${when(r.previous.t)}, ${r.previous.floor}). `
        + 'Ruhende Geräte erneuert die FRITZ!Box nur alle paar Minuten. Wurde das Gerät umgelegt: ein paar Minuten warten und neu suchen.');
    }
    this.renderBasis(s, r);
    if (r.skipped.length) div(s, 'small muted', `Nicht berücksichtigt: ${r.skipped.join(', ')} (nicht ausgerichtet oder ohne Auswertung).`);
    const band5 = r.reading.band === '5' || r.reading.band === '6';
    div(s, 'small muted', r.basis === 'scan'
      ? `Unsicherheit etwa ±${G.fmt(r.sigma_db, 0)} dB je Wert; gemeinsam schwächere Werte (Handy zugedeckt) verschieben die Schätzung kaum.`
      : `Unsicherheit etwa ±${G.fmt(r.sigma_db, 0)} dB${band5 ? ' (5 GHz kennt das Modell nur als Abschlag)' : ''}, `
        + 'deshalb ein Bereich statt eines Punkts. Jeder gemeldete Fundort macht die Schätzung genauer.');
  }

  // Womit gerechnet wurde: eigener Scan des Handys („findbar“) oder der eine Wert der FRITZ!Box
  renderBasis(s, r) {
    const f = r.findable;
    const list = f ? this.scanList(f.aps) : '';
    if (r.basis === 'scan') {
      const still = f.still_s ? `, ruhte da seit ${Math.round(f.still_s / 60)} min` : '';
      div(s, 'small', `Grundlage: Scan des Handys von ${when(f.t)} (${r.scan.n} Werte${still}) – alle Zugangspunkte, nicht nur der eine.`);
      div(s, 'small muted', `Gemeldet: ${list}`);
      button(s, 'Nur mit dem Wert der FRITZ!Box rechnen', () => this.search(this.device, 'fritzbox'));
    } else if (f?.usable) {
      div(s, 'small muted', `Es gibt einen Scan des Handys von ${when(f.t)}: ${list}`);
      button(s, 'Mit dem Scan des Handys rechnen', () => this.search(this.device, 'auto'));
    } else if (f) {
      div(s, 'small callout', `Scan des Handys von ${when(f.t)} nicht genutzt: ${f.why}${list ? ` Gemeldet: ${list}` : ''}`);
    }
  }

  // „DG-Bad 2,4 GHz −52, 5 GHz −55 · OG-Bad 2,4 GHz −74“ (Werte der Meldung „findbar“)
  scanList(aps) {
    const label = (key) => this.floors.flatMap((f) => f.devices || []).find((d) => d.key === key)?.label || key;
    return Object.entries(aps || {})
      .map(([key, bands]) => `${label(key)} ${Object.entries(bands).map(([b, v]) => `${bandLabel(b)} GHz ${v}`).join(', ')}`)
      .join(' · ');
  }

  renderFound(p) {
    const all = this.floors.flatMap((f) => (f.found || []).map((fp) => ({ f, fp })));
    if (!all.length) return;
    const s = section(p, 'Fundorte');
    const inRegion = all.filter(({ fp }) => fp.in_region).length;
    const ranked = all.filter(({ fp }) => fp.room_rank != null);
    const top1 = ranked.filter(({ fp }) => fp.room_rank === 1).length;
    const top2 = ranked.filter(({ fp }) => fp.room_rank <= 2).length;
    const summary = div(s, 'found-summary');
    if (ranked.length) {
      const main = div(summary, 'found-summary-main');
      main.append('Raum-Trefferquote: ');
      const b1 = document.createElement('strong');
      b1.textContent = `${top1} von ${ranked.length}`;
      main.append(b1, ' direkt im 1. Raum');
      if (ranked.length > 1 || top2 > top1) {
        const b2 = document.createElement('strong');
        b2.textContent = `${top2} von ${ranked.length} (${Math.round((top2 / ranked.length) * 100)} %)`;
        main.append(' · ', b2, ' in den ersten 2 Räumen');
      }
      div(summary, 'small muted', `${inRegion} von ${all.length} im 50-%-Bereich · Jeder gemeldete Fundort eicht das Modell mit.`);
    } else {
      const main = div(summary, 'found-summary-main');
      const b = document.createElement('strong');
      b.textContent = `${inRegion} von ${all.length}`;
      main.append(b, ' im 50-%-Bereich');
      div(summary, 'small muted', 'Jeder gemeldete Fundort eicht das Modell mit.');
    }
    const tbl = document.createElement('table');
    tbl.className = 'mini tight found-table';
    const head = tbl.createTHead().insertRow();
    for (const h of ['Gerät', 'Stockwerk', 'Treffer', '']) head.insertCell().textContent = h;
    const tbody = tbl.createTBody();
    for (const { f, fp } of all.sort((a, b) => b.fp.t.localeCompare(a.fp.t))) {
      const tr = tbody.insertRow();
      const devCell = tr.insertCell();
      div(devCell, 'found-dev', fp.label || fp.device);
      const tStr = when(fp.t);
      if (tStr) div(devCell, 'found-time muted', tStr);
      tr.insertCell().textContent = f.name;
      const hitCell = tr.insertCell();
      const hit = div(hitCell, 'found-hit');
      if (fp.room_rank != null) {
        const cls = fp.room_rank === 1 ? 'ok' : fp.room_rank === 2 ? 'ha' : 'warn';
        div(hit, `badge ${cls}`, `${fp.room_rank}. Raum`);
      }
      const detail = div(hit, 'found-hit-detail');
      detail.textContent = fp.in_region ? '50-%-Bereich' : 'außerhalb';
      if (fp.error_m != null) {
        detail.append(' · ');
        const dist = document.createElement('span');
        dist.className = 'nowrap';
        dist.textContent = `${G.fmt(fp.error_m, 1)} m`;
        detail.appendChild(dist);
      }
      const del = document.createElement('button');
      del.textContent = '✕';
      del.title = 'Fundort löschen';
      del.className = 'danger';
      del.addEventListener('click', () => this.deleteFound(f, fp));
      tr.insertCell().appendChild(del);
    }
    s.appendChild(tbl);
  }

  // --- Zeichenfläche: Umschalten -----------------------------------------------------------

  show() {
    const three = this.mode === '3d';
    this.scene.hidden = !three;
    this.ctx.svg.style.visibility = three ? 'hidden' : '';
    this.updateHint();
    this.renderStage();
    if (!three) requestAnimationFrame(() => this.fit2d());
  }

  updateHint() {
    this.ctx.hint(this.mode === '3d'
      ? 'Haus in 3D: Ziehen dreht die Ansicht, ein Klick auf ein Stockwerk öffnet es. Violett: wo das Gerät wahrscheinlich ist.'
      : this.marking ? 'Fundort antippen. Mausrad oder zwei Finger zoomen, Ziehen verschiebt.'
        : 'Violett: wo das Gerät wahrscheinlich ist (Linie: Bereich mit 50 % Wahrscheinlichkeit, Kreuz: wahrscheinlichste Stelle). '
          + 'Gestrichelt: Räume mit ihrer Wahrscheinlichkeit (Klick wählt einen Raum).');
  }

  setFloor(floor, show2d) {
    if (!floor) return;
    this.floor = floor;
    this.foundPos = null;
    this.build2d();
    if (show2d) this.mode = '2d';
    this.show();
    this.renderPanel();
  }

  renderStage() {
    if (this.mode === '3d') this.render3d();
    else this.render2d();
  }

  // --- 2D ---------------------------------------------------------------------------------

  build2d() {
    const w = this.vp.world;
    w.replaceChildren();
    const f = this.floor;
    this.layer = { image: el('g', {}, w), walls: el('g', {}, w), heat: el('g', {}, w), rooms: el('g', {}, w), marks: el('g', {}, w) };
    el('rect', { x: 0, y: 0, width: f.image_w, height: f.image_h, fill: 'var(--plan-paper)', class: 'plan-paper' }, this.layer.image);
    el('image', { href: api.floorImageUrl(f), x: 0, y: 0, width: f.image_w, height: f.image_h, opacity: 0.45, class: 'plan-img' }, this.layer.image);
    for (const wl of f.walls) {
      el('line', { x1: wl.a[0], y1: wl.a[1], x2: wl.b[0], y2: wl.b[1], stroke: 'var(--wall-map)', 'stroke-width': wl.thickness_px, 'stroke-opacity': 0.5 }, this.layer.walls);
    }
    this.vp.contentBox = this.wallsBox(f) || { x: 0, y: 0, w: f.image_w, h: f.image_h };
  }

  wallsBox(f) {
    const pts = f.walls.flatMap((w) => [w.a, w.b]);
    if (!pts.length) return null;
    const xs = pts.map((q) => q[0]);
    const ys = pts.map((q) => q[1]);
    const x0 = Math.min(...xs); const y0 = Math.min(...ys);
    return { x: x0, y: y0, w: Math.max(...xs) - x0, h: Math.max(...ys) - y0 };
  }

  fit2d() { this.vp.fit(); }

  floorResult(id) { return this.result?.floors.find((f) => f.id === id) || null; }

  render2d() {
    if (!this.layer) return;
    const { heat, rooms } = this.layer;
    heat.replaceChildren();
    rooms.replaceChildren();
    const fr = this.floorResult(this.floor.id);
    if (fr) {
      const g = fr.grid;
      el('image', { href: fr.overlay, x: g.x, y: g.y, width: g.cols * g.cell_px, height: g.rows * g.cell_px, preserveAspectRatio: 'none', opacity: 0.9 }, heat);
      for (const poly of fr.contours) {
        el('polygon', { points: poly.map((q) => q.join(',')).join(' '), fill: 'none', stroke: VIOLET, 'stroke-width': 2.5, 'vector-effect': 'non-scaling-stroke' }, heat);
      }
      // Räume: Umriss, der gewählte zuletzt obenauf hervorgehoben
      const ordered = [...(fr.rooms || [])].sort(
        (a, b) => (`${this.floor.id}:${a.id}` === this.room ? 1 : 0) - (`${this.floor.id}:${b.id}` === this.room ? 1 : 0),
      );
      for (const rm of ordered) {
        const key = `${this.floor.id}:${rm.id}`;
        for (const pg of rm.contours) {
          el('polygon', { points: G.pointsAttr(pg), class: `room-outline${this.room === key ? ' current' : ''}`, 'data-room': key }, rooms);
        }
      }
    }
    this.renderOverlay();
  }

  renderOverlay() {
    if (!this.layer || this.mode !== '2d') return;
    this.ctx.status(undefined, `Zoom ${G.fmt(this.vp.s * 100, 0)} %`, this.floor.name);
    const { marks } = this.layer;
    marks.replaceChildren();
    const px = (n) => this.vp.px(n);
    const boxes = [];
    const fr = this.floorResult(this.floor.id);
    const aps = this.floor.devices.filter((x) => x.kind === 'ap');
    const apKey = this.result?.reading.ap;

    // Punkt-Symbole zuerst zeichnen und als Sperrflächen merken, damit keine Beschriftung sie überdeckt
    for (const d of aps) {
      const own = d.key === apKey;
      const g = el('g', { transform: `translate(${d.pos[0]} ${d.pos[1]})` }, marks);
      el('circle', { r: px(own ? 12 : 9), fill: own ? 'var(--dev-ap)' : 'var(--handle-fill)', stroke: 'var(--dev-ap)', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }, g);
      el('circle', { r: px(4), fill: own ? 'var(--handle-fill)' : 'var(--dev-ap)' }, g);
      const r = px(own ? 14 : 11);
      boxes.push({ x0: d.pos[0] - r, y0: d.pos[1] - r, x1: d.pos[0] + r, y1: d.pos[1] + r });
    }
    if (fr?.peak && this.result.best.floor_id === this.floor.id) {
      const g = el('g', { transform: `translate(${fr.peak[0]} ${fr.peak[1]})` }, marks);
      el('circle', { r: px(10), fill: 'none', stroke: VIOLET, 'stroke-width': 3, 'vector-effect': 'non-scaling-stroke' }, g);
      el('path', { d: `M${-px(16)},0H${px(16)}M0,${-px(16)}V${px(16)}`, stroke: VIOLET, 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }, g);
      const r = px(16);
      boxes.push({ x0: fr.peak[0] - r, y0: fr.peak[1] - r, x1: fr.peak[0] + r, y1: fr.peak[1] + r });
    }
    for (const fp of this.floor.found || []) {
      const g = el('g', { transform: `translate(${fp.pos[0]} ${fp.pos[1]})` }, marks);
      el('rect', { x: -px(7), y: -px(7), width: px(14), height: px(14), rx: px(3), fill: FOUND, stroke: 'var(--handle-fill)', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }, g);
      const r = px(10);
      boxes.push({ x0: fp.pos[0] - r, y0: fp.pos[1] - r, x1: fp.pos[0] + r, y1: fp.pos[1] + r });
    }

    // Beschriftungen der Zugangspunkte und Fundorte überlappungsfrei platzieren
    for (const d of aps) {
      const own = d.key === apKey;
      const t = el('text', { x: d.pos[0] + px(14), y: d.pos[1] + px(4), class: 'device-label', 'font-size': px(13) }, marks);
      t.textContent = own ? `${d.label} (verbunden)` : d.label;
      const tw = t.getComputedTextLength?.() || t.textContent.length * px(7.4);
      const ty = placeSideLabel(boxes, d.pos[0] + px(14), d.pos[1] + px(4), tw, px(15), px);
      t.setAttribute('y', ty);
    }
    if (this.vp.s >= 0.5) {
      for (const fp of this.floor.found || []) {
        const t = el('text', { x: fp.pos[0] + px(11), y: fp.pos[1] + px(4), class: 'device-label', 'font-size': px(11) }, marks);
        t.textContent = `✓ ${fp.label || ''}`;
        const tw = t.getComputedTextLength?.() || t.textContent.length * px(6.5);
        const ty = placeSideLabel(boxes, fp.pos[0] + px(11), fp.pos[1] + px(4), tw, px(13), px);
        t.setAttribute('y', ty);
      }
    }

    // Raumnamen mit Prozenten: gewählten Raum und höchste Werte zuerst platzieren, gewählten obenauf zeichnen
    const roomsShown = (fr?.rooms || [])
      .filter((rm) => rm.share >= 1 || `${this.floor.id}:${rm.id}` === this.room)
      .sort((a, b) => {
        const ca = `${this.floor.id}:${a.id}` === this.room ? 1 : 0;
        const cb = `${this.floor.id}:${b.id}` === this.room ? 1 : 0;
        return cb - ca || b.share - a.share;
      });
    let currentLabel = null;
    for (const rm of roomsShown) {
      const key = `${this.floor.id}:${rm.id}`;
      const isCurrent = key === this.room;
      const g = el('g', { class: `room-label-group${isCurrent ? ' current' : ''}` }, marks);
      const pill = el('rect', { class: 'room-label-pill', rx: px(5), ry: px(5) }, g);
      const t = el('text', { x: 0, y: 0, class: 'room-label', 'font-size': px(12.5) }, g);
      t.textContent = `${rm.name} · ${rm.share} %`;
      const tw = t.getComputedTextLength?.() || t.textContent.length * px(7.4);
      const w = tw + px(14);
      const h = px(20);
      const [cx, cy] = G.placeRoomLabel(boxes, rm, w, h, px);
      pill.setAttribute('x', cx - w / 2);
      pill.setAttribute('y', cy - h / 2);
      pill.setAttribute('width', w);
      pill.setAttribute('height', h);
      t.setAttribute('x', cx);
      t.setAttribute('y', cy);
      if (isCurrent) currentLabel = g;
    }
    if (currentLabel) marks.appendChild(currentLabel);

    if (this.foundPos) {
      const g = el('g', { transform: `translate(${this.foundPos[0]} ${this.foundPos[1]})`, class: 'found-new' }, marks);
      el('circle', { r: px(13), fill: 'var(--locate-found-fill)', stroke: FOUND, 'stroke-width': 3, 'vector-effect': 'non-scaling-stroke' }, g);
      el('circle', { r: px(4), fill: FOUND }, g);
    }
  }

  down(e) {
    return 'pan';
  }

  // --- 3D: Stockwerke als Ebenen im Raum (CSS-3D), im Gebäudesystem ausgerichtet -------------------

  bind3d() {
    let drag = null;
    this.scene.addEventListener('pointerdown', (e) => {
      drag = { x: e.clientX, y: e.clientY, rx: this.rot.x, rz: this.rot.z, moved: false };
      this.scene.setPointerCapture?.(e.pointerId);
    });
    this.scene.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (Math.hypot(dx, dy) > TAP_PX) drag.moved = true;
      if (!drag.moved) return;
      this.rot.z = drag.rz + dx * 0.35;
      this.rot.x = Math.max(0, Math.min(85, drag.rx - dy * 0.3));
      if (this.stack) this.stack.style.transform = this.sceneTransform();
    });
    const end = (e) => {
      if (drag && !drag.moved) {
        const hit = document.elementsFromPoint(e.clientX, e.clientY).find((n) => n.dataset?.floor);
        if (hit) this.setFloor(this.floors.find((f) => f.id === hit.dataset.floor), true);
      }
      drag = null;
    };
    this.scene.addEventListener('pointerup', end);
    this.scene.addEventListener('pointercancel', () => { drag = null; });
  }

  sceneTransform() {
    return `rotateX(${this.rot.x}deg) rotateZ(${this.rot.z}deg)`;
  }

  reset3d() {
    this.rot = { x: 56, z: -30 };
    if (this.stack) this.stack.style.transform = this.sceneTransform();
  }

  render3d() {
    const box = this.scene.getBoundingClientRect();
    this.scene.replaceChildren();
    if (!this.floors.length || !box.width) return;
    // Hausumriss je Stockwerk (Wände) im Gebäudesystem -> gemeinsamer Maßstab
    const items = this.floors.map((f) => ({ f, b: this.wallsBox(f) || { x: 0, y: 0, w: f.image_w, h: f.image_h } }));
    const corners = items.flatMap(({ f, b }) => [[b.x, b.y], [b.x + b.w, b.y], [b.x, b.y + b.h], [b.x + b.w, b.y + b.h]].map((p) => toM(f, p)));
    const xs = corners.map((p) => p[0]);
    const ys = corners.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1);
    const levels = this.floors.map((f) => f.level);
    const lo = Math.min(...levels);
    const hi = Math.max(...levels);
    const S = Math.min(box.width * 0.62, box.height * (hi > lo ? 0.5 : 0.75)) / span;   // CSS-px je Meter
    const dz = FLOOR_HEIGHT_M * Z_STRETCH * S;
    const stack = document.createElement('div');
    stack.className = 'stack3d';
    stack.style.transform = this.sceneTransform();
    this.scene.appendChild(stack);
    this.stack = stack;
    const best = this.result?.best.floor_id;
    for (const { f, b } of items) {
      const k = S / f.scale.px_per_m;        // CSS-px je Bildpixel
      const t = f.transform;
      const z = (f.level - (lo + hi) / 2) * dz;
      const plate = document.createElement('div');
      plate.className = `floor3d${f.id === best ? ' best' : ''}`;
      plate.dataset.floor = f.id;
      plate.style.width = `${b.w}px`;
      plate.style.height = `${b.h}px`;
      plate.style.transform = `translate3d(${(t.dx_m - cx) * S}px, ${(t.dy_m - cy) * S}px, ${z}px) rotate(${t.rot_deg}deg) scale(${k}) translate(${b.x}px, ${b.y}px)`;
      const inner = document.createElement('div');
      inner.className = 'floor3d-inner';
      inner.style.transform = `translate(${-b.x}px, ${-b.y}px)`;
      inner.style.width = `${f.image_w}px`;
      inner.style.height = `${f.image_h}px`;
      plate.appendChild(inner);
      const img = document.createElement('img');
      img.src = api.floorImageUrl(f);
      img.alt = '';
      img.draggable = false;
      img.width = f.image_w;
      img.height = f.image_h;
      inner.appendChild(img);
      const fr = this.floorResult(f.id);
      if (fr) {
        const g = fr.grid;
        const ov = document.createElement('img');
        ov.src = fr.overlay;
        ov.alt = '';
        ov.draggable = false;
        ov.className = 'overlay3d';
        Object.assign(ov.style, { left: `${g.x}px`, top: `${g.y}px`, width: `${g.cols * g.cell_px}px`, height: `${g.rows * g.cell_px}px` });
        inner.appendChild(ov);
      }
      const svg = el('svg', { width: f.image_w, height: f.image_h, viewBox: `0 0 ${f.image_w} ${f.image_h}`, class: 'marks3d' });
      inner.appendChild(svg);
      const u = 1 / k;                         // 1 CSS-px in Bildpixeln
      for (const wl of f.walls) {
        el('line', { x1: wl.a[0], y1: wl.a[1], x2: wl.b[0], y2: wl.b[1], stroke: 'var(--wall-map)', 'stroke-width': Math.max(wl.thickness_px, 1.2 * u), 'stroke-opacity': 0.55 }, svg);
      }
      for (const poly of fr?.contours || []) {
        el('polygon', { points: poly.map((q) => q.join(',')).join(' '), fill: 'none', stroke: VIOLET, 'stroke-width': 2.5 * u }, svg);
      }
      for (const d of f.devices.filter((x) => x.kind === 'ap')) {
        const own = d.key === this.result?.reading.ap;
        el('circle', { cx: d.pos[0], cy: d.pos[1], r: (own ? 7 : 5) * u, fill: own ? 'var(--dev-ap)' : 'var(--handle-fill)', stroke: 'var(--dev-ap)', 'stroke-width': 2 * u }, svg);
      }
      if (fr?.peak && best === f.id) {
        el('circle', { cx: fr.peak[0], cy: fr.peak[1], r: 7 * u, fill: 'none', stroke: VIOLET, 'stroke-width': 3 * u }, svg);
      }
      for (const fp of f.found || []) {
        el('rect', { x: fp.pos[0] - 5 * u, y: fp.pos[1] - 5 * u, width: 10 * u, height: 10 * u, fill: FOUND, stroke: 'var(--handle-fill)', 'stroke-width': 1.5 * u }, svg);
      }
      const label = document.createElement('div');
      label.className = 'floor3d-label';
      label.style.transform = `translate(${b.x}px, ${b.y}px) scale(${1 / k})`;   // in normaler Schriftgröße
      label.textContent = fr ? `${f.name} · ${fr.share} %` : f.name;
      inner.appendChild(label);
      stack.appendChild(plate);
    }
  }
}

// --- Hilfen für überlappungsfreie Beschriftungen im 2D-Plan -------------------------------

function placeSideLabel(boxes, x, baseY, w, h, px) {
  let best = { ty: baseY, box: { x0: x - px(2), y0: baseY - h + px(3), x1: x + w + px(2), y1: baseY + px(3) }, area: Infinity };
  for (const k of [0, 1, -1, 2, -2, 3, -3, 4, -4]) {
    const ty = baseY + k * px(16);
    const box = { x0: x - px(2), y0: ty - h + px(3), x1: x + w + px(2), y1: ty + px(3) };
    const area = boxes.reduce((s, o) => s + G.overlapArea(box, o), 0);
    if (area === 0) {
      boxes.push(box);
      return ty;
    }
    if (area < best.area) best = { ty, box, area };
  }
  boxes.push(best.box);
  return best.ty;
}
