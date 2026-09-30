# Runner

Servicio aparte que levanta el repo de la empresa en contenedores desechables. Es el **único** componente que toca Docker: el backend de AgenteQA nunca monta `docker.sock` y habla con el runner solo por HTTP.

Estado: solo está el contrato. La implementación es la pista B de `TRABAJO-PARALELO.md`.

## Contrato HTTP (congelado)

- Base: `http://127.0.0.1:8100`.
- Todas las requests llevan el header `X-Runner-Token: <RUNNER_TOKEN>`. Es un secreto compartido que está en el `.env` del backend y en el del runner. Sin él, la respuesta es `401`.

### `POST /runs`

```json
{"session_id": "abc", "repo_path": "/ruta/al/clone"}
```

- `200 {"run_id": "aqa-abc", "urls": ["http://127.0.0.1:18080"]}`: la app respondió al healthcheck.
- `422 {"detail": "sin docker-compose.yml ni Dockerfile"}`: no se sabe levantar el repo.
- `504 {"detail": "la app no respondio en 180s"}`: el healthcheck agotó el tiempo. Los contenedores se destruyen igual.

`urls` puede traer más de una URL si el compose publica varios puertos web. En ese caso el backend pausa y le pregunta al usuario cuál es la app.

### `GET /runs/{run_id}/logs?tail=200`

`200 {"logs": "..."}`: texto crudo de todos los servicios. **Puede contener secretos**, así que el backend lo pasa por `app.security.redact` antes de mandarlo a un prompt.

### `DELETE /runs/{run_id}`

`200 {"status": "stopped"}`. Borra contenedores, redes y volúmenes del proyecto (`docker compose -p <run_id> down -v`).

## Reglas de seguridad

- Nombre de proyecto: `aqa-<session_id>`. Cada ejecución queda aislada de las demás.
- El runner genera un override de compose que aplica a cada servicio:
  - `mem_limit`, `cpus`, `pids_limit`
  - `security_opt: ["no-new-privileges:true"]`
  - `privileged: false`
  - puertos publicados solo en `127.0.0.1`
- El `.env` se genera siempre con valores dummy desde `.env.example`. Nunca se usa un `.env` que ya venga en el repo.
- Red abierta en el MVP. El corte de salida a internet queda para la migración a instancia (ver `PLAN.md`, decisiones).
