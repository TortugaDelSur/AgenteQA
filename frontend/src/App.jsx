import { useEffect, useRef, useState } from 'react';
import { downloadReport, executePlan, generatePlan, sendChat } from './api/client';

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
  const [results, setResults] = useState(null);
  const [report, setReport] = useState(null);
  const [context, setContext] = useState({
    objetivo: false,
    acceso: false,
    alcance: false,
    repo: false,
    target_url: null,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const chatScrollRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    const chatScroll = chatScrollRef.current;
    if (chatScroll) {
      chatScroll.scrollTop = chatScroll.scrollHeight;
    }
  }, [messages, isLoading, error, plan]);

  const appendMessage = (role, content) => {
    setMessages((current) => [...current, { role, content }]);
  };

  const resetChat = () => {
    setSessionId('');
    setMessages([welcomeMessage]);
    setInput('');
    setPlan(null);
    setResults(null);
    setReport(null);
    setContext({ objetivo: false, acceso: false, alcance: false, repo: false, target_url: null });
    setError('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const resizeTextarea = (textarea) => {
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    textarea.style.overflowY = textarea.scrollHeight > 200 ? 'auto' : 'hidden';
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

  const handleExecutePlan = async () => {
    if (!sessionId || !plan || isLoading) return;

    setError('');
    setIsLoading(true);
    try {
      const data = await executePlan(sessionId);
      setResults(data.results);
      appendMessage('assistant', `Ejecución completada: ${data.results.length} casos procesados.`);
    } catch (err) {
      setError(err.message || 'No se pudo ejecutar el plan');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownloadReport = async () => {
    if (!sessionId || !results || isLoading) return;

    setError('');
    setIsLoading(true);
    try {
      const data = await downloadReport(sessionId);
      setReport(data.content);
      const blob = new Blob([data.content], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = data.filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || 'No se pudo generar el reporte');
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
    if (textareaRef.current) {
      textareaRef.current.style.height = '44px';
      textareaRef.current.style.overflowY = 'hidden';
    }
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
      </aside>

      <main className="conversation-area">
        <section className="chat-content">
          <div className="chat-scroll" ref={chatScrollRef}>
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
                <button className="execute-button" onClick={handleExecutePlan} disabled={isLoading}>
                  Ejecutar plan de pruebas
                </button>
              </section>
            )}

            {results && (
              <section className="execution-card">
                <div className="plan-heading">
                  <div>
                    <span className="eyebrow">Ejecución</span>
                    <h2>{results.length} resultados</h2>
                  </div>
                  <span className="plan-badge">Completada</span>
                </div>
                <div className="results-list">
                  {results.map((result) => (
                    <div className="result-item" key={`${result.test_case_id}-${result.detail}`}>
                      <span className={`result-status ${result.status}`}>{result.status}</span>
                      <div>
                        <strong>{result.test_case_id}</strong>
                        <p>{result.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
                <button className="report-button" onClick={handleDownloadReport} disabled={isLoading}>
                  Descargar reporte Markdown
                </button>
                {report && <p className="report-ready">Reporte generado y descargado.</p>}
              </section>
            )}
          </div>

          <form className="composer" onSubmit={handleSendMessage}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                resizeTextarea(event.target);
              }}
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
