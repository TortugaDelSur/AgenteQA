import { useEffect, useRef, useState } from 'react';
import { downloadReport, executePlan, generatePlan, sendChat } from './api/client';

const welcomeMessage = {
  role: 'assistant',
  content: 'Hola, soy AgenteQA. Puedo ayudarte a diseñar pruebas para tu web o API. Cuéntame qué quieres validar.',
};

const SESSION_STORAGE_KEY = 'agenteqa_session_id';

const bubbleData = [
  { left: '82%', size: 32, category: 'foreground', duration: 24, delay: -0.0, drift: 16, opacity: 0.7, blur: 2 },
  { left: '12%', size: 48, category: 'foreground', duration: 28, delay: -1.5, drift: -18, opacity: 0.66, blur: 2 },
  { left: '64%', size: 72, category: 'mid', duration: 31, delay: -3.0, drift: 20, opacity: 0.42, blur: 8 },
  { left: '5%', size: 86, category: 'back', duration: 34, delay: -4.5, drift: -14, opacity: 0.2, blur: 18 },
  { left: '91%', size: 44, category: 'foreground', duration: 20, delay: -6.0, drift: -22, opacity: 0.6, blur: 2 },
  { left: '38%', size: 96, category: 'back', duration: 30, delay: -7.5, drift: 18, opacity: 0.22, blur: 20 },
  { left: '73%', size: 54, category: 'mid', duration: 26, delay: -9.0, drift: -17, opacity: 0.34, blur: 6 },
  { left: '24%', size: 40, category: 'foreground', duration: 23, delay: -10.5, drift: 12, opacity: 0.63, blur: 2 },
  { left: '49%', size: 68, category: 'mid', duration: 29, delay: -12.0, drift: 15, opacity: 0.38, blur: 9 },
  { left: '58%', size: 28, category: 'foreground', duration: 22, delay: -13.5, drift: -12, opacity: 0.7, blur: 2 },
  { left: '31%', size: 112, category: 'back', duration: 36, delay: -15.0, drift: 19, opacity: 0.18, blur: 22 },
  { left: '68%', size: 36, category: 'foreground', duration: 25, delay: -16.5, drift: 16, opacity: 0.58, blur: 2 },
  { left: '87%', size: 76, category: 'mid', duration: 32, delay: -18.0, drift: -15, opacity: 0.3, blur: 8 },
  { left: '17%', size: 54, category: 'mid', duration: 27, delay: -19.5, drift: 22, opacity: 0.44, blur: 7 },
  { left: '52%', size: 24, category: 'foreground', duration: 21, delay: -21.0, drift: -10, opacity: 0.68, blur: 2 },
  { left: '96%', size: 88, category: 'back', duration: 33, delay: -22.5, drift: -18, opacity: 0.16, blur: 18 },
  { left: '44%', size: 36, category: 'foreground', duration: 24, delay: -24.0, drift: -16, opacity: 0.62, blur: 2 },
  { left: '59%', size: 84, category: 'mid', duration: 30, delay: -25.5, drift: 10, opacity: 0.28, blur: 12 },
  { left: '7%', size: 26, category: 'foreground', duration: 22, delay: -27.0, drift: 18, opacity: 0.7, blur: 2 },
  { left: '93%', size: 58, category: 'mid', duration: 29, delay: -28.5, drift: -12, opacity: 0.36, blur: 7 },
];

function QaIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 3 20 6v5c0 5-3.3 8.7-8 10-4.7-1.3-8-5-8-10V6l8-3Z" fill="url(#qa-gradient)" />
      <path d="m8.5 12 2.2 2.2 4.8-5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <defs>
        <linearGradient id="qa-gradient" x1="4" y1="4" x2="19" y2="20">
          <stop stopColor="#c7b7ff" />
          <stop offset="1" stopColor="#7353d6" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function TypingLoader() {
  return (
    <div className="typing" aria-label="Escribiendo">
      <i />
      <i />
      <i />
    </div>
  );
}

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
      <div className="progress-track"><span style={{ width: `${(completed.filter(Boolean).length / steps.length) * 100}%` }} /></div>
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
  const [executionProgress, setExecutionProgress] = useState(null);
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

  // Al recargar la página se reinicia el chat para empezar una sesión nueva.
  useEffect(() => {
    try {
      localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // localStorage no disponible: no hay nada que limpiar
    }
    setSessionId('');
    setMessages([welcomeMessage]);
    setContext({ objetivo: false, acceso: false, alcance: false, repo: false, target_url: null });
    setPlan(null);
    setResults(null);
    setExecutionProgress(null);
    setReport(null);
    setError('');
    if (textareaRef.current) {
      textareaRef.current.style.height = '44px';
      textareaRef.current.style.overflowY = 'hidden';
    }
  }, []);

  const appendMessage = (role, content) => {
    setMessages((current) => [...current, { role, content }]);
  };

  const resetChat = () => {
    setSessionId('');
    setMessages([welcomeMessage]);
    setInput('');
    setPlan(null);
    setResults(null);
    setExecutionProgress(null);
    setReport(null);
    setContext({ objetivo: false, acceso: false, alcance: false, repo: false, target_url: null });
    setError('');
    try {
      localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // localStorage no disponible: no hay nada que limpiar
    }
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
    setResults([]);
    setExecutionProgress({ index: 0, total: plan.test_cases.length });
    try {
      const data = await executePlan(sessionId, (progress) => {
        setExecutionProgress({ index: progress.index, total: progress.total });
        setResults((current) => [...current, progress.result]);
      });
      appendMessage('assistant', `Ejecución completada: ${data.results.length} casos procesados.`);
    } catch (err) {
      setError(err.message || 'No se pudo ejecutar el plan');
    } finally {
      setIsLoading(false);
      setExecutionProgress(null);
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
      try {
        localStorage.setItem(SESSION_STORAGE_KEY, data.session_id);
      } catch {
        // localStorage no disponible (modo privado, etc): la sesion sigue funcionando en memoria
      }
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
      <div className="ambient-glow" aria-hidden="true">
        <span className="glow glow-1" />
        <span className="glow glow-2" />
        <span className="glow glow-3" />
        <span className="glow glow-4" />
      </div>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <span>AgenteQA</span>
        </div>

        <QaStepper context={context} hasPlan={Boolean(plan)} />
      </aside>

      <main className="conversation-area">
        <div className="floating-bubbles" aria-hidden="true">
          {bubbleData.map((bubble, index) => (
            <span
              key={`bubble-${index}`}
              className={`bubble-wrapper ${bubble.category}`}
              style={{
                left: bubble.left,
                animationDuration: `${bubble.duration}s`,
                animationDelay: `${bubble.delay}s`,
                ['--drift-x']: `${bubble.drift}px`,
                ['--bubble-opacity']: String(bubble.opacity),
                ['--blur']: `${bubble.blur}px`,
                ['--size']: `${bubble.size}px`,
              }}
            >
              <span className="bubble-circle" style={{ width: `${bubble.size}px`, height: `${bubble.size}px` }} />
            </span>
          ))}
        </div>
        <section className="chat-content">
          <div className="chat-scroll" ref={chatScrollRef}>
            <div className="messages">
              {messages.map((message, index) => (
                <article key={`${message.role}-${index}`} className={`message ${message.role}`}>
                  {message.role === 'assistant' && <div className="assistant-mark">A</div>}
                  <div className="message-body">
                    {message.role === 'assistant' && <span className="message-name">AgenteQA</span>}
                    {message.role === 'assistant' && (
                      <button
                        type="button"
                        className="copy-button"
                        onClick={() => {
                          navigator.clipboard?.writeText(message.content).catch(() => {});
                        }}
                        aria-label="Copiar respuesta"
                        title="Copiar contenido"
                      >
                        <span className="copy-icon">⧉</span>
                      </button>
                    )}
                    <p>{message.content}</p>
                  </div>
                </article>
              ))}
              {isLoading && (
                <article className="message assistant">
                  <div className="assistant-mark">A</div>
                  <div className="message-body">
                    <span className="message-name">AgenteQA</span>
                    <TypingLoader />
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
                    <h2>
                      {executionProgress
                        ? `Ejecutando prueba ${executionProgress.index} de ${executionProgress.total}...`
                        : `${results.length} resultados`}
                    </h2>
                  </div>
                  <span className="plan-badge">{executionProgress ? 'En curso' : 'Completada'}</span>
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
                {!executionProgress && (
                  <button className="report-button" onClick={handleDownloadReport} disabled={isLoading}>
                    Descargar reporte Markdown
                  </button>
                )}
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
              onInput={(event) => resizeTextarea(event.target)}
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
                <button
                  type="submit"
                  className={`send-button ${input.trim() ? 'active' : ''}`}
                  disabled={!input.trim() || isLoading}
                  aria-label="Enviar"
                >
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
