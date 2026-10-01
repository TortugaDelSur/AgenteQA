import { useState } from 'react';
import { removeIntegration, saveIntegration } from '../api/client';

const PROVIDERS = [
  {
    id: 'github',
    name: 'GitHub',
    tokenName: 'Fine-grained personal access token',
    steps: [
      'Settings → Developer settings → Personal access tokens → Fine-grained tokens.',
      'Repository access: solo los repos que vas a probar.',
      'Permissions: Contents → Read-only. Nada más.',
    ],
    link: 'https://github.com/settings/personal-access-tokens/new',
  },
  {
    id: 'bitbucket',
    name: 'Bitbucket',
    tokenName: 'Repository access token',
    steps: [
      'En el repo: Repository settings → Security → Access tokens.',
      'Scope: Repositories → Read. Nada más.',
    ],
    link: 'https://support.atlassian.com/bitbucket-cloud/docs/repository-access-tokens/',
  },
];

function IntegrationCard({ provider, connected, onChange }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const run = async (action) => {
    setBusy(true);
    setError('');
    try {
      onChange(await action());
      setToken('');
    } catch (err) {
      setError(err.message || 'No se pudo guardar la integración');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="integration-card" aria-labelledby={`integration-${provider.id}`}>
      <div className="integration-heading">
        <h2 id={`integration-${provider.id}`}>{provider.name}</h2>
        <span className={`integration-status ${connected ? 'on' : ''}`}>
          {connected ? 'Conectado' : 'Sin conectar'}
        </span>
      </div>
      <p className="integration-help">
        Usa un <strong>{provider.tokenName}</strong> de solo lectura:
      </p>
      <ol className="integration-steps">
        {provider.steps.map((step) => <li key={step}>{step}</li>)}
      </ol>
      <a className="integration-link" href={provider.link} target="_blank" rel="noreferrer">
        Cómo crearlo ↗
      </a>
      <form
        className="integration-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (token.trim()) run(() => saveIntegration(provider.id, token.trim()));
        }}
      >
        <input
          type="password"
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder={connected ? 'Pegar un token nuevo para reemplazarlo' : 'Pegar token'}
          aria-label={`Token de ${provider.name}`}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !token.trim()}>
          {busy ? 'Guardando...' : connected ? 'Reemplazar' : 'Conectar'}
        </button>
        {connected && (
          <button
            type="button"
            className="integration-remove"
            disabled={busy}
            onClick={() => run(() => removeIntegration(provider.id))}
          >
            Desconectar
          </button>
        )}
      </form>
      {error && <p className="integration-error">{error}</p>}
    </section>
  );
}

export default function IntegrationsPage({ integrations, onChange, onBack }) {
  const anyConnected = Boolean(integrations?.github || integrations?.bitbucket);

  return (
    <section className="integrations-page">
      <span className="eyebrow">Configuración</span>
      <h1>Integraciones</h1>
      <p className="integrations-intro">
        AgenteQA necesita acceso de lectura a tu repositorio para levantarlo, probarlo y señalar dónde
        está el problema cuando algo falla. Conecta al menos uno.
      </p>
      <p className="integrations-note">
        El token se guarda solo en la memoria del servidor: nunca se muestra, no se guarda en el
        navegador y no se envía al modelo. Si el servidor se reinicia, hay que volver a conectarlo.
      </p>
      <div className="integrations-grid">
        {PROVIDERS.map((provider) => (
          <IntegrationCard
            key={provider.id}
            provider={provider}
            connected={Boolean(integrations?.[provider.id])}
            onChange={onChange}
          />
        ))}
      </div>
      {anyConnected && (
        <button className="execute-button" onClick={onBack}>
          Ir al agente
        </button>
      )}
    </section>
  );
}
