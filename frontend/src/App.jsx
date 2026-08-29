import { useMemo, useState } from 'react';
import { generatePlan, getChatHistory, sendChat } from './api/client';

const initialMessages = [
  {
    role: 'assistant',
    content: 'Hola. Cuéntame qué web o API quieres probar y te ayudo a preparar la validación.',
  },
];

export default function App() {
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState(initialMessages);
  const [input, setInput] = useState('');
  const [plan, setPlan] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const readyForPlan = useMemo(() => {
    return Boolean(sessionId) && messages.some((m) => m.role === 'assistant');
  }, [messages, sessionId]);

  const appendMessage = (role, content) => {
    setMessages((current) => [...current, { role, content }]);
  };

  const handleSendMessage = async (event) => {
    event.preventDefault();
    const value = input.trim();
    if (!value || isLoading) return;

    setIsLoading(true);
    setError('');
    appendMessage('user', value);
    setInput('');

    try {
      const data = await sendChat({ message: value, sessionId });
      setSessionId(data.session_id);
      appendMessage('assistant', data.reply);

      if (data.ready_for_plan) {
        try {
          const history = await getChatHistory(data.session_id);
          if (history.ready_for_plan) {
            setError('');
          }
        } catch {
          // no-op; el usuario puede continuar con el flujo.
        }
      }
    } catch (err) {
      const message = err.message || 'No se pudo enviar el mensaje';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleGeneratePlan = async () => {
    if (!sessionId || isLoading) return;

    setIsLoading(true);
    setError('');

    try {
      const data = await generatePlan(sessionId);
      setPlan(data);
      appendMessage('assistant', `Plan generado: ${data.test_cases.length} casos de prueba.`);
    } catch (err) {
      setError(err.message || 'No se pudo generar el plan');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AgenteQA</p>
          <h1>QA conversacional</h1>
        </div>
        <div className="session-pill">
          {sessionId ? `Sesión: ${sessionId.slice(0, 8)}` : 'Sin sesión'}
        </div>
      </header>

      <main className="layout">
        <section className="panel">
          <h2>Chat</h2>
          <div className="messages">
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`bubble ${message.role}`}>
                <strong>{message.role === 'user' ? 'Usuario' : 'Agente'}</strong>
                <p>{message.content}</p>
              </div>
            ))}
          </div>

          <form onSubmit={handleSendMessage} className="composer">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ej: quiero probar la app de login y la API de usuarios"
              rows={3}
            />
            <button type="submit" disabled={isLoading || !input.trim()}>
              {isLoading ? 'Enviando…' : 'Enviar'}
            </button>
          </form>

          <button
            className="secondary"
            onClick={handleGeneratePlan}
            disabled={!readyForPlan || isLoading}
          >
            Generar plan
          </button>
        </section>

        <aside className="panel">
          <h2>Resultado</h2>
          {error && <div className="alert error">{error}</div>}

          {!plan && !error && <p className="placeholder">El plan aparecerá aquí después del chat.</p>}

          {plan && (
            <div className="plan-box">
              <h3>{plan.test_cases.length} casos de prueba</h3>
              <ul>
                {plan.test_cases.map((test) => (
                  <li key={test.id}>
                    <strong>{test.id}</strong> — {test.title}
                    <span>{test.type}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
