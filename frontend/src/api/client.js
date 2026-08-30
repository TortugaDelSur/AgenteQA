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

  // NDJSON: una linea de progreso por test case a medida que termina, no esperamos al final.
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const results = [];
  let buffer = '';

  const handleLine = (line) => {
    if (!line.trim()) return;
    const progress = JSON.parse(line);
    results.push(progress.result);
    onProgress?.(progress);
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

  return { session_id: sessionId, results };
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
