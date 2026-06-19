"""
Context Agent — FastAPI Server

Entry point for the web backend. Serves the REST API and WebSocket
for the React frontend.

Run with: python -m backend.server
"""

import asyncio
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# Ensure the project root is in the path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from backend.ws_manager import ConnectionManager
from backend.orchestrator import Orchestrator
from models.state import ProjectState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── Global state ──────────────────────────────────────────────────────
ws_manager = ConnectionManager()
orchestrator = Orchestrator(ws_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    log.info("Context Agent backend starting on %s:%d", config.BACKEND_HOST, config.BACKEND_PORT)
    yield
    log.info("Context Agent backend shutting down")


# ── FastAPI App ───────────────────────────────────────────────────────
app = FastAPI(
    title="Context Agent",
    description="AI Coding Agent Backend",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Models ──────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str
    prompt: str = ""

class PromptRequest(BaseModel):
    prompt: str

class InputRequest(BaseModel):
    text: str

class PermissionResponse(BaseModel):
    granted: bool

class LoadProjectRequest(BaseModel):
    workspace_path: str

class FollowupRequest(BaseModel):
    text: str

class UpdateModelRequest(BaseModel):
    model_name: str


# ── REST Endpoints ────────────────────────────────────────────────────

@app.post("/api/settings/model")
async def update_model(req: UpdateModelRequest):
    """Update the global LLM model."""
    config.GROQ_MODEL = req.model_name
    
    # Re-initialize the Orchestrator's LLMClient so it picks up the new model
    if orchestrator.llm:
        from core.llm_client import LLMClient
        orchestrator.llm = LLMClient()
        if orchestrator.planner:
            orchestrator.planner.llm = orchestrator.llm
        if orchestrator.coder:
            orchestrator.coder.llm = orchestrator.llm
        if orchestrator.fixer:
            orchestrator.fixer.llm = orchestrator.llm
            
    return {"success": True, "model": req.model_name}

@app.get("/api/health")
async def health_check():
    """Check if the backend and Ollama are running."""
    from core.llm_client import LLMClient
    llm = LLMClient()
    health = await llm.health_check()
    return {
        "backend": "ok",
        "ollama": health,
    }


@app.get("/api/projects")
async def list_projects():
    """List all saved projects."""
    projects = ProjectState.list_projects(config.PROJECTS_DIR)
    return {"projects": projects}


@app.post("/api/project/create")
async def create_project(req: CreateProjectRequest):
    """Create a new project."""
    result = await orchestrator.create_project(req.name, req.prompt)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create project"))
    return result


@app.post("/api/project/load")
async def load_project(req: LoadProjectRequest):
    """Load an existing project."""
    result = await orchestrator.load_project(req.workspace_path)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", "Project not found"))
    return result


@app.get("/api/project/state")
async def get_project_state():
    """Get the current project state."""
    if not orchestrator.state:
        raise HTTPException(status_code=404, detail="No project loaded")
    return {"project": orchestrator.state.to_api_dict()}


@app.post("/api/project/followup")
async def project_followup(req: FollowupRequest):
    """Trigger a manual fix/followup for the project."""
    if not orchestrator.state:
        raise HTTPException(status_code=404, detail="No project loaded")
    result = await orchestrator.handle_manual_fix(req.text)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Followup failed"))
    return result


@app.post("/api/plan/generate")
async def generate_plan(req: PromptRequest):
    """Generate the implementation plan."""
    result = await orchestrator.generate_plan(req.prompt)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Plan generation failed"))
    return result


@app.post("/api/plan/approve")
async def approve_plan():
    """Approve the plan for execution."""
    result = await orchestrator.approve_plan()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Cannot approve plan"))
    return result


@app.post("/api/execute/all")
async def execute_all():
    """Execute all plan steps."""
    # Run execution in background so API responds immediately
    asyncio.create_task(orchestrator.execute_all())
    return {"status": "execution_started"}


@app.post("/api/execute/step/{step_number}")
async def execute_step(step_number: int):
    """Execute a specific plan step."""
    asyncio.create_task(orchestrator.execute_single_step(step_number))
    return {"status": "step_execution_started", "step": step_number}


@app.post("/api/process/input")
async def send_process_input(req: InputRequest):
    """Send input to the running process."""
    result = await orchestrator.send_input(req.text)
    return result


@app.post("/api/process/kill")
async def kill_process():
    """Kill the running process."""
    result = await orchestrator.cancel_execution()
    return result


@app.post("/api/permission/respond")
async def respond_permission(req: PermissionResponse):
    """Respond to a permission request."""
    await orchestrator.respond_permission(req.granted)
    return {"status": "ok"}


@app.get("/api/file/{file_path:path}")
async def get_file(file_path: str):
    """Get content of a workspace file."""
    content = orchestrator.get_file_content(file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"file_path": file_path, "content": content}


@app.get("/api/files")
async def list_files():
    """List all files in the workspace."""
    files = orchestrator.list_workspace_files()
    return {"files": files}


# ── WebSocket ─────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication with the frontend."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "input":
                # User sending input to the running process
                text = data.get("text", "")
                await orchestrator.send_input(text)

            elif msg_type == "permission":
                # User responding to a permission request
                granted = data.get("granted", False)
                await orchestrator.respond_permission(granted)

            elif msg_type == "cancel":
                # User requesting cancellation
                await orchestrator.cancel_execution()

            elif msg_type == "ping":
                await ws_manager.send_to(websocket, {"type": "pong"})

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        log.error("WebSocket error: %s", repr(e))
        await ws_manager.disconnect(websocket)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    """Start the backend server."""
    import uvicorn
    uvicorn.run(
        "backend.server:app",
        host=config.BACKEND_HOST,
        port=config.BACKEND_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
