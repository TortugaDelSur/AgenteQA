import { useEffect, useRef, useState } from 'react';
import {
  answerSweepQuestion, downloadReport, executePlan, getChatHistory, sendChat, submitSweepLogin, sweepPlan,
} from './api/client';

const welcomeMessage = {
  role: 'assistant',
  content: 'Hola, soy AgenteQA. Puedo ayudarte a diseñar pruebas para tu web o API. Cuéntame qué quieres validar.',
};

const SESSION_STORAGE_KEY = 'agenteqa_session_id';

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

function SweepPanel({ events, question, onAnswer, loginRequired, onSubmitLogin, isLoading }) {
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
            <p className="sweep-error">{event.url}: {event.detail}</p>
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
  const chatScrollRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    const chatScroll = chatScrollRef.current;
    if (chatScroll) {
      chatScroll.scrollTop = chatScroll.scrollHeight;
    }
  }, [messages, isLoading, error, plan]);

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
        setMessages(history.messages.length ? history.messages : [welcomeMessage]);
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
    setSessionId('');
    setMessages([welcomeMessage]);
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

            <SweepPanel
              events={sweepEvents}
              question={sweepQuestion}
              onAnswer={handleAnswerSweepQuestion}
              loginRequired={sweepLoginRequired}
              onSubmitLogin={handleSubmitSweepLogin}
              isLoading={isLoading}
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
