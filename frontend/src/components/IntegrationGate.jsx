import { useEffect, useRef } from 'react';

// Bloquea el chat hasta que haya al menos una integracion (GitHub o Bitbucket) conectada.
export default function IntegrationGate({ onGoToIntegrations }) {
  const buttonRef = useRef(null);

  useEffect(() => {
    buttonRef.current?.focus();
  }, []);

  return (
    <div className="gate-backdrop">
      <div className="gate-modal" role="dialog" aria-modal="true" aria-labelledby="gate-title">
        <span className="eyebrow">Antes de empezar</span>
        <h2 id="gate-title">Conecta GitHub o Bitbucket</h2>
        <p>
          AgenteQA levanta tu repositorio para probarlo y, si algo falla, te dice en qué archivo está el
          problema. Para eso necesita un token de solo lectura.
        </p>
        <button ref={buttonRef} className="execute-button" onClick={onGoToIntegrations}>
          Ir a Integraciones
        </button>
      </div>
    </div>
  );
}
