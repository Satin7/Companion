import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.deepseek_client import DeepseekClient
from app.trigger_engine import TriggerEngine
from app.models import StartSessionRequest, TriggerRequest
from app.sessions import SessionManager

app = FastAPI(title="Companion - Active AI Chat Framework")

deepseek = DeepseekClient(
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)
sqlite_db = os.getenv("SQLITE_DB_PATH", "") or None
session_manager = SessionManager(db_path=sqlite_db)
engine = TriggerEngine(deepseek_client=deepseek, session_manager=session_manager)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/sessions/start")
async def start_session(req: StartSessionRequest):
    session_id = session_manager.create_session(req.user_id, metadata=req.metadata)
    return {"session_id": session_id}


@app.post("/triggers/evaluate")
async def evaluate_trigger(req: TriggerRequest):
    ok = await engine.evaluate_trigger(req)
    return {"triggered": ok}


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    engine.register_connection(user_id, websocket)
    try:
        while True:
            # simple echo/keepalive receiver
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        engine.unregister_connection(user_id, websocket)
