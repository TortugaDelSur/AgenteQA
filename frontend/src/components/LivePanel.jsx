import { useEffect, useState } from 'react';
import {
  answerExecuteQuestion, executePlan, getExecuteState, openLiveSocket, submitExecuteLogin,
} from '../api/client';

const PAUSE_TEXT = {
  question: 'El agente tiene una duda',
  unreachable: 'La app no responde',
};

// Vista en vivo de solo lectura: se ve el navegador, no se lo controla. La unica interaccion es
// responder cuando el agente pausa (mismo cuadro que el barrido: clases sweep-*).
export default function LivePanel({ sessionId, onProgress }) {
  const [frame, setFrame] = useState(null);
  const [step, setStep] = useState(null);
  const [paused, setPaused] = useState(null);
  const [done, setDone] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [answer, setAnswer] = useState('');
  const [loginUser, setLoginUser] = useState('');
  const [loginPass, setLoginPass] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // tras refrescar, la pausa ya no llega por el WS: se pide al backend.
  useEffect(() => {
    if (!sessionId) return;
    getExecuteState(sessionId).then((data) => data.paused && setPaused(data.paused)).catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return undefined;
    const socket = openLiveSocket(sessionId, (message) => {
      if (message.type === 'launching') {
        setLaunching(true);
        setDone(false);
      } else if (message.type === 'frame') {
        setFrame(message.data);
        setLaunching(false);
        setDone(false);
      } else if (message.type === 'step') {
        setStep(message);
      } else if (message.type === 'paused') {
        setPaused(message);
      } else if (message.type === 'done') {
        setDone(true);
        setStep(null);
      }
    });
    return () => socket.close();
  }, [sessionId]);

  if (!frame && !paused && !launching) return null;

  const resume = async (send) => {
    setBusy(true);
    setError('');
    try {
      await send();
      setPaused(null);
      await executePlan(sessionId, onProgress);
    } catch (err) {
      setError(err.message || 'No se pudo retomar la ejecución');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="sweep-panel">
      <span className="eyebrow">Navegador en vivo</span>
      <p className="sweep-visiting">
        {done
          ? 'Ejecución terminada.'
          : launching
            ? 'Levantando el repo localmente (puede tardar unos minutos)...'
            : step && `${step.test_case_id} · paso ${step.index}: ${step.action} ${step.target}`}
      </p>
      {frame && <img className="result-screenshot" src={`data:image/jpeg;base64,${frame}`} alt="Navegador en vivo" />}
      {error && <p className="sweep-error">{error}</p>}
      {paused && paused.reason !== 'login' && (
        <div className="sweep-question">
          <p><strong>{PAUSE_TEXT[paused.reason]}</strong>: {paused.detail}</p>
          <textarea
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            rows={2}
            placeholder="Tu respuesta..."
          />
          <button
            disabled={!answer.trim() || busy}
            onClick={() => resume(async () => {
              await answerExecuteQuestion(sessionId, answer);
              setAnswer('');
            })}
          >
            Responder y continuar
          </button>
        </div>
      )}
      {paused?.reason === 'login' && (
        <div className="sweep-login">
          <p>
            <strong>{paused.detail}</strong> pide iniciar sesión y no estaba definido antes.
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
            disabled={!loginUser.trim() || !loginPass.trim() || busy}
            onClick={() => resume(async () => {
              await submitExecuteLogin(sessionId, loginUser, loginPass);
              setLoginUser('');
              setLoginPass('');
            })}
          >
            Iniciar sesión y continuar
          </button>
        </div>
      )}
    </section>
  );
}
