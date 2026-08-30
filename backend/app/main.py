from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models.db import init_db
from app.routers import chat, execute, plan, report

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


@app.on_event("startup")
def on_startup() -> None:
    init_db()
