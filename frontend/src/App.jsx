import { useState } from 'react';
import { generatePlan, sendChat } from './api/client';

const welcomeMessage = {
  role: 'assistant',
  content: 'Hola, soy AgenteQA. Puedo ayudarte a diseñar pruebas para tu web o API. Cuéntame qué quieres validar.',
};

function QaStepper({ context, hasPlan }) {
  const completed = [
    Boolean(context.objetivo),
    Boolean(context.acceso),
    Boolean(context.alcance),
    Boolean(context.objetivo && context.acceso && context.alcance),
    hasPlan,
  ];
  const activeIndex = completed.findIndex((isCompleted) => !isCompleted);
  const steps = [
    { id: 'objective', title: 'Objetivo', description: 'Qué quieres validar' },
    { id: 'app', title: 'Tipo de aplicación', description: 'Web, API o ambas' },
    { id: 'flow', title: 'Endpoints y flujo', description: 'Alcance de las pruebas' },
    { id: 'cases', title: 'Casos de prueba', description: 'Contexto listo para planificar' },
    { id: 'plan', title: 'Plan generado', description: 'Plan listo para revisar' },
  ];

  return (
    <section className="qa-stepper" aria-label="Progreso de QA">
      <div className="stepper-heading">
        <span className="stepper-eyebrow">Progreso de QA</span>
        <span className="stepper-count">{completed.filter(Boolean).length}/{steps.length}</span>
      </div>
      <div className="stepper-list">
        {steps.map((step, index) => {
          const isCompleted = completed[index];
          const isActive = !isCompleted && index === activeIndex;
          return (
            <div className={`step ${isCompleted ? 'completed' : ''} ${isActive ? 'active' : ''}`} key={step.id}>
              <div className="step-rail">
                <span className="step-marker">{isCompleted ? '✓' : index + 1}</span>
                {index < steps.length - 1 && <span className="step-line" />}
              </div>
              <div className="step-content">
                <strong>{step.title}</strong>
                <small>{step.description}</small>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState([welcomeMessage]);
  const [input, setInput] = useState('');
  const [plan, setPlan] = useState(null);
  const [context, setContext] = useState({
    objetivo: false,
    acceso: false,
    alcance: false,
    repo: false,
    target_url: null,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const appendMessage = (role, content) => {
    setMessages((current) => [...current, { role, content }]);
  };

  const resetChat = () => {
    setSessionId('');
    setMessages([welcomeMessage]);
    setInput('');
    setPlan(null);
    setContext({ objetivo: false, acceso: false, alcance: false, repo: false, target_url: null });
    setError('');
  };

  const runGeneratePlan = async (id) => {
    setIsLoading(true);
    setError('');

    try {
      const data = await generatePlan(id);
      setPlan(data);
      appendMessage('assistant', `Plan generado: ${data.test_cases.length} casos de prueba.`);
    } catch (err) {
      setError(err.message || 'No se pudo generar el plan');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendMessage = async (event) => {
    event.preventDefault();
    const value = input.trim();
    if (!value || isLoading) return;

    setMessages((current) => [...current, { role: 'user', content: value }]);
    setInput('');
    setError('');
    setIsLoading(true);

    try {
      const data = await sendChat({ message: value, sessionId });
      setSessionId(data.session_id);
      setContext(data.context);
      appendMessage('assistant', data.reply);

      // el agente ya junto todo el contexto obligatorio: generamos el plan solo,
      // sin esperar que el usuario aprete un boton.
      if (data.ready_for_plan && !plan) {
        setIsLoading(false);
        await runGeneratePlan(data.session_id);
        return;
      }
    } catch (err) {
      setError(err.message || 'No se pudo enviar el mensaje');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="claude-app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <span>AgenteQA</span>
        </div>

        <QaStepper context={context} hasPlan={Boolean(plan)} />

        <div className="sidebar-bottom">
          <div className="provider">
            <span className="provider-dot" />
            <div>
              <strong>Groq conectado</strong>
              <small>Asistente listo</small>
            </div>
          </div>
        </div>
      </aside>

      <main className="conversation-area">
        <header className="conversation-header">
          <div className="model-picker">
            <span>AgenteQA</span>
            <span className="chevron">⌄</span>
          </div>
          <div className="header-actions">
            <button className="icon-button" aria-label="Compartir">↗</button>
            <button className="icon-button" aria-label="Más opciones">•••</button>
          </div>
        </header>

        <section className="chat-content">
          <div className="chat-scroll">
            <div className="messages">
              {messages.map((message, index) => (
                <article key={`${message.role}-${index}`} className={`message ${message.role}`}>
                  {message.role === 'assistant' && <div className="assistant-mark">A</div>}
                  <div className="message-body">
                    {message.role === 'assistant' && <span className="message-name">AgenteQA</span>}
                    <p>{message.content}</p>
                  </div>
                </article>
              ))}
              {isLoading && (
                <article className="message assistant">
                  <div className="assistant-mark">A</div>
                  <div className="message-body">
                    <span className="message-name">AgenteQA</span>
                    <div className="typing"><i /><i /><i /></div>
                  </div>
                </article>
              )}
            </div>

            {error && <div className="error-message">{error}</div>}

            {plan && (
              <section className="plan-card">
                <div className="plan-heading">
                  <div>
                    <span className="eyebrow">Plan generado</span>
                    <h2>{plan.test_cases.length} casos de prueba</h2>
                  </div>
                  <span className="plan-badge">Listo</span>
                </div>
                <div className="plan-list">
                  {plan.test_cases.map((test) => (
                    <div className="plan-item" key={test.id}>
                      <span className="test-id">{test.id}</span>
                      <span>{test.title}</span>
                      <span className="test-type">{test.type}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>

          <form className="composer" onSubmit={handleSendMessage}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form.requestSubmit();
                }
              }}
              placeholder="Escribe un mensaje a AgenteQA..."
              rows={1}
              aria-label="Mensaje"
            />
            <div className="composer-footer">
              <div className="composer-tools">
                <button type="button" className="tool-button" aria-label="Adjuntar archivo">+</button>
                <span>Agrega contexto sobre tu aplicación</span>
              </div>
              <div className="composer-actions">
                <span className="shortcut">Shift + Enter para nueva línea</span>
                <button type="submit" className="send-button" disabled={!input.trim() || isLoading} aria-label="Enviar">
                  ↑
                </button>
              </div>
            </div>
          </form>

          <p className="disclaimer">AgenteQA puede cometer errores. Revisa el plan antes de ejecutar las pruebas.</p>
        </section>
      </main>
    </div>
  );
}
