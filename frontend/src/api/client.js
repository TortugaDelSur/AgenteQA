const API_BASE = '/api';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });

  const isJson = response.headers.get('content-type')?.includes('application/json');
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const message = typeof payload === 'string' ? payload : payload?.detail || 'Error de la API';
    throw new Error(message);
  }

  return payload;
}

export async function sendChat({ message, sessionId }) {
  return request('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId || null }),
  });
}

export async function getChatHistory(sessionId) {
  return request(`/chat/${sessionId}`);
}

export async function generatePlan(sessionId) {
  return request('/plan', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  });
}

// NDJSON: una linea de evento por vez, procesada a medida que llega, no esperamos al final.
async function readNdjson(response, onLine) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const handleLine = (line) => {
    if (line.trim()) onLine(JSON.parse(line));
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    lines.forEach(handleLine);
  }
  if (buffer) handleLine(buffer);
}

export async function executePlan(sessionId, onProgress) {
  const response = await fetch(`${API_BASE}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || 'No se pudo ejecutar el plan');
  }

  const results = [];
  let paused = null;
  // la ultima linea puede ser {"type": "paused"}: la pregunta la muestra LivePanel (llega por el WS).
  await readNdjson(response, (progress) => {
    if (progress.type === 'paused') {
      paused = progress;
      return;
    }
    results.push(progress.result);
    onProgress?.(progress);
  });

  return { session_id: sessionId, results, paused };
}

export async function getExecuteState(sessionId) {
  return request(`/execute/state/${sessionId}`);
}

export async function answerExecuteQuestion(sessionId, answer) {
  return request('/execute/answer', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, answer }),
  });
}

export async function submitExecuteLogin(sessionId, username, password) {
  return request('/execute/login', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, username, password }),
  });
}

// Solo lectura: el socket nunca manda nada al servidor.
export function openLiveSocket(sessionId, onMessage) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/live/${sessionId}`);
  socket.onmessage = (event) => onMessage(JSON.parse(event.data));
  return socket;
}

export async function sweepPlan(sessionId, onEvent) {
  const response = await fetch(`${API_BASE}/plan/sweep`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || 'No se pudo generar el plan');
  }

  await readNdjson(response, onEvent);
}

export async function answerSweepQuestion(sessionId, answer) {
  return request('/plan/sweep/answer', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, answer }),
  });
}

export async function submitSweepLogin(sessionId, username, password) {
  return request('/plan/sweep/login', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, username, password }),
  });
}

// Integraciones: el token va directo al backend (solo memoria del servidor); nunca se guarda en
// el navegador ni pasa por el chat.
export async function getIntegrations() {
  return request('/integrations');
}

export async function saveIntegration(provider, token, email) {
  return request('/integrations', {
    method: 'POST',
    body: JSON.stringify({ provider, token, email: email || null }),
  });
}

// Repos a los que dan acceso los tokens conectados: el usuario elige uno, nunca pega un link.
export async function listRepos() {
  return request('/repos');
}

// libera el clon y apaga el repo levantado de esa sesion (al cambiar de repo / empezar de nuevo).
export async function forgetRepo(sessionId) {
  return request(`/repo/${sessionId}`, { method: 'DELETE' });
}

export async function selectRepo(sessionId, provider, fullName) {
  return request('/repo/select', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId || null, provider, full_name: fullName }),
  });
}

export async function removeIntegration(provider) {
  return request(`/integrations/${provider}`, { method: 'DELETE' });
}

export async function downloadReport(sessionId) {
  const response = await fetch(`${API_BASE}/report/${sessionId}`);
  const payload = await response.text();

  if (!response.ok) {
    let message = payload;
    try {
      message = JSON.parse(payload).detail || message;
    } catch {
      // La API puede responder texto plano en errores no JSON.
    }
    throw new Error(message || 'No se pudo generar el reporte');
  }

  return {
    content: payload,
    filename: response.headers.get('content-disposition')?.match(/filename="?([^"]+)/)?.[1] || 'reporte.md',
  };
}
