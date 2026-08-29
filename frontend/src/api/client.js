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
