// Zoom und Verschieben einer SVG-Zeichenfläche. Weltkoordinaten liegen in <g class="world">.
// Bedienung: Mausrad zoomt um den Mauszeiger, mittlere Maustaste oder Leertaste + Ziehen
// verschiebt, zwei Finger zoomen und verschieben. Alles andere geht an den Handler der Ansicht.

const SVG_NS = 'http://www.w3.org/2000/svg';

export function el(tag, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    node.setAttribute(k, v);
    if ((k === 'fill' || k === 'stroke') && typeof v === 'string' && v.includes('var(')) {
      node.style.setProperty(k, v);
    }
  }
  if (parent) parent.appendChild(node);
  return node;
}

export class Viewport {
  constructor(svg, { onChange } = {}) {
    this.svg = svg;
    this.onChange = onChange || (() => {});
    this.s = 1;
    this.tx = 0;
    this.ty = 0;
    this.world = el('g', { class: 'world' }, svg);
    this.handler = null;
    this.pointers = new Map();
    this.pan = null;
    this.pinch = null;
    this.space = false;
    this.contentBox = null;

    this._onWheel = (e) => this.wheel(e);
    this._onDown = (e) => this.down(e);
    this._onMove = (e) => this.move(e);
    this._onUp = (e) => this.up(e);
    this._onKeyDown = (e) => {
      if (e.code === 'Space' && !isTyping(e)) {
        this.space = true;
        svg.classList.add('tool-pan');
        e.preventDefault();
      }
    };
    this._onKeyUp = (e) => {
      if (e.code === 'Space') {
        this.space = false;
        svg.classList.remove('tool-pan');
      }
    };
    this._onResize = () => this.onChange(this);
    svg.addEventListener('wheel', this._onWheel, { passive: false });
    svg.addEventListener('pointerdown', this._onDown);
    svg.addEventListener('pointermove', this._onMove);
    svg.addEventListener('pointerup', this._onUp);
    svg.addEventListener('pointercancel', this._onUp);
    svg.addEventListener('contextmenu', (e) => e.preventDefault());
    window.addEventListener('keydown', this._onKeyDown);
    window.addEventListener('keyup', this._onKeyUp);
    window.addEventListener('resize', this._onResize);
  }

  destroy() {
    this.svg.removeEventListener('wheel', this._onWheel);
    this.svg.removeEventListener('pointerdown', this._onDown);
    this.svg.removeEventListener('pointermove', this._onMove);
    this.svg.removeEventListener('pointerup', this._onUp);
    this.svg.removeEventListener('pointercancel', this._onUp);
    window.removeEventListener('keydown', this._onKeyDown);
    window.removeEventListener('keyup', this._onKeyUp);
    window.removeEventListener('resize', this._onResize);
    this.svg.replaceChildren();
    this.svg.className.baseVal = '';
  }

  apply() {
    this.world.setAttribute('transform', `translate(${this.tx} ${this.ty}) scale(${this.s})`);
    this.onChange(this);
  }

  toWorld(clientX, clientY) {
    const r = this.svg.getBoundingClientRect();
    return [(clientX - r.left - this.tx) / this.s, (clientY - r.top - this.ty) / this.s];
  }

  toScreen(p) {
    return [p[0] * this.s + this.tx, p[1] * this.s + this.ty];
  }

  // Pixel auf dem Bildschirm in Welteinheiten
  px(n) {
    return n / this.s;
  }

  fit(box = this.contentBox, padding = 24) {
    if (!box) return;
    this.contentBox = box;
    const r = this.svg.getBoundingClientRect();
    const w = Math.max(r.width - 2 * padding, 50);
    const h = Math.max(r.height - 2 * padding, 50);
    this.s = Math.min(w / box.w, h / box.h);
    this.tx = (r.width - box.w * this.s) / 2 - box.x * this.s;
    this.ty = (r.height - box.h * this.s) / 2 - box.y * this.s;
    this.apply();
  }

  zoomAt(clientX, clientY, factor) {
    const r = this.svg.getBoundingClientRect();
    const sx = clientX - r.left;
    const sy = clientY - r.top;
    const ns = Math.min(Math.max(this.s * factor, 0.005), 400);
    const f = ns / this.s;
    this.tx = sx - (sx - this.tx) * f;
    this.ty = sy - (sy - this.ty) * f;
    this.s = ns;
    this.apply();
  }

  centerOn(p, zoom = null) {
    const r = this.svg.getBoundingClientRect();
    if (zoom) this.s = zoom;
    this.tx = r.width / 2 - p[0] * this.s;
    this.ty = r.height / 2 - p[1] * this.s;
    this.apply();
  }

  wheel(e) {
    e.preventDefault();
    const factor = Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015));
    this.zoomAt(e.clientX, e.clientY, factor);
  }

  startPan(e) {
    this.pan = { x: e.clientX, y: e.clientY, tx: this.tx, ty: this.ty };
    this.svg.classList.add('panning');
    this.svg.setPointerCapture?.(e.pointerId);
  }

  down(e) {
    this.svg.focus({ preventScroll: true });
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this.pointers.size === 2) {
      this.handler?.cancel?.();
      this.pan = null;
      const [p1, p2] = [...this.pointers.values()];
      this.pinch = { d: Math.hypot(p1.x - p2.x, p1.y - p2.y), cx: (p1.x + p2.x) / 2, cy: (p1.y + p2.y) / 2 };
      return;
    }
    if (this.pointers.size > 2) return;
    if (e.button === 1 || this.space || e.button === 2 && !this.handler?.wantsRightClick) {
      if (e.button === 2) this.handler?.rightClick?.(e, this.toWorld(e.clientX, e.clientY));
      if (e.button !== 2) this.startPan(e);
      return;
    }
    const res = this.handler?.down?.(e, this.toWorld(e.clientX, e.clientY));
    if (res === 'pan') this.startPan(e);
    else if (res) this.svg.setPointerCapture?.(e.pointerId);
  }

  move(e) {
    if (this.pointers.has(e.pointerId)) this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const w = this.toWorld(e.clientX, e.clientY);
    this.handler?.hover?.(e, w);
    if (this.pinch && this.pointers.size >= 2) {
      const [p1, p2] = [...this.pointers.values()];
      const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      const cx = (p1.x + p2.x) / 2;
      const cy = (p1.y + p2.y) / 2;
      this.tx += cx - this.pinch.cx;
      this.ty += cy - this.pinch.cy;
      this.pinch.cx = cx;
      this.pinch.cy = cy;
      if (this.pinch.d > 0) this.zoomAt(cx, cy, d / this.pinch.d);
      this.pinch.d = d;
      return;
    }
    if (this.pan) {
      this.tx = this.pan.tx + (e.clientX - this.pan.x);
      this.ty = this.pan.ty + (e.clientY - this.pan.y);
      this.apply();
      return;
    }
    this.handler?.move?.(e, w);
  }

  up(e) {
    this.pointers.delete(e.pointerId);
    if (this.pinch) {
      if (this.pointers.size < 2) this.pinch = null;
      return;
    }
    if (this.pan) {
      this.pan = null;
      this.svg.classList.remove('panning');
      return;
    }
    this.handler?.up?.(e, this.toWorld(e.clientX, e.clientY));
  }
}

export function isTyping(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
}
