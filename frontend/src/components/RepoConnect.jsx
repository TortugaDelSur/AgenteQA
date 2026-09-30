import { useEffect, useState } from 'react';

// Token del repo fuera del chat: va directo a /api/repo/credentials (solo memoria del backend),
// nunca pasa por el LLM ni se guarda en el navegador.
async function repoRequest(path, options) {
  const response = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload?.detail === 'string' ? payload.detail : 'Error de la API');
  return payload;
}

function providerOf(repoUrl) {
  return repoUrl?.includes('bitbucket.org') ? 'bitbucket' : 'github';
}

export default function RepoConnect({ sessionId, repoUrl }) {
  const [provider, setProvider] = useState(providerOf(repoUrl));
  const [token, setToken] = useState('');
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => setProvider(providerOf(repoUrl)), [repoUrl]);

  useEffect(() => {
    if (!sessionId) return;
    repoRequest(`/repo/status?session_id=${encodeURIComponent(sessionId)}`).then(setStatus).catch(() => setStatus(null));
  }, [sessionId, repoUrl]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!sessionId || !token.trim()) return;
    setBusy(true);
    setError('');
    try {
      const next = await repoRequest('/repo/credentials', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, provider, token: token.trim() }),
      });
      setStatus((prev) => ({ ...prev, ...next }));
      setToken('');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const connected = status?.[provider];

  return (
    <form className="sweep-login" onSubmit={handleSubmit} aria-label="Conectar repo">
      <p>Conectar repo {connected ? '· conectado' : ''}{status?.cloned ? ' · clonado' : ''}</p>
      {!sessionId && <p>Escribe en el chat primero para abrir la sesión.</p>}
      <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={!sessionId || busy}>
        <option value="github">GitHub</option>
        <option value="bitbucket">Bitbucket</option>
      </select>
      <input
        type="password"
        autoComplete="off"
        placeholder={connected ? 'Reemplazar token' : 'Token de acceso'}
        value={token}
        onChange={(e) => setToken(e.target.value)}
        disabled={!sessionId || busy}
        aria-label="Token del repo"
      />
      <button type="submit" disabled={!sessionId || busy || !token.trim()}>
        {busy ? 'Conectando...' : 'Conectar'}
      </button>
      {error && <p>{error}</p>}
    </form>
  );
}
