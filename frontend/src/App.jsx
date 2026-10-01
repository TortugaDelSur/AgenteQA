import { useEffect, useRef, useState } from 'react';
import {
  answerSweepQuestion, downloadReport, executePlan, forgetRepo, getChatHistory, getIntegrations, sendChat,
  submitSweepLogin, sweepPlan,
} from './api/client';
import IntegrationsPage from './components/IntegrationsPage';
import LivePanel from './components/LivePanel';
import RepoPicker, { RepoNeedsToken } from './components/RepoPicker';

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
                <span className="step-marker">{index + 1}</span>
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

function SweepPanel({ events, question, onAnswer, loginRequired, onSubmitLogin, isLoading, onRetry }) {
  const [answer, setAnswer] = useState('');
  const [loginUser, setLoginUser] = useState('');
  const [loginPass, setLoginPass] = useState('');
  if (!events.length && !question && !loginRequired) return null;

  return (
    <section className="sweep-panel">
      <span className="eyebrow">Barrido de pantallas</span>
      {events.map((event, index) => (
        <div className="sweep-event" key={index}>
          {event.type === 'error' ? (
            <>
              <p className="sweep-error">{event.url === 'plan' ? event.detail : `${event.url}: ${event.detail}`}</p>
              {event.retry && (
                <button type="button" className="execute-button" onClick={onRetry} disabled={isLoading}>
                  Reintentar generar el plan
                </button>
              )}
            </>
          ) : event.type === 'launching' ? (
            <p className="sweep-visiting">{event.detail}</p>
          ) : event.type === 'page_result' ? (
            <>
              <p>{event.url} — {event.summary}</p>
              {event.screenshot_b64 && (
                <img src={`data:image/png;base64,${event.screenshot_b64}`} alt={event.url} />
              )}
            </>
          ) : (
            <p className="sweep-visiting">Visitando {event.url}...</p>
          )}
        </div>
      ))}
      {question && (
        <div className="sweep-question">
          <p><strong>{question.url}</strong>: {question.question}</p>
          <textarea
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            rows={2}
            placeholder="Tu respuesta..."
          />
          <button
            disabled={!answer.trim() || isLoading}
            onClick={() => {
              onAnswer(answer);
              setAnswer('');
            }}
          >
            Responder
          </button>
        </div>
      )}
      {loginRequired && (
        <div className="sweep-login">
          <p>
            <strong>{loginRequired.url}</strong> pide iniciar sesión y no estaba definido antes.
            Ingresá credenciales de prueba (no reales) para continuar.
          </p>
          <input
            type="text"
            value={loginUser}
            onChange={(event) => setLoginUser(event.target.value)}
            placeholder="Usuario de prueba"
          />
          <input
            type="password"
            value={loginPass}
            onChange={(event) => setLoginPass(event.target.value)}
            placeholder="Contraseña de prueba"
          />
          <button
            disabled={!loginUser.trim() || !loginPass.trim() || isLoading}
            onClick={() => {
              onSubmitLogin(loginUser, loginPass);
              setLoginUser('');
              setLoginPass('');
            }}
          >
            Iniciar sesión y continuar
          </button>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState([welcomeMessage]);
  const [input, setInput] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [hasStarted, setHasStarted] = useState(() => {
    try {
      return Boolean(localStorage.getItem(SESSION_STORAGE_KEY));
    } catch {
      return false;
    }
  });
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
  const [sweepEvents, setSweepEvents] = useState([]);
  const [sweepQuestion, setSweepQuestion] = useState(null);
  const [sweepLoginRequired, setSweepLoginRequired] = useState(null);
  const [view, setView] = useState('chat');
  const [isLightMode, setIsLightMode] = useState(() => {
    try {
      return localStorage.getItem('agenteqa_theme') === 'light';
    } catch {
      return false;
    }
  });
  // null mientras carga: no se muestra el bloqueo hasta saber si hay integraciones.
  const [integrations, setIntegrations] = useState(null);
  const chatScrollRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    const chatScroll = chatScrollRef.current;
    if (chatScroll) {
      chatScroll.scrollTop = chatScroll.scrollHeight;
    }
  }, [messages, isLoading, error, plan, context.wants_repo, context.repo_url, integrations]);

  useEffect(() => {
    getIntegrations().then(setIntegrations).catch(() => setIntegrations(null));
  }, []);

  const hasIntegration = Boolean(integrations?.github || integrations?.bitbucket);
  useEffect(() => {
    try {
      localStorage.setItem('agenteqa_theme', isLightMode ? 'light' : 'dark');
    } catch {
      // El tema sigue funcionando durante esta sesión si localStorage no está disponible.
    }
  }, [isLightMode]);
  // el usuario dijo que tiene repo y todavia no lo eligio: aviso de token o lista de repos bajo el chat.
  const needsRepo = Boolean(context.wants_repo) && !context.repo_url;
  const repoName = context.repo_url ? context.repo_url.replace(/^https:\/\/[^/]+\//, '') : '';

  const handleRepoSelected = (data) => {
    setSessionId(data.session_id);
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, data.session_id);
    } catch {
      // localStorage no disponible: la sesion sigue en memoria
    }
    setContext(data.context);
    appendMessage('assistant', data.reply);
    if (data.ready_for_plan && !plan) runSweepPlan(data.session_id);
  };

  // recupera la conversacion si el usuario refresca la pagina (no recupera plan/resultados,
  // el backend no tiene un endpoint para volver a pedir el ultimo plan generado sin regenerarlo).
  useEffect(() => {
    let savedSessionId;
    try {
      savedSessionId = localStorage.getItem(SESSION_STORAGE_KEY);
    } catch {
      return;
    }
    if (!savedSessionId) return;

    getChatHistory(savedSessionId)
      .then((history) => {
        setSessionId(history.session_id);
        const storedMessages = history.messages || [];
        const hasWelcomeMessage = storedMessages.some(
          (message) => message.role === welcomeMessage.role && message.content === welcomeMessage.content,
        );
        setMessages(hasWelcomeMessage ? storedMessages : [welcomeMessage, ...storedMessages]);
        setHasStarted(true);
        setContext(history.context);
      })
      .catch(() => {
        try {
          localStorage.removeItem(SESSION_STORAGE_KEY);
        } catch {
          // localStorage no disponible (modo privado, etc): no hay nada que limpiar
        }
      });
  }, []);

  const appendMessage = (role, content) => {
    setMessages((current) => [...current, { role, content }]);
  };

  const resetChat = () => {
    if (sessionId) forgetRepo(sessionId).catch(() => {});
    setSessionId('');
    setMessages([welcomeMessage]);
    setHasStarted(false);
    setSidebarOpen(false);
    setInput('');
    setPlan(null);
    setResults(null);
    setExecutionProgress(null);
    setReport(null);
    setContext({ objetivo: false, acceso: false, alcance: false, repo: false, target_url: null });
    setError('');
    setSweepEvents([]);
    setSweepQuestion(null);
    setSweepLoginRequired(null);
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

  const runSweepPlan = async (id) => {
    setIsLoading(true);
    setError('');

    try {
      await sweepPlan(id, (event) => {
        if (event.type === 'question') {
          setSweepQuestion({ url: event.url, question: event.question });
        } else if (event.type === 'login_required') {
          setSweepLoginRequired({ url: event.url });
        } else if (event.type === 'plan_ready') {
          setPlan(event.plan);
          appendMessage('assistant', `Plan generado: ${event.plan.test_cases.length} casos de prueba.`);
        } else {
          setSweepEvents((current) => [...current, event]);
        }
      });
    } catch (err) {
      setError(err.message || 'No se pudo generar el plan');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmitSweepLogin = async (username, password) => {
    if (!sessionId || !sweepLoginRequired) return;

    setError('');
    try {
      await submitSweepLogin(sessionId, username, password);
      setSweepLoginRequired(null);
      await runSweepPlan(sessionId);
    } catch (err) {
      setError(err.message || 'No se pudo iniciar sesion');
    }
  };

  const handleAnswerSweepQuestion = async (answerText) => {
    if (!sessionId || !sweepQuestion) return;

    setError('');
    try {
      await answerSweepQuestion(sessionId, answerText);
      appendMessage('user', answerText);
      setSweepQuestion(null);
      await runSweepPlan(sessionId);
    } catch (err) {
      setError(err.message || 'No se pudo enviar la respuesta');
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
      appendMessage(
        'assistant',
        data.paused
          ? `Ejecución pausada tras ${data.results.length} casos: necesito tu respuesta para seguir.`
          : `Ejecución completada: ${data.results.length} casos procesados.`,
      );
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

    setHasStarted(true);
    setSidebarOpen(true);
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
        await runSweepPlan(data.session_id);
        return;
      }
    } catch (err) {
      setError(err.message || 'No se pudo enviar el mensaje');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={`claude-app ${isLightMode ? 'theme-light' : 'theme-dark'} ${hasStarted ? 'has-started' : 'is-initial'} ${sidebarOpen ? 'sidebar-is-open' : 'sidebar-is-closed'}`}>
      <div className="ambient-glow" aria-hidden="true">
        <span className="glow glow-1" />
        <span className="glow glow-2" />
        <span className="glow glow-3" />
        <span className="glow glow-4" />
      </div>
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-visible' : 'sidebar-hidden'}`}>
        <div className="brand">
          <div className="brand-mark">A</div>
          <span>AgenteQA</span>
        </div>

        <nav className="sidebar-nav" aria-label="Secciones">
          <button
            type="button"
            className={`nav-item ${view === 'chat' ? 'active' : ''}`}
            aria-current={view === 'chat' ? 'page' : undefined}
            onClick={() => setView('chat')}
          >
            <span className="nav-icon" aria-hidden="true">◆</span>
            <span className="nav-label">Agente</span>
          </button>
          <button
            type="button"
            className={`nav-item ${view === 'integrations' ? 'active' : ''}`}
            aria-current={view === 'integrations' ? 'page' : undefined}
            onClick={() => setView('integrations')}
          >
            <span className="nav-icon" aria-hidden="true">⚙</span>
            <span className="nav-label">Integraciones</span>
            <span className={`nav-dot ${hasIntegration ? 'on' : ''}`} aria-label={hasIntegration ? 'conectado' : 'sin conectar'} />
          </button>
        </nav>

        {view === 'chat' && repoName && (
          <div className="repo-chip">
            <span className="repo-chip-label">Repositorio</span>
            <strong title={context.repo_url}>{repoName}</strong>
            <button type="button" className="link-button" onClick={resetChat}>Cambiar (nueva sesión)</button>
          </div>
        )}

        {view === 'chat' && <QaStepper context={context} hasPlan={Boolean(plan)} />}
        <div className="sidebar-bottom">
          <button
            type="button"
            className="theme-toggle-button"
            onClick={() => setIsLightMode((light) => !light)}
            aria-label={isLightMode ? 'Cambiar a modo oscuro' : 'Cambiar a modo claro'}
            title={isLightMode ? 'Modo oscuro' : 'Modo claro'}
          >
            <span aria-hidden="true">{isLightMode ? '☾' : '☀'}</span>
          </button>
          {view === 'chat' && (
            <button type="button" className="new-session-button" onClick={resetChat}>
              Reiniciar sesión
            </button>
          )}
        </div>
      </aside>

      <main className="conversation-area">
        {!hasStarted && (
          <button
            type="button"
            className="sidebar-toggle"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-label={sidebarOpen ? 'Ocultar barra lateral' : 'Mostrar barra lateral'}
            title={sidebarOpen ? 'Ocultar barra lateral' : 'Mostrar barra lateral'}
          >
            <span aria-hidden="true">{sidebarOpen ? '‹' : '☰'}</span>
          </button>
        )}
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
        {view === 'integrations' ? (
          <IntegrationsPage integrations={integrations} onChange={setIntegrations} onBack={() => setView('chat')} />
        ) : (
        <section className={`chat-content ${hasStarted ? 'chat-started' : 'chat-initial'}`}>
          <div className="chat-scroll" ref={chatScrollRef}>
            {!hasStarted ? (
              <div className="initial-welcome">
                <h1>Hola, muy buenas</h1>
                <p>¿En qué puedo ayudarte?</p>
              </div>
            ) : (
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
            )}

            {error && <div className="error-message">{error}</div>}

            {needsRepo && !hasIntegration && <RepoNeedsToken onGoToIntegrations={() => setView('integrations')} />}
            {needsRepo && hasIntegration && (
              <RepoPicker sessionId={sessionId} onSelected={handleRepoSelected} onGoToIntegrations={() => setView('integrations')} />
            )}

            <SweepPanel
              events={sweepEvents}
              question={sweepQuestion}
              onAnswer={handleAnswerSweepQuestion}
              loginRequired={sweepLoginRequired}
              onSubmitLogin={handleSubmitSweepLogin}
              isLoading={isLoading}
              onRetry={() => {
                // el error viejo con boton se quita; el barrido ya hecho se conserva en el backend.
                setSweepEvents((current) => current.filter((event) => !event.retry));
                runSweepPlan(sessionId);
              }}
            />

            <LivePanel
              sessionId={sessionId}
              onProgress={(progress) => setResults((current) => [...(current || []), progress.result])}
            />

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
                      <div className="result-body">
                        <strong>{result.test_case_id}</strong>
                        <p>{result.detail}</p>
                        {result.suspected_cause && (
                          <p className="result-cause">
                            <strong>Causa probable</strong> ({result.suspected_cause.confidence}):{' '}
                            <code>
                              {result.suspected_cause.file}
                              {result.suspected_cause.line ? `:${result.suspected_cause.line}` : ''}
                            </code>
                            {' — '}{result.suspected_cause.explanation}
                          </p>
                        )}
                        {result.screenshot_b64 && (
                          <img
                            className="result-screenshot"
                            src={`data:image/png;base64,${result.screenshot_b64}`}
                            alt={`Captura de ${result.test_case_id}`}
                          />
                        )}
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
              placeholder={needsRepo ? 'Elige el repositorio en la lista, o escribe si prefieres seguir sin repo...' : 'Escribe un mensaje a AgenteQA...'}
              rows={1}
              aria-label="Mensaje"
            />
            <div className="composer-footer">
              <div className="composer-actions">
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
        </section>
        )}
      </main>
    </div>
  );
}
