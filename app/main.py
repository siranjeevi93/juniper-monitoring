import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request, BackgroundTasks, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import database, crypto, scheduler
from .collector import collect_and_parse, CollectionError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = __file__.rsplit("/", 1)[0]
templates = Jinja2Templates(directory=f"{BASE_DIR}/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Juniper Switch Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=f"{BASE_DIR}/static"), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/switches")


@app.get("/switches")
def list_switches(request: Request):
    switches = database.get_switches()
    enriched = []
    for sw in switches:
        latest = database.get_latest_collection(sw["id"])
        enriched.append({**sw, "latest": latest})
    return templates.TemplateResponse("index.html", {"request": request, "switches": enriched})


@app.post("/switches")
def add_switch(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(22),
    username: str = Form(...),
    password: str = Form(...),
):
    if database.get_switch_by_name(name):
        raise HTTPException(status_code=400, detail="A switch with this name already exists")
    password_enc = crypto.encrypt(password)
    switch_id = database.add_switch(name, host, port, username, password_enc)
    background_tasks.add_task(scheduler.collect_one, switch_id)
    return RedirectResponse(url="/switches", status_code=303)


@app.post("/switches/{switch_id}/delete")
def remove_switch(switch_id: int):
    database.delete_switch(switch_id)
    return RedirectResponse(url="/switches", status_code=303)


@app.post("/switches/{switch_id}/collect")
def trigger_collect(switch_id: int, background_tasks: BackgroundTasks):
    if not database.get_switch(switch_id):
        raise HTTPException(status_code=404, detail="Switch not found")
    background_tasks.add_task(scheduler.collect_one, switch_id)
    return {"status": "collection started"}


@app.get("/switches/{switch_id}")
def switch_dashboard(request: Request, switch_id: int):
    switch = database.get_switch(switch_id)
    if not switch:
        raise HTTPException(status_code=404, detail="Switch not found")
    return templates.TemplateResponse("dashboard.html", {"request": request, "switch": switch})


# ---- JSON API for the dashboard charts --------------------------------

@app.get("/api/switches/{switch_id}/summary")
def api_summary(switch_id: int):
    switch = database.get_switch(switch_id)
    if not switch:
        raise HTTPException(status_code=404, detail="Switch not found")
    latest = database.get_latest_collection(switch_id)
    if not latest:
        return {"switch": switch["name"], "status": "no_data"}
    return {
        "switch": switch["name"],
        "status": latest["status"],
        "error_message": latest["error_message"],
        "collected_at": latest["collected_at"],
        "summary": json.loads(latest["summary_json"]) if latest["summary_json"] else {},
        "raw": json.loads(latest["raw_json"]) if latest["raw_json"] else {},
    }


@app.get("/api/switches/{switch_id}/history")
def api_history(switch_id: int, metric: str, limit: int = 200):
    if not database.get_switch(switch_id):
        raise HTTPException(status_code=404, detail="Switch not found")
    return database.get_metric_history(switch_id, metric, limit)


@app.get("/api/switches/{switch_id}/collections")
def api_collections(switch_id: int, limit: int = 30):
    if not database.get_switch(switch_id):
        raise HTTPException(status_code=404, detail="Switch not found")
    return database.get_collection_history(switch_id, limit)
