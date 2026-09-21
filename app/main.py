from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import models
from app.database import Base, engine
from app.routes import accounts, transactions, voice


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="PayGuard - Double Entry Financial Ledger API", lifespan=lifespan)

app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(voice.router)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())



@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}