// Ansicht „Messen“: Rundgang mit dem Handy. Auf dem Plan antippen, wo man steht, dann „Hier messen“.
// Die Android-App (window.WifiSurveyApp) liefert Signal und WLAN-Scan des Handys; der Server ordnet
// die Werte den Zugangspunkten zu. Im normalen Browser: Messpunkte ansehen, App herunterladen.

import { api } from './api.js';
import { el, Viewport, isTyping } from './viewport.js';
import * as G from './geom.js';
import { section, div, button } from './plans.js';
import { RATING_COLOR } from './evaluate.js';

const SCAN_WAIT_MS = 8000;   // so lange auf frische Scan-Ergebnisse warten
const TAP_PX = 10;           // weiter bewegt: Verschieben statt Antippen

const parse = (json) => { try { return JSON.parse(json); } catch { return null; } };
const bandOf = (f) => (f >= 2400 && f <= 2500 ? '2,4' : f >= 4900 && f <= 5900 ? '5' : f >= 5925 && f <= 7125 ? '6' : '?');
const bandLabel = (b) => (b === '2.4' ? '2,4' : b);
const rating = (v) => (v >= -60 ? 'gut' : v >= -70 ? 'ausreichend' : v >= -80 ? 'schwach' : 'kritisch');

export class SurveyView {
  constructor(ctx, floorId) {
    this.ctx = ctx;
    this.floorId = floorId;
    this.app = window.WifiSurveyApp || null;
    this.here = null;
    this.busy = false;
    this.live = null;
    this.aps = [];
    this.selected = null;
    this.last = null;
    this.scanDone = null;
  }

  async mount() {
    const floors = this.ctx.floorsSorted();
    this.floor = floors.find((f) => f.id === this.floorId) || floors.find((f) => f.level === 0) || floors[0];
    this.vp = new Viewport(this.ctx.svg, { onChange: () => this.renderOverlay() });
    this.vp.handler = this;
    this.keyHandler = (e) => { if (!isTyping(e) && (e.key === 'f' || e.key === 'F')) this.vp.fit(); };
    window.addEventListener('keydown', this.keyHandler);
    if (this.floor) {
      const w = this.vp.world;
      this.layer = { image: el('g', {}, w), walls: el('g', {}, w), points: el('g', {}, w), here: el('g', {}, w) };
      el('rect', { x: 0, y: 0, width: this.floor.image_w, height: this.floor.image_h, fill: 'var(--plan-paper)', class: 'plan-paper' }, this.layer.image);
      el('image', { href: api.floorImageUrl(this.floor), x: 0, y: 0, width: this.floor.image_w, height: this.floor.image_h, opacity: 0.5, class: 'plan-img' }, this.layer.image);
      for (const wl of this.floor.walls) {
        el('line', { x1: wl.a[0], y1: wl.a[1], x2: wl.b[0], y2: wl.b[1], stroke: 'var(--wall-map)', 'stroke-width': wl.thickness_px, 'stroke-opacity': 0.5 }, this.layer.walls);
      }
      this.vp.contentBox = { x: 0, y: 0, w: this.floor.image_w, h: this.floor.image_h };
      // Antippen erkennen: Finger kaum bewegt (Verschieben und Zoomen übernimmt der Viewport)
      this.onPointerDown = (e) => { this.tap = e.isPrimary ? { x: e.clientX, y: e.clientY, multi: false } : { ...this.tap, multi: true }; };
      this.onPointerUp = (e) => {
        const t = this.tap;
        this.tap = null;
        if (!t || t.multi || !e.isPrimary || Math.hypot(e.clientX - t.x, e.clientY - t.y) > TAP_PX) return;
        if (e.target.closest?.('[data-pt]')) return;
        this.here = this.vp.toWorld(e.clientX, e.clientY);
        this.selected = null;
        this.renderOverlay();
        this.renderPanel();
      };
      this.ctx.svg.addEventListener('pointerdown', this.onPointerDown);
      this.ctx.svg.addEventListener('pointerup', this.onPointerUp);
    }
    this.ctx.hint(this.app ? 'Auf den Plan tippen, wo du stehst, dann „Hier messen“. Zwei Finger: verschieben und zoomen.'
      : 'Messen geht mit der Android-App. Hier im Browser siehst du die Messpunkte.');
    try {
      this.aps = (await api.surveyAps()).aps;
    } catch {
      this.aps = [];
    }
    if (this.app) {
      this.app.keepAwake?.(true);
      this.onScan = (e) => this.scanDone?.(e.detail);
      this.onPermission = () => this.renderPanel();
      this.onFindable = () => { this.findableBusy = false; this.renderPanel(); };
      window.addEventListener('wifiscan', this.onScan);
      window.addEventListener('wifipermission', this.onPermission);
      window.addEventListener('findable', this.onFindable);
      this.timer = setInterval(() => this.updateLive(), 2000);
      this.updateLive();
    }
    this.renderOverlay();
    this.renderPanel();
    requestAnimationFrame(() => this.vp.fit());
  }

  async unmount() {
    clearInterval(this.timer);
    window.removeEventListener('keydown', this.keyHandler);
    window.removeEventListener('wifiscan', this.onScan);
    window.removeEventListener('wifipermission', this.onPermission);
    window.removeEventListener('findable', this.onFindable);
    this.ctx.svg.removeEventListener('pointerdown', this.onPointerDown);
    this.ctx.svg.removeEventListener('pointerup', this.onPointerUp);
    this.app?.keepAwake?.(false);
    this.vp.destroy();
  }

  // --- Zeichenfläche ----------------------------------------------------------------------

  down(e) {
    const g = e.target.closest?.('[data-pt]');
    if (g) {
      this.selected = g.dataset.pt;
      this.renderOverlay();
      this.renderPanel();
      return true;
    }
    return 'pan';
  }

  hover(e, w) {
    if (!this.floor?.scale) return;
    const ppm = this.floor.scale.px_per_m;
    this.ctx.status(`x ${G.fmt(w[0] / ppm, 2)} m · y ${G.fmt(w[1] / ppm, 2)} m`);
  }

  renderOverlay() {
    if (!this.layer) return;
    this.ctx.status(undefined, `Zoom ${G.fmt(this.vp.s * 100, 0)} %`);
    const px = (n) => this.vp.px(n);
    const { points, here } = this.layer;
    points.replaceChildren();
    here.replaceChildren();
    (this.floor.survey || []).forEach((p, i) => {
      const best = this.best(p);
      const g = el('g', { transform: `translate(${p.pos[0]} ${p.pos[1]})`, 'data-pt': p.id, style: 'cursor:pointer' }, points);
      if (this.selected === p.id) el('circle', { r: px(15), class: 'device-ring' }, g);
      el('rect', { x: -px(8), y: -px(8), width: px(16), height: px(16), transform: 'rotate(45)', fill: best ? RATING_COLOR[rating(best.rssi)] : 'var(--dev-unmeasured)',
        stroke: 'var(--handle-fill)', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }, g);
      if (this.vp.s >= 0.45 || this.selected === p.id) {
        const t = el('text', { x: px(12), y: px(4), class: 'device-label', 'font-size': px(12) }, g);
        t.textContent = `${i + 1}${best ? ` ${best.rssi}` : ''}`;
      }
    });
    if (this.here) {
      const g = el('g', { transform: `translate(${this.here[0]} ${this.here[1]})` }, here);
      el('circle', { r: px(16), fill: 'var(--ring-fill)', stroke: 'var(--accent)', 'stroke-width': 3, 'vector-effect': 'non-scaling-stroke' }, g);
      el('circle', { r: px(3), fill: 'var(--accent)' }, g);
    }
  }

  best(p) {
    let best = null;
    for (const [key, bands] of Object.entries(p.aps || {})) {
      for (const [band, rssi] of Object.entries(bands)) {
        if (!best || rssi > best.rssi) best = { key, band, rssi };
      }
    }
    return best;
  }

  apLabel(key) {
    return this.aps.find((a) => a.key === key)?.label || key || 'unbekannt';
  }

  apByBssid(bssid) {
    const b = (bssid || '').toLowerCase().replace(/[^0-9a-f]/g, '');
    if (b.length !== 12) return null;
    return this.aps.find((a) => a.bssids.includes(b)) || this.aps.find((a) => a.bssids.some((c) => c.slice(0, 10) === b.slice(0, 10))) || null;
  }

  // --- Messen -----------------------------------------------------------------------------

  updateLive() {
    this.live = parse(this.app.connection());
    if (!this.liveEl) return;
    const c = this.live;
    if (!c || c.rssi <= -127) {
      this.liveEl.textContent = 'Nicht mit einem WLAN verbunden.';
      return;
    }
    const ap = this.apByBssid(c.bssid);
    this.liveEl.textContent = `Jetzt: ${ap ? ap.label : 'unbekannter Zugangspunkt'} · ${bandOf(c.frequency)} GHz · ${c.rssi} dBm · ${c.link_mbps} Mbit/s`;
  }

  async measure(btn) {
    if (!this.here || this.busy) return;
    this.busy = true;
    btn.disabled = true;
    btn.textContent = 'Messe … (WLAN-Scan)';
    const started = Boolean(this.app.startScan());
    let fresh = false;
    if (started) {
      fresh = await new Promise((resolve) => {
        const timeout = setTimeout(() => { this.scanDone = null; resolve(false); }, SCAN_WAIT_MS);
        this.scanDone = (detail) => { clearTimeout(timeout); this.scanDone = null; resolve(Boolean(detail?.updated)); };
      });
    }
    const model = (navigator.userAgent.match(/Android [\d.]+; ([^;)]+)/) || [])[1] || '';
    try {
      const point = await api.addSurveyPoint(this.floor.id, {
        pos: this.here.map((v) => Math.round(v * 10) / 10),
        connection: parse(this.app.connection()),
        scan: parse(this.app.scanResults()) || [],
        device: model.trim().slice(0, 120),
      });
      this.floor.survey = [...(this.floor.survey || []), point];
      this.last = { point, fresh, started };
      this.here = null;
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
    this.busy = false;
    this.renderOverlay();
    this.renderPanel();
  }

  async remove(id) {
    try {
      await api.deleteSurveyPoint(this.floor.id, id);
      this.floor.survey = this.floor.survey.filter((p) => p.id !== id);
      if (this.selected === id) this.selected = null;
      if (this.last?.point.id === id) this.last = null;
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
    this.renderOverlay();
    this.renderPanel();
  }

  // --- Panel ------------------------------------------------------------------------------

  renderPanel() {
    const { ctx } = this;
    const p = ctx.panel;
    const scroll = p.scrollTop;
    p.replaceChildren();
    const head = section(p, 'Messen mit dem Handy');
    const floors = ctx.floorsSorted();
    if (!floors.length) { div(head, 'muted', 'Noch keine Stockwerke.'); return; }
    const sel = document.createElement('select');
    for (const f of floors) sel.appendChild(new Option(f.name, f.id, false, f.id === this.floor.id));
    sel.addEventListener('change', () => ctx.navigate(`#/messen/${sel.value}`));
    head.appendChild(sel);

    if (!this.app) {
      div(head, 'callout', 'Zum Messen brauchst du die Android-App. Sie zeigt diese Oberfläche und liefert die WLAN-Werte des Handys: '
        + 'Signal des verbundenen Zugangspunkts und den Scan aller Zugangspunkte auf 2,4 und 5 GHz.');
      const a = document.createElement('a');
      a.href = 'app/wifi-survey.apk';
      a.textContent = 'Android-App herunterladen';
      a.className = 'button-link';
      head.appendChild(a);
      div(head, 'small muted', 'Bei der Installation „Apps aus unbekannten Quellen“ erlauben. iPhones geben die WLAN-Werte nicht an Apps heraus.');
      this.renderServerAddress(div(head, 'small'));
    } else {
      this.renderApp(head);
      this.renderOwn(p);
      if (this.app.findable) this.renderFindable(p);
    }
    this.renderPoints(p);
    p.scrollTop = scroll;
  }

  // Eigene Zugangspunkte (ohne FRITZ!Box-Messlauf): Netze aus dem Scan des Handys zuordnen. Gespeichert werden
  // nur die Adressen (BSSID) zugeordneter Netze; Netznamen zeigt nur das Handy an.
  renderOwn(p) {
    const own = this.aps.filter((a) => a.manual);
    if (!own.length) return;
    const s = section(p, 'Eigene Zugangspunkte');
    div(s, 'small muted', 'Netze aus dem Scan des Handys dem passenden Router oder Repeater zuordnen. Danach zählen Messpunkte auch für ihn. '
      + 'Gespeichert wird nur die Adresse (BSSID) zugeordneter Netze.');
    for (const a of own) {
      div(s, 'small', `${a.label}${a.floor ? ` (${a.floor})` : ''}: `
        + `${a.bssids.length ? `${a.bssids.length} ${a.bssids.length === 1 ? 'Netz' : 'Netze'} zugeordnet` : 'noch kein Netz zugeordnet'}`);
    }
    const norm = (b) => (b || '').toLowerCase().replace(/[^0-9a-f]/g, '');
    const groups = new Map();   // je Gerät (erste fünf Bytes der Adresse)
    for (const r of parse(this.app.scanResults()) || []) {
      const b = norm(r.bssid);
      if (b.length !== 12 || b === '020000000000' || !(r.rssi < 0 && r.rssi > -110)) continue;
      const known = this.apByBssid(b);
      if (known && !known.manual) continue;          // gehört zum Mesh aus dem Messlauf
      const k = b.slice(0, 10);
      const g = groups.get(k) || { bssids: new Set(), ssids: new Set(), bands: new Set(), rssi: -999, owner: null };
      g.bssids.add(b);
      if (r.ssid) g.ssids.add(r.ssid);
      g.bands.add(bandOf(r.frequency));
      g.rssi = Math.max(g.rssi, r.rssi);
      if (known?.manual) g.owner = known.key;
      groups.set(k, g);
    }
    const list = [...groups.values()].sort((x, y) => y.rssi - x.rssi).slice(0, 12);
    if (!list.length) div(s, 'small muted', 'Keine weiteren Netze im letzten Scan.');
    for (const g of list) {
      const row = div(s, 'own-net');
      div(row, 'small', `${[...g.ssids].join(', ') || '(ohne Namen)'} · ${[...g.bands].sort().join(' / ')} GHz · ${g.rssi} dBm`);
      const sel = document.createElement('select');
      sel.appendChild(new Option('nicht meins', ''));
      for (const a of own) sel.appendChild(new Option(a.label, a.key, false, a.key === g.owner));
      sel.addEventListener('change', () => this.assign([...g.bssids], g.owner, sel.value || null));
      row.appendChild(sel);
    }
    const b = button(s, 'Neu scannen', async () => {
      b.disabled = true;
      b.textContent = 'Scanne …';
      if (this.app.startScan()) {
        await new Promise((resolve) => {
          const t = setTimeout(() => { this.scanDone = null; resolve(); }, SCAN_WAIT_MS);
          this.scanDone = () => { clearTimeout(t); this.scanDone = null; resolve(); };
        });
      }
      this.renderPanel();
    });
  }

  async assign(bssids, from, to) {
    const prefix = bssids[0].slice(0, 10);
    try {
      if (from && from !== to) {
        const a = this.aps.find((x) => x.key === from);
        await api.putBssids(from, a.bssids.filter((b) => b.slice(0, 10) !== prefix));
      }
      if (to) {
        const a = this.aps.find((x) => x.key === to);
        await api.putBssids(to, [...new Set([...a.bssids, ...bssids])]);
      }
      this.aps = (await api.surveyAps()).aps;
      this.ctx.toast(to ? `Zugeordnet: ${this.apLabel(to)}` : 'Zuordnung entfernt', 'ok');
    } catch (e) {
      this.ctx.toast(e.message, 'error');
    }
    this.renderPanel();
  }

  // Adresse, die man in der App einträgt. Hinter dem Ingress von Home Assistant gilt die Adresse der
  // Seite nicht (sie braucht die HA-Anmeldung), sondern nur ein freigegebener Port der HA-App.
  async renderServerAddress(node) {
    let info = {};
    try { info = await api.info(); } catch { /* ältere Server ohne /api/info */ }
    const here = location.href.split('#')[0].replace(/index\.html$/, '').replace(/\/$/, '');
    const url = info.direct_url || (info.ingress ? null : here);
    if (url) {
      node.append('Server-Adresse für die App: ');
      const code = document.createElement('code');
      code.textContent = url;
      node.append(code);
    } else {
      node.className = 'small callout';
      node.textContent = 'Die App braucht eine direkte Adresse im Heimnetz. In Home Assistant bei der App „WiFi Survey“ '
        + 'unter Konfiguration → Netzwerk einen Port eintragen (z. B. 8770); danach steht die Adresse hier.';
    }
  }

  renderApp(s) {
    const perm = parse(this.app.permissions()) || {};
    if (!perm.location || !perm.nearby) {
      div(s, 'callout', 'Android gibt WLAN-Scans nur mit der Berechtigung „Standort“ (und „Geräte in der Nähe“) heraus. Die App nutzt sie nur zum Messen.');
      button(s, 'Berechtigung erteilen', () => this.app.requestPermissions()).className = 'primary';
    }
    if (perm.location_enabled === false) {
      div(s, 'callout', 'Der Standort ist ausgeschaltet; ohne ihn liefert Android keine Scan-Ergebnisse.');
      button(s, 'Standort einschalten', () => this.app.openLocationSettings());
    }
    if (perm.wifi_enabled === false) div(s, 'callout', 'WLAN ist ausgeschaltet.');
    this.liveEl = div(s, 'small', '');
    this.updateLive();
    div(s, 'small muted', this.here ? 'Position gesetzt. Kurz stehen bleiben, dann messen.' : 'Auf den Plan tippen, wo du gerade stehst.');
    const b = button(s, 'Hier messen', () => this.measure(b));
    b.className = 'primary big';
    b.disabled = !this.here || this.busy;
    if (this.last) {
      const { point, fresh, started } = this.last;
      const parts = Object.entries(point.aps).map(([key, bands]) => `${this.apLabel(key)} ${Object.entries(bands)
        .map(([band, v]) => `${bandLabel(band)} GHz ${v}`).join(', ')}`);
      div(s, 'finding', `Gespeichert: ${parts.join(' · ') || 'nur Verbindung'}. Fremde Netze: ${point.others.reduce((n, o) => n + o.count, 0)}.`);
      if (!started || !fresh) {
        div(s, 'finding warn', 'Android hat den Scan gedrosselt (höchstens 4 Scans in 2 Minuten). Gemessen ist sicher nur der verbundene Zugangspunkt. '
          + 'Abhilfe: Entwickleroptionen → „WLAN-Scan-Drosselung“ ausschalten.');
      }
    }
    const row = div(s, 'row');
    button(row, 'Server ändern', () => this.app.changeServer());
    div(row, 'small muted', `App ${this.app.version?.() || ''}`);
  }

  // Hintergrundmodus „findbar“ (Entscheidung 0010): Das ruhende Handy meldet einen WLAN-Scan, damit „Suchen“
  // es über alle Zugangspunkte findet statt nur über den einen, an dem es hängt.
  renderFindable(p) {
    const st = parse(this.app.findable()) || {};
    const s = section(p, 'Dieses Handy findbar machen');
    div(s, 'small muted', 'Im Hintergrund prüft die App etwa alle 15 Minuten, ob das Handy im WLAN des Hauses ruht: Bildschirm aus '
      + 'oder am Ladekabel, dazu zweimal derselbe Zugangspunkt mit fast gleichem Signal. Nur dann meldet sie einen WLAN-Scan, und nur, '
      + 'wenn sich seit der letzten Meldung etwas geändert hat. „Suchen“ findet das Handy damit über alle Zugangspunkte. '
      + 'Kein GPS, kein Bluetooth; gemeldet werden nur die Zugangspunkte des Hauses, der Server behält nur die letzte Meldung.');
    if (st.enabled && !st.background_location) {
      div(s, 'callout', 'Android gibt WLAN-Werte im Hintergrund nur mit Standort „Immer zulassen“ heraus. Ohne diese Freigabe kann die App nicht melden.');
      button(s, 'Standort „Immer zulassen“', () => this.app.requestBackgroundLocation()).className = 'primary';
    }
    const row = div(s, 'row');
    const toggle = button(row, st.enabled ? 'Ausschalten' : 'Einschalten', () => this.setFindable(!st.enabled));
    if (!st.enabled) toggle.className = 'primary';
    const now = button(row, this.findableBusy ? 'Melde …' : 'Jetzt melden', () => {
      this.findableBusy = true;
      this.app.findableNow();
      this.renderPanel();
    });
    now.disabled = !!this.findableBusy;
    now.title = 'Sofort einen Scan melden, ohne auf die Ruhe zu warten (zum Ausprobieren)';
    const t = (ms) => (ms ? new Date(ms).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '');
    div(s, 'small', `${st.enabled ? 'Ein' : 'Aus'}${st.status ? ` · zuletzt: ${st.status}${st.status_t ? ` (${t(st.status_t)})` : ''}` : ''}`);
    if (st.report_t) div(s, 'small muted', `Letzte Meldung: ${t(st.report_t)}${st.report_name ? `, auf dem Server als „${st.report_name}“` : ''}.`);
  }

  setFindable(on) {
    if (on && !(parse(this.app.findable()) || {}).background_location) this.app.requestBackgroundLocation();
    this.app.setFindable(on);
    this.renderPanel();
  }

  renderPoints(p) {
    const s = section(p, `Messpunkte auf ${this.floor.name} (${(this.floor.survey || []).length})`);
    const pts = this.floor.survey || [];
    if (!pts.length) { div(s, 'small muted', 'Noch keine Messpunkte.'); return; }
    pts.forEach((pt, i) => {
      const best = this.best(pt);
      const row = div(s, `ev-device${this.selected === pt.id ? ' selected' : ''}`);
      const top = div(row, 'row');
      const dot = div(top, 'device-dot');
      dot.style.background = best ? RATING_COLOR[rating(best.rssi)] : 'var(--dev-unmeasured)';
      const t = div(top, 'title', `Messpunkt ${i + 1}`);
      t.style.flex = '1';
      div(top, `rssi ${best ? rating(best.rssi) : ''}`, best ? `${best.rssi} dBm` : '–');
      const when = new Date(pt.t).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
      div(row, 'small muted', `${best ? `bester: ${this.apLabel(best.key)}, ${bandLabel(best.band)} GHz · ` : ''}${Object.keys(pt.aps).length} Zugangspunkte · ${when}`);
      if (this.selected === pt.id) button(row, 'Messpunkt löschen', () => this.remove(pt.id)).className = 'danger';
      row.addEventListener('click', () => {
        this.selected = pt.id;
        this.vp.centerOn(pt.pos, Math.max(this.vp.s, 0.9));
        this.renderOverlay();
        this.renderPanel();
      });
    });
    div(s, 'small muted', 'Die Werte fließen in die Eichung der Auswertung ein (2,4 GHz). 5-GHz-Werte werden gespeichert für die Auswertung je Band.');
  }
}
