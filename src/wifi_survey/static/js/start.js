// Ansicht „Start“: geführter Ablauf vom Plan bis zur Auswertung, mit dem Stand des Projekts je Schritt
// (GET api/progress). Der nächste offene Schritt ist hervorgehoben und führt direkt an die richtige Stelle.

import { api } from './api.js';
import { section, div, button } from './plans.js';

const TEXTS = {
  title: 'In wenigen Schritten zur WLAN-Karte',
  leadEmpty: 'Starte mit deinem eigenen Grundriss oder probiere zuerst das Beispielhaus aus.',
  leadProject: 'Grundriss hochladen, Wände korrigieren, Zugangspunkte setzen. Messungen machen die Karte genauer.',
  ownTitle: 'Eigenes Haus',
  ownBody: 'Grundriss (PDF oder Bild) hochladen und Wände automatisch erkennen lassen.',
  ownBtn: 'Plan hochladen',
  demoTitle: 'Beispielhaus',
  demoBody: 'Fertiges Haus mit zwei Stockwerken, Auswertung und Suche – ohne eigenen Plan.',
  demoBtn: 'Beispielhaus laden',
  demoActive: 'Beispielhaus aktiv: zwei Stockwerke, Router, Repeater und Messwerte zum Ausprobieren.',
  demoEnd: 'Beispiel beenden und eigenes Haus anlegen',
  demoConfirm: 'Beispiel beenden? Das Projekt ist danach leer.',
  stepsEmptyHead: 'So entsteht deine Karte',
};

export class StartView {
  constructor(ctx) {
    this.ctx = ctx;
  }

  async mount() {
    this.ctx.svg.style.display = 'none';
    this.page = document.createElement('div');
    this.page.id = 'startpage';
    this.ctx.svg.parentElement.appendChild(this.page);
    this.renderPanel(null);
    try {
      this.res = await api.progress();
    } catch (e) {
      div(this.page, 'callout', e.message);
      return;
    }
    this.render();
    this.renderPanel(this.res);
  }

  async unmount() {
    this.page?.remove();
    this.ctx.svg.style.display = '';
  }

  render() {
    const p = this.page;
    const pr = this.ctx.project;
    const empty = Boolean(pr && !pr.plans.length && !pr.floors.length);
    p.replaceChildren();
    const h = document.createElement('h1');
    h.textContent = TEXTS.title;
    p.appendChild(h);
    div(p, 'muted', empty ? TEXTS.leadEmpty : TEXTS.leadProject);
    this.renderDemo(p, empty);
    if (empty) div(p, 'start-steps-head', TEXTS.stepsEmptyHead);
    const list = document.createElement('ol');
    list.className = 'steps';
    p.appendChild(list);
    const next = this.res.steps.find((x) => x.status === 'todo');
    for (const st of this.res.steps) {
      const li = document.createElement('li');
      li.className = `step ${st.status}${st === next ? ' next' : ''}`;
      li.dataset.step = st.id;
      list.appendChild(li);
      div(li, 'step-mark', st.status === 'done' ? '✓' : '');
      const body = div(li, 'step-body');
      const head = div(body, 'step-title', st.title);
      if (st.status === 'optional') head.insertAdjacentHTML('beforeend', ' <span class="badge">optional</span>');
      div(body, 'small', st.detail);
      if (st.link) {
        const b = button(body, st.action || 'Öffnen', () => this.ctx.navigate(st.link));
        if (st === next) b.classList.add('primary');
      }
    }
  }

  // Beispielhaus (Paket A17) und klarer Zweifach-Einstieg (Paket A22 M2)
  renderDemo(p, empty) {
    const { ctx } = this;
    const pr = ctx.project;
    if (pr?.demo) {
      const box = div(p, 'callout demo-box');
      div(box, '', TEXTS.demoActive);
      button(box, TEXTS.demoEnd, async () => {
        if (!confirm(TEXTS.demoConfirm)) return;
        try {
          await api.demoEnd();
          await ctx.refreshProject();
          ctx.navigate('#/start');
        } catch (e) {
          ctx.toast(e.message, 'error');
        }
      });
    } else if (empty) {
      const grid = div(p, 'start-choices');
      const own = div(grid, 'start-choice main');
      div(own, 'start-choice-title', TEXTS.ownTitle);
      div(own, 'start-choice-body', TEXTS.ownBody);
      button(own, TEXTS.ownBtn, () => ctx.navigate('#/plaene')).classList.add('primary');

      const demo = div(grid, 'start-choice demo-box');
      div(demo, 'start-choice-title', TEXTS.demoTitle);
      div(demo, 'start-choice-body', TEXTS.demoBody);
      const b = button(demo, TEXTS.demoBtn, async () => {
        b.disabled = true;
        try {
          await api.demoLoad();
          await ctx.refreshProject();
          ctx.navigate('#/auswertung');
        } catch (e) {
          b.disabled = false;
          ctx.toast(e.message, 'error');
        }
      });
    }
  }

  renderPanel(res) {
    const p = this.ctx.panel;
    p.replaceChildren();
    const s = section(p, 'Start');
    if (!res) { div(s, 'small muted', 'Lade Stand …'); return; }
    const required = res.steps.filter((x) => !['devices', 'measure', 'evaluate'].includes(x.id));
    const total = required.length;
    const done = required.filter((x) => x.status === 'done').length;
    div(s, '', res.todo ? `${done} von ${total} Pflichtschritten erledigt.` : 'Alle Pflichtschritte erledigt.');
    const next = res.steps.find((x) => x.status === 'todo');
    if (next) {
      div(s, 'small', `Als Nächstes: ${next.title}.`);
      if (next.link) button(s, next.action || 'Öffnen', () => this.ctx.navigate(next.link)).classList.add('primary');
    }
    div(s, 'small muted', 'Die Liste rechnet den Stand bei jedem Öffnen neu aus. Alle Ansichten bleiben über die Reiter oben erreichbar.');
  }
}
