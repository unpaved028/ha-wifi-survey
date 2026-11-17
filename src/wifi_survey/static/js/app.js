// Einstieg: lädt Projekt und Stammdaten, schaltet zwischen den Ansichten um (Hash-Routing).
//   #/start             geführter Ablauf mit dem Stand des Projekts (Standard für ein leeres Projekt)
//   #/plaene            Pläne hochladen, Stockwerke ausschneiden
//   #/stockwerk/<id>    Wände eines Stockwerks bearbeiten
//   #/ausrichten        Stockwerke übereinander ausrichten
//   #/auswertung/<id>   Ausleuchtung, Simulation, Empfehlung
//   #/messen/<id>       Rundgang mit dem Handy (Android-App)

import { api } from './api.js';
import { PlansView } from './plans.js';
import { FloorView } from './floor.js';
import { AlignView } from './align.js';
import { EvaluationView } from './evaluate.js';
import { SurveyView } from './survey.js';
import { LocateView } from './locate.js';
import { StartView } from './start.js';

const $ = (sel) => document.querySelector(sel);

const TEXTS = {
  closeHint: 'Tippen zum Schließen',
};

const ctx = {
  svg: $('#canvas'),
  panel: $('#panel'),
  hintEl: $('#hint'),
  project: null,
  materials: [],
  classes: [],
  view: null,

  async refreshProject() {
    ctx.project = await api.project();
    renderTabs();
    return ctx.project;
  },

  navigate(hash) {
    if (location.hash === hash) route();
    else location.hash = hash;
  },

  toast(msg, kind = '') {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = `toast ${kind}`;
    node.textContent = msg;
    node.title = TEXTS.closeHint;
    const timer = setTimeout(() => node.remove(), kind === 'error' ? 7000 : 3500);
    node.addEventListener('click', () => { clearTimeout(timer); node.remove(); });
    $('#toasts').appendChild(node);
  },

  hint(text) {
    if (!text) {
      ctx.hintEl.hidden = true;
      return;
    }
    // Einmal weggeklickte Hinweise bleiben in dieser Sitzung verborgen
    ctx.hintEl.hidden = sessionStorage.getItem('ws-hints-off') === '1';
    ctx.hintEl.textContent = text;
    ctx.hintEl.title = TEXTS.closeHint;
  },

  setSaveState(state, text) {
    const n = $('#savestate');
    n.className = `savestate ${state}`;
    n.textContent = text || { saved: 'Gespeichert', dirty: '● Ungespeichert', saving: 'Speichere …', error: 'Fehler beim Speichern' }[state] || '';
  },

  status(pos, zoom, info) {
    if (pos !== undefined) $('#status-pos').textContent = pos;
    if (zoom !== undefined) $('#status-zoom').textContent = zoom;
    if (info !== undefined) $('#status-info').textContent = info;
  },

  floorsSorted() {
    return [...(ctx.project?.floors || [])].sort((a, b) => a.level - b.level || a.name.localeCompare(b.name));
  },

  getTheme() {
    const v = localStorage.getItem('ws-theme');
    return ['auto', 'light', 'dark', 'classic'].includes(v) ? v : 'auto';
  },

  setTheme(pref) {
    const valid = ['auto', 'light', 'dark', 'classic'].includes(pref) ? pref : 'auto';
    localStorage.setItem('ws-theme', valid);
    applyTheme();
  },
};

const THEME_ICONS = {
  auto: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M12 3a9 9 0 0 0 0 18Z" fill="currentColor" fill-opacity=".3"/></svg>',
  light: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>',
  dark: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
  classic: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>',
  chevron: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
};

const THEME_OPTIONS = [
  ['auto', 'Automatisch'],
  ['light', 'Hell'],
  ['dark', 'Dunkel'],
  ['classic', 'Classic'],
];

function detectAutoTheme() {
  try {
    if (window.parent && window.parent !== window) {
      const ha = window.parent.document?.querySelector('home-assistant');
      if (typeof ha?.hass?.themes?.darkMode === 'boolean') {
        return ha.hass.themes.darkMode ? 'dark' : 'light';
      }
    }
  } catch { /* anderer Ursprung */ }
  try {
    const raw = localStorage.getItem('selectedTheme');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (typeof parsed?.dark === 'boolean') return parsed.dark ? 'dark' : 'light';
    }
  } catch { /* ungültiges JSON */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme() {
  const pref = ctx.getTheme();
  const resolved = pref === 'auto' ? detectAutoTheme() : pref;
  document.documentElement.dataset.themePref = pref;
  document.documentElement.dataset.theme = resolved;
  const btn = $('#theme-btn');
  const menu = $('#theme-menu');
  if (!btn || !menu) return;
  const label = THEME_OPTIONS.find(([k]) => k === pref)?.[1] || 'Automatisch';
  btn.innerHTML = `${THEME_ICONS[pref] || THEME_ICONS.auto}${THEME_ICONS.chevron}`;
  btn.title = `Darstellung: ${label}`;
  btn.setAttribute('aria-label', `Darstellung: ${label}`);
  for (const item of menu.querySelectorAll('.theme-item')) {
    const active = item.dataset.theme === pref;
    item.classList.toggle('active', active);
    item.setAttribute('aria-checked', String(active));
  }
}

function initThemePicker() {
  const btn = $('#theme-btn');
  const menu = $('#theme-menu');
  if (!btn || !menu) return;
  menu.replaceChildren();
  for (const [key, label] of THEME_OPTIONS) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'theme-item';
    item.role = 'menuitemradio';
    item.dataset.theme = key;
    item.innerHTML = `${THEME_ICONS[key]}<span>${label}</span>`;
    item.addEventListener('click', () => {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      ctx.setTheme(key);
    });
    menu.appendChild(item);
  }
  const close = () => {
    if (!menu.hidden) {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
    }
  };
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = menu.hidden;
    menu.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest?.('#theme-picker')) close();
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
    if (ctx.getTheme() === 'auto') applyTheme();
  });
  window.addEventListener('storage', (e) => {
    if (e.key === 'ws-theme' || e.key === 'selectedTheme') applyTheme();
  });
  try {
    if (window.parent && window.parent !== window && window.parent.document?.documentElement) {
      new MutationObserver(() => {
        if (ctx.getTheme() === 'auto') applyTheme();
      }).observe(window.parent.document.documentElement, { attributes: true, attributeFilter: ['style', 'class'] });
    }
  } catch { /* anderer Ursprung */ }
  applyTheme();
}

function renderTabs() {
  const tabs = $('#tabs');
  tabs.replaceChildren();
  const current = location.hash || defaultHash();
  const add = (href, label, title) => {
    const a = document.createElement('a');
    a.href = href;
    a.textContent = label;
    if (title) a.title = title;
    if (current === href || (href !== '#/plaene' && href !== '#/start' && current.startsWith(href))) a.classList.add('active');
    tabs.appendChild(a);
  };
  add('#/start', 'Start', 'Geführter Ablauf und Stand des Projekts');
  add('#/plaene', 'Pläne');
  for (const f of ctx.floorsSorted()) add(`#/stockwerk/${f.id}`, f.name, `Ebene ${f.level}`);
  if ((ctx.project?.floors || []).length > 1) add('#/ausrichten', 'Ausrichten');
  if ((ctx.project?.floors || []).length) add('#/auswertung', 'Auswertung');
  if ((ctx.project?.floors || []).length) add('#/messen', 'Messen');
  if ((ctx.project?.floors || []).length) add('#/suchen', 'Suchen');
  tabs.querySelector('a.active')?.scrollIntoView({ inline: 'nearest', block: 'nearest' });
}

// Ohne Plan beginnt man beim geführten Ablauf, sonst bei den Plänen
function defaultHash() {
  return ctx.project && !ctx.project.plans.length ? '#/start' : '#/plaene';
}

let routing = Promise.resolve();

function route() {
  routing = routing.then(doRoute).catch((e) => {
    console.error(e);
    ctx.toast(e.message || String(e), 'error');
  });
}

async function doRoute() {
  if (ctx.view) {
    await ctx.view.unmount();
    ctx.view = null;
  }
  ctx.panel.replaceChildren();
  ctx.hint('');
  ctx.status('', '', '');
  await ctx.refreshProject();
  const hash = location.hash || defaultHash();
  const m = hash.match(/^#\/stockwerk\/([\w-]+)/);
  if (m) {
    const floor = ctx.project.floors.find((f) => f.id === m[1]);
    if (!floor) {
      ctx.toast('Stockwerk nicht gefunden', 'error');
      ctx.navigate('#/plaene');
      return;
    }
    document.body.dataset.view = 'floor';
    ctx.view = new FloorView(ctx, floor);
  } else if (hash.startsWith('#/ausrichten')) {
    document.body.dataset.view = 'align';
    ctx.view = new AlignView(ctx);
  } else if (hash.startsWith('#/suchen')) {
    document.body.dataset.view = 'locate';
    ctx.view = new LocateView(ctx, hash.split('/')[2]);
  } else if (hash.startsWith('#/messen')) {
    document.body.dataset.view = 'survey';
    ctx.view = new SurveyView(ctx, hash.split('/')[2] || sessionStorage.getItem('ws-eval-floor'));
  } else if (hash.startsWith('#/start')) {
    document.body.dataset.view = 'start';
    ctx.view = new StartView(ctx);
  } else if (hash.startsWith('#/auswertung')) {
    document.body.dataset.view = 'evaluate';
    ctx.view = new EvaluationView(ctx, hash.split('/')[2] || sessionStorage.getItem('ws-eval-floor'));
  } else {
    document.body.dataset.view = 'plans';
    ctx.view = new PlansView(ctx);
  }
  await ctx.view.mount();
  if ((ctx.view instanceof EvaluationView || ctx.view instanceof SurveyView) && ctx.view.floor) sessionStorage.setItem('ws-eval-floor', ctx.view.floor.id);
  renderTabs();
}

window.addEventListener('hashchange', route);
ctx.hintEl.addEventListener('click', () => {
  ctx.hintEl.hidden = true;
  sessionStorage.setItem('ws-hints-off', '1');
});
window.addEventListener('beforeunload', (e) => {
  if (ctx.view?.isDirty?.()) {
    e.preventDefault();
    e.returnValue = '';
  }
});

async function init() {
  try {
    const [materials, classes] = await Promise.all([api.materials(), api.thicknessClasses()]);
    ctx.materials = materials;
    ctx.classes = classes.classes_cm;
  } catch (e) {
    ctx.toast(`Server nicht erreichbar: ${e.message}`, 'error');
    return;
  }
  ctx.setSaveState('saved', '');
  route();
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
}

window.wifiSurvey = ctx; // für Tests und Fehlersuche in der Konsole
initThemePicker();
init();
