// Geometrie-Helfer. Punkte sind [x, y]-Arrays in Weltkoordinaten der jeweiligen Ansicht.

export const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
export const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
export const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
export const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];

export function projectOnSegment(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  let t = len2 > 0 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const pt = [a[0] + t * dx, a[1] + t * dy];
  return { pt, t, d: dist(p, pt) };
}

// Richtung von `from` nach `to` auf ein Vielfaches von stepDeg runden (Länge bleibt als Projektion)
export function snapAngle(from, to, stepDeg = 45) {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const len = Math.hypot(dx, dy);
  if (len === 0) return to.slice();
  const step = (stepDeg * Math.PI) / 180;
  const ang = Math.round(Math.atan2(dy, dx) / step) * step;
  const ux = Math.cos(ang);
  const uy = Math.sin(ang);
  const proj = dx * ux + dy * uy;
  return [from[0] + ux * proj, from[1] + uy * proj];
}

export function wallCorners(w) {
  const [ax, ay] = w.a;
  const [bx, by] = w.b;
  const len = Math.hypot(bx - ax, by - ay) || 1;
  const nx = (-(by - ay) / len) * (w.thickness_px / 2);
  const ny = ((bx - ax) / len) * (w.thickness_px / 2);
  return [[ax + nx, ay + ny], [bx + nx, by + ny], [bx - nx, by - ny], [ax - nx, ay - ny]];
}

export const pointsAttr = (pts) => pts.map((p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(' ');

export function normRect(a, b) {
  return { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), w: Math.abs(a[0] - b[0]), h: Math.abs(a[1] - b[1]) };
}

export const inPolygon = (p, poly) => {      // Strahlverfahren: liegt p im Vieleck?
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]; const [xj, yj] = poly[j];
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};
export const inRect = (p, r) => p[0] >= r.x && p[0] <= r.x + r.w && p[1] >= r.y && p[1] <= r.y + r.h;

export function rotate(p, deg) {
  const r = (deg * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  return [p[0] * c - p[1] * s, p[0] * s + p[1] * c];
}

// Zahlenformat mit deutschem Komma
export function fmt(n, digits = 2) {
  return Number(n).toLocaleString('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtLength(px, pxPerM) {
  return pxPerM ? `${fmt(px / pxPerM, 2)} m` : `${fmt(px, 0)} px`;
}

export function fmtThickness(px, pxPerM) {
  return pxPerM ? `${fmt((px / pxPerM) * 100, 1)} cm` : `${fmt(px, 1)} px`;
}

export function parseNumber(str) {
  if (typeof str === 'number') return str;
  const v = parseFloat(String(str).replace(',', '.'));
  return Number.isFinite(v) ? v : NaN;
}

export function newId(prefix = 'w') {
  const bytes = new Uint8Array(4);
  crypto.getRandomValues(bytes);
  return `${prefix}_${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`;
}

export const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
export const cross = (a, b) => a[0] * b[1] - a[1] * b[0];

export function unit(a, b) {
  const len = dist(a, b) || 1;
  return [(b[0] - a[0]) / len, (b[1] - a[1]) / len];
}

// Schnittpunkt der Geraden durch a1–a2 und b1–b2 (null, wenn parallel)
export function lineIntersection(a1, a2, b1, b2) {
  const r = sub(a2, a1);
  const s = sub(b2, b1);
  const den = cross(r, s);
  if (Math.abs(den) < 1e-9) return null;
  const t = cross(sub(b1, a1), s) / den;
  return [a1[0] + t * r[0], a1[1] + t * r[1]];
}
