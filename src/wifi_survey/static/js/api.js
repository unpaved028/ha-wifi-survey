// Schmale Hülle um die HTTP-API (siehe api/docs). Alle Pfade relativ: die Oberfläche läuft auch
// unter einem Unterpfad (Ingress von Home Assistant).

async function request(method, url, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) {
      opts.body = body;
    } else {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    let code = null;
    try {
      const data = await res.json();
      if (data && data.detail) {
        if (typeof data.detail === 'string') msg = data.detail;
        else if (Array.isArray(data.detail)) msg = data.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
        else { msg = data.detail.message || msg; code = data.detail.code; }   // Rückfrage mit Code
      }
    } catch { /* keine JSON-Antwort */ }
    const err = new Error(msg);
    err.status = res.status;
    err.code = code;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  project: () => request('GET', 'api/project'),
  materials: () => request('GET', 'api/materials'),
  thicknessClasses: () => request('GET', 'api/thickness-classes'),
  uploadPlan(file) {
    const form = new FormData();
    form.append('file', file);
    return request('POST', 'api/plans', form, true);
  },
  deletePlan: (id) => request('DELETE', `api/plans/${id}`),
  createFloor: (body) => request('POST', 'api/floors', body),
  updateFloor: (id, body) => request('PATCH', `api/floors/${id}`, body),
  deleteFloor: (id) => request('DELETE', `api/floors/${id}`),
  setScale: (id, body) => request('PUT', `api/floors/${id}/scale`, body),
  clearScale: (id) => request('DELETE', `api/floors/${id}/scale`),
  putWalls: (id, walls) => request('PUT', `api/floors/${id}/walls`, walls),
  detect: (id, body) => request('POST', `api/floors/${id}/detect`, body),
  exterior: (id) => request('GET', `api/floors/${id}/exterior`),
  putDevices: (id, devices) => request('PUT', `api/floors/${id}/devices`, devices),
  outline: (id) => request('GET', `api/floors/${id}/outline`),
  putOutline: (id, polygons) => request('PUT', `api/floors/${id}/outline`, { polygons }),
  rooms: (id) => request('GET', `api/floors/${id}/rooms`),
  demoLoad: () => request('POST', 'api/demo'),
  demoEnd: () => request('DELETE', 'api/demo'),
  putRoomLabels: (id, labels) => request('PUT', `api/floors/${id}/room-labels`, { labels }),
  catalog: () => request('GET', 'api/devices/catalog'),
  evaluation: (id) => request('GET', `api/floors/${id}/evaluation`),
  evaluationOverview: () => request('GET', 'api/evaluation'),
  simulate: (body) => request('POST', 'api/simulation', body),
  surveyAps: () => request('GET', 'api/survey/aps'),
  putBssids: (key, bssids) => request('PUT', `api/devices/${encodeURIComponent(key)}/bssids`, { bssids }),
  addSurveyPoint: (floorId, body) => request('POST', `api/floors/${floorId}/survey`, body),
  deleteSurveyPoint: (floorId, id) => request('DELETE', `api/floors/${floorId}/survey/${id}`),
  recommend: (body) => request('POST', 'api/simulation/recommend', body),
  heatmapUrl: (id, ap, stamp, band = '2.4') => `api/floors/${id}/evaluation/heatmap.png?ap=${encodeURIComponent(ap)}&band=${band}&v=${encodeURIComponent(stamp || '')}`,
  measure: () => request('POST', 'api/measurements'),
  info: () => request('GET', 'api/info'),
  progress: () => request('GET', 'api/progress'),
  locateDevices: (refresh) => request('GET', `api/locate/devices${refresh ? '?refresh=true' : ''}`),
  locate: (device, basis = 'auto') => request('POST', 'api/locate', { device, basis }),
  addFound: (floorId, body) => request('POST', `api/floors/${floorId}/found`, body),
  deleteFound: (floorId, id) => request('DELETE', `api/floors/${floorId}/found/${id}`),
  exportUrl: () => 'api/project/export',
  importProject(file) {
    const form = new FormData();
    form.append('file', file);
    return request('POST', 'api/project/import', form, true);
  },
  pagePreviewUrl: (planId, index) => `api/plans/${planId}/pages/${index}/preview.png`,
  floorImageUrl: (floor) => `api/floors/${floor.id}/image.png?v=${encodeURIComponent(floor.render_scale + '-' + floor.crop.x + '-' + floor.crop.y + '-' + floor.crop.w + '-' + floor.crop.h)}`,
};
