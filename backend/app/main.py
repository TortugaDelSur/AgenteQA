import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import live
from app.models.db import init_db
from app.repo import launch
from app.routers import chat, execute, plan, repo, report

app = FastAPI(title="AgenteQA")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(plan.router)
app.include_router(execute.router)
app.include_router(report.router)
app.include_router(live.router)
app.include_router(repo.router)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    # apaga repos levantados que nadie mira (pagina cerrada, sin internet); ver repo/launch.py.
    app.state.reaper = asyncio.create_task(launch.reap_forever())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    app.state.reaper.cancel()
    await launch.stop_all()  # no dejar contenedores del runner huerfanos al cerrar el backend
