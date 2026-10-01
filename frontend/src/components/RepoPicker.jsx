import { useEffect, useMemo, useRef, useState } from 'react';
import { listRepos, selectRepo } from '../api/client';

const PROVIDER_LABEL = { github: 'GitHub', bitbucket: 'Bitbucket' };

// Elige el repo a probar entre los que ve el token: nunca se pega un link (el backend ademas valida
// que el repo elegido este en esa lista).
export default function RepoPicker({ sessionId, onSelected, onGoToIntegrations }) {
  const [repos, setRepos] = useState(null);
  const [errors, setErrors] = useState({});
  const [loadError, setLoadError] = useState('');
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(null);
  const [selectError, setSelectError] = useState('');
  const searchRef = useRef(null);

  useEffect(() => {
    listRepos()
      .then((data) => {
        setRepos(data.repos);
        setErrors(data.errors || {});
      })
      .catch((err) => setLoadError(err.message || 'No se pudieron cargar los repositorios'));
    searchRef.current?.focus();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (repos || []).filter((r) => !q || r.full_name.toLowerCase().includes(q)
      || (r.description || '').toLowerCase().includes(q));
  }, [repos, query]);

  const choose = async (repo) => {
    setBusy(repo.full_name);
    setSelectError('');
    try {
      const data = await selectRepo(sessionId, repo.provider, repo.full_name);
      if (!data.cloned) {
        setSelectError(data.detail || 'No se pudo clonar el repositorio');
        return;
      }
      onSelected(data);
    } catch (err) {
      setSelectError(err.message || 'No se pudo elegir el repositorio');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="gate-backdrop">
      <div className="gate-modal repo-picker" role="dialog" aria-modal="true" aria-labelledby="picker-title">
        <span className="eyebrow">Paso 1</span>
        <h2 id="picker-title">Elige el repositorio a probar</h2>
        <p>Solo aparecen los repositorios a los que tu token tiene acceso.</p>

        <input
          ref={searchRef}
          className="repo-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar por nombre o descripción"
          aria-label="Buscar repositorio"
        />

        {Object.entries(errors).map(([provider, detail]) => (
          <p className="integration-error" key={provider}>
            {PROVIDER_LABEL[provider]}: {detail}{' '}
            <button type="button" className="link-button" onClick={onGoToIntegrations}>Revisar integración</button>
          </p>
        ))}
        {loadError && <p className="integration-error">{loadError}</p>}
        {selectError && <p className="integration-error">{selectError}</p>}

        <div className="repo-list" role="list">
          {repos === null && !loadError && <p className="repo-empty">Cargando repositorios...</p>}
          {repos !== null && filtered.length === 0 && (
            <p className="repo-empty">
              {repos.length === 0
                ? 'Tu token no ve ningún repositorio. Revisa que tenga acceso a los repos que quieres probar.'
                : 'Ningún repositorio coincide con la búsqueda.'}
            </p>
          )}
          {filtered.map((repo) => (
            <div className="repo-item" role="listitem" key={`${repo.provider}:${repo.full_name}`}>
              <div className="repo-info">
                <strong>{repo.full_name}</strong>
                <span className="repo-meta">
                  {PROVIDER_LABEL[repo.provider]} · {repo.private ? 'Privado' : 'Público'}
                  {repo.updated_at && ` · actualizado ${repo.updated_at.slice(0, 10)}`}
                </span>
                {repo.description && <span className="repo-desc">{repo.description}</span>}
              </div>
              <button
                type="button"
                className="execute-button repo-choose"
                disabled={busy !== null}
                onClick={() => choose(repo)}
                aria-label={`Probar ${repo.full_name}`}
              >
                {busy === repo.full_name ? 'Clonando...' : 'Probar'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
