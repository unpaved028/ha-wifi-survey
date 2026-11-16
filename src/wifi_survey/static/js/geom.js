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

export const overlapArea = (a, b) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0))
  * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));

export const inRoomContours = (p, contours) => (contours || []).some((pg) => inPolygon(p, pg));

// Prüft per Liang-Barsky, ob Strecke a–b das Rechteck { x0, y0, x1, y1 } schneidet oder darin liegt
export function segIntersectsRect(a, b, r) {
  let t0 = 0;
  let t1 = 1;
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  for (const [p, q] of [[-dx, a[0] - r.x0], [dx, r.x1 - a[0]], [-dy, a[1] - r.y0], [dy, r.y1 - a[1]]]) {
    if (Math.abs(p) < 1e-9) {
      if (q < 0) return false;
    } else {
      const t = q / p;
      if (p < 0) t0 = Math.max(t0, t);
      else t1 = Math.min(t1, t);
      if (t0 > t1) return false;
    }
  }
  return t0 <= t1;
}

function boxWallHits(box, walls, pad) {
  let hits = 0;
  for (const w of walls) {
    const h = (w.thickness_px || 10) / 2 + pad;
    const ex = { x0: box.x0 - h, y0: box.y0 - h, x1: box.x1 + h, y1: box.y1 + h };
    if (Math.max(w.a[0], w.b[0]) < ex.x0 || Math.min(w.a[0], w.b[0]) > ex.x1) continue;
    if (Math.max(w.a[1], w.b[1]) < ex.y0 || Math.min(w.a[1], w.b[1]) > ex.y1) continue;
    if (segIntersectsRect(w.a, w.b, ex)) hits += 1;
  }
  return hits;
}

// Platziert eine Raum-Pille überlappungsfrei im Raum (optional mit Abstand zu Wänden)
export function placeRoomLabel(boxes, rm, w, h, px, walls = []) {
  const [ax, ay] = rm.anchor;
  const cands = [];
  const hasWalls = walls.length > 0;
  const sx = hasWalls ? Math.max(px(24), w * 0.35) : px(28);
  const sy = hasWalls ? Math.max(px(18), h * 0.85) : px(20);
  const rangeX = hasWalls ? [0, -1, 1, -2, 2, -3, 3] : [0, -1, 1, -2, 2];
  for (const dx of rangeX) {
    for (const dy of [0, -1, 1, -2, 2, -3, 3, -4, 4]) {
      const cx = ax + dx * sx;
      const cy = ay + dy * sy;
      cands.push([cx, cy, Math.hypot(cx - ax, cy - ay)]);
    }
  }
  if (hasWalls && rm.contours?.length) {
    const pts = rm.contours.flat();
    let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
    for (const [x, y] of pts) {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    for (const fx of [0.25, 0.5, 0.75]) {
      for (const fy of [0.25, 0.5, 0.75]) {
        const cx = minX + (maxX - minX) * fx;
        const cy = minY + (maxY - minY) * fy;
        cands.push([cx, cy, Math.hypot(cx - ax, cy - ay)]);
      }
    }
  }
  cands.sort((a, b) => a[2] - b[2]);
  let best = { cx: ax, cy: ay, box: { x0: ax - w / 2, y0: ay - h / 2, x1: ax + w / 2, y1: ay + h / 2 }, score: Infinity };
  const pad = px(3);
  for (const [cx, cy, dAnchor] of cands) {
    const box = { x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 };
    const area = boxes.reduce((s, o) => s + overlapArea(box, o), 0);
    const inside = inRoomContours([cx, cy], rm.contours);
    const wallHits = hasWalls ? boxWallHits(box, walls, pad) : 0;
    const cornersOut = hasWalls
      ? [[cx - w * 0.42, cy - h * 0.4], [cx + w * 0.42, cy - h * 0.4], [cx - w * 0.42, cy + h * 0.4], [cx + w * 0.42, cy + h * 0.4]]
        .filter((pt) => !inRoomContours(pt, rm.contours)).length
      : 0;
    const score = (!inside ? 1e9 : 0) + (area > 0 ? 1e6 + area : 0) + wallHits * 50000 + cornersOut * 2000 + dAnchor * 0.05;
    if (score < best.score) {
      best = { cx, cy, box, score };
      if (area === 0 && inside && wallHits === 0 && cornersOut === 0) break;
    }
  }
  boxes.push(best.box);
  return [best.cx, best.cy];
}

function contourBox(contours) {
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const pg of contours || []) {
    for (const [x, y] of pg) {
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  return { x0, y0, x1, y1 };
}

function pointNearContours(p, contours, gap) {
  for (const pg of contours || []) {
    for (let i = 0; i < pg.length; i += 1) {
      const a = pg[i];
      const b = pg[(i + 1) % pg.length];
      if (projectOnSegment(p, a, b).d <= gap) return true;
    }
  }
  return false;
}

function roomsAdjacent(ca, cb, gap) {
  for (const pg of ca) {
    if (pg.some((p) => pointNearContours(p, cb, gap))) return true;
  }
  for (const pg of cb) {
    if (pg.some((p) => pointNearContours(p, ca, gap))) return true;
  }
  return false;
}

// Weist Räumen Farbindizes (0 .. paletteSize-1) zu, sodass Nachbarräume verschieden gefärbt sind
export function assignRoomColors(rooms, gap = 50, paletteSize = 6) {
  const boxes = rooms.map((r) => contourBox(r.contours));
  const colors = new Array(rooms.length).fill(-1);
  for (let i = 0; i < rooms.length; i += 1) {
    const used = new Set();
    const bi = boxes[i];
    for (let j = 0; j < i; j += 1) {
      const bj = boxes[j];
      if (bi.x1 + gap < bj.x0 || bj.x1 + gap < bi.x0 || bi.y1 + gap < bj.y0 || bj.y1 + gap < bi.y0) continue;
      if (roomsAdjacent(rooms[i].contours, rooms[j].contours, gap)) used.add(colors[j]);
    }
    const base = i % paletteSize;
    let pick = base;
    for (let k = 0; k < paletteSize; k += 1) {
      const cand = (base + k) % paletteSize;
      if (!used.has(cand)) { pick = cand; break; }
    }
    colors[i] = pick;
  }
  return colors;
}
