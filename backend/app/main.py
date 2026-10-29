from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, UploadFile, File, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import json
import os
import asyncio
from datetime import datetime
import logging
from typing import Dict, List

from .detector import ProctorDetector
from .db import Database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize global instances
detector: ProctorDetector = None
db: Database = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global detector, db
    logger.info("🚀 Starting Live Proctoring Server")
    try:
        detector = ProctorDetector()
        db = Database()
        db.connect()
        logger.info("✅ All services initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize services: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Live Proctoring Server")
    try:
        if db:
            db.close()
        logger.info("✅ Graceful shutdown completed")
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")

app = FastAPI(
    title="Live Proctoring API",
    description="Real-time exam proctoring with AI detection",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_data: Dict[str, dict] = {}
    
    async def connect(self, client_id: str, websocket: WebSocket):
        try:
            # If there's an existing connection for this client_id, close it first
            existing = self.active_connections.get(client_id)
            if existing:
                try:
                    logger.info(f"🔄 Closing existing connection for {client_id} (duplicate connection detected)")
                    await existing.close(code=1008, reason="New connection established for same client")
                except Exception as close_err:
                    logger.debug(f"Could not cleanly close existing connection: {close_err}")
                # Remove from active connections
                del self.active_connections[client_id]
            
            await websocket.accept()
            self.active_connections[client_id] = websocket
            
            # Load existing warning count from DB, or initialize to 0
            warning_count = 0
            last_warning_time = None
            try:
                session = db.get_session(client_id)
                if session and session.get('warning_count') is not None:
                    warning_count = session['warning_count']
                    if session.get('last_warning_time'):
                        last_warning_time = datetime.fromisoformat(session['last_warning_time'])
                    logger.info(f"✅ Loaded existing session state: {warning_count}/3 warnings")
            except Exception as e:
                logger.warning(f"Could not load session state from DB: {e}")
            
            self.client_data[client_id] = {
                "connected_at": datetime.now(),
                "frames_received": 0,
                "violations": 0,
                "warning_count": warning_count,
                "max_warnings": 3,
                "session_ended": False,
                "last_warning_time": last_warning_time,
                "warning_expiry_seconds": 8  # Warnings expire after 8s of no new violations (quicker re-warn)
            }
            logger.info(f"✅ Client {client_id} connected (warnings: {warning_count}/3)")
        except Exception as e:
            logger.error(f"❌ Connection error for {client_id}: {e}")
            raise
    
    async def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.client_data:
            del self.client_data[client_id]
        logger.info(f"✅ Client {client_id} disconnected")
    
    async def send_message(self, client_id: str, message: dict):
        if client_id not in self.active_connections:
            logger.warning(f"⚠️ Client {client_id} not in active connections. Cannot send message: {message.get('status', 'unknown')}")
            return False
        
        try:
            ws = self.active_connections[client_id]
            await ws.send_json(message)
            logger.debug(f"✅ Message sent to {client_id}: {message.get('status', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"❌ Error sending message to {client_id}: {type(e).__name__}: {e}")
            # Force disconnect on send failure
            try:
                await self.disconnect(client_id)
            except Exception as disc_err:
                logger.debug(f"Error during disconnect after send failure: {disc_err}")
            return False

    def get_active_clients(self) -> List[str]:
        return list(self.active_connections.keys())

manager = ConnectionManager()

# Routes

@app.get("/")
async def root():
    return {"message": "Live Proctoring API", "status": "running"}



@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "live-proctoring",
        "timestamp": datetime.now().isoformat(),
        "active_clients": len(manager.get_active_clients())
    }

@app.get("/api/clients")
async def list_clients():
    """Get list of all active clients"""
    try:
        return {
            "active_clients": manager.get_active_clients(),
            "count": len(manager.get_active_clients()),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error listing clients: {e}")
        raise HTTPException(status_code=500, detail="Failed to list clients")

@app.post("/api/session/start")
async def start_session(client_id: str = Query(..., description="Unique client identifier")):
    """Start a new proctoring session"""
    try:
        db.create_session(client_id, datetime.now())
        logger.info(f"Session started for client: {client_id}")
        return {
            "status": "session_started",
            "client_id": client_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error starting session for {client_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to start session")

@app.post("/api/session/end")
async def end_session(client_id: str = Query(..., description="Unique client identifier")):
    """End a proctoring session"""
    try:
        # end the session and return a summary of violations
        db.end_session(client_id, datetime.now())
        logger.info(f"Session ended for client: {client_id}")
        try:
            violations = db.get_violations(client_id) or []
            severity = summarize_violations(violations)
        except Exception:
            violations = []
            severity = {}

        return {
            "status": "session_ended",
            "client_id": client_id,
            "timestamp": datetime.now().isoformat(),
            "violation_count": len(violations),
            "severity_summary": severity,
            "violations": violations
        }
    except Exception as e:
        logger.error(f"Error ending session for {client_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to end session")


@app.post("/api/session/rebind")
async def rebind_session(old_client_id: str = Query(None, description="Current client id to rebind from"), new_client_id: str = Query(..., description="New client id to bind to")):
    """Rebind an active websocket/session from old_client_id to new_client_id.
    Useful when the frontend refreshes or wants to change the student id via HTTP.
    """
    try:
        if not new_client_id:
            raise HTTPException(status_code=400, detail="new_client_id is required")

        # If there is an existing websocket for new_client_id, close it
        existing_new = manager.active_connections.get(new_client_id)
        if existing_new:
            try:
                await existing_new.close(code=1000)
            except Exception:
                pass

        # If there is an active websocket mapped to old_client_id, move it
        ws = None
        if old_client_id:
            ws = manager.active_connections.get(old_client_id)

        if ws:
            # move websocket mapping
            manager.active_connections[new_client_id] = ws
            if old_client_id in manager.active_connections:
                try:
                    del manager.active_connections[old_client_id]
                except Exception:
                    pass

            # move client data
            if old_client_id in manager.client_data:
                manager.client_data[new_client_id] = manager.client_data.pop(old_client_id)
        else:
            # no active ws for old id; ensure client_data exists for new id
            manager.client_data.setdefault(new_client_id, {
                'connected_at': datetime.now(),
                'frames_received': 0,
                'violations': 0,
                'warning_count': 0,
                'max_warnings': 3,
                'session_ended': False,
                'last_warning_time': None,
                'warning_expiry_seconds': 8
            })

        # Ensure DB session exists for new id
        try:
            db.create_session(new_client_id, datetime.now())
        except Exception:
            logger.debug('Session creation may have failed or session already exists')

        logger.info(f"🔁 Rebound session {old_client_id} -> {new_client_id}")
        return {
            'status': 'rebound',
            'old_client_id': old_client_id,
            'new_client_id': new_client_id,
            'timestamp': datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rebinding session {old_client_id} -> {new_client_id}: {e}")
        raise HTTPException(status_code=500, detail='Failed to rebind session')

@app.post("/api/tab_switch")
async def handle_tab_switch(client_id: str = Query(..., description="Client ID"), state: str = Query(..., description="State: hidden, visible, blur, focus")):
    """HTTP endpoint for tab-switch events (alternative to WebSocket for better reliability)."""
    try:
        if not client_id or not state:
            raise HTTPException(status_code=400, detail="client_id and state are required")
        
        now = datetime.now()
        cd = manager.client_data.get(client_id, {})
        logger.info(f"📌 [TAB_SWITCH] Received tab_switch event for {client_id}: state={state}")
        
        # Check if session already ended
        if cd.get('session_ended', False):
            logger.warning(f"⚠️ [TAB_SWITCH] Session already ended for {client_id}")
            return {"status": "session_ended", "message": "Session already ended"}
        
        # Check if warning should be issued for tab switch
        last_warn = cd.get('last_warning_time')
        warning_count = cd.get('warning_count', 0)
        max_warnings = cd.get('max_warnings', 3)
        expiry = cd.get('warning_expiry_seconds', 8)
        
        # Only hidden/blur states trigger warnings
        if state in ['hidden', 'blur']:
            # Check if enough time has passed since last warning
            if last_warn is None or (now - last_warn).total_seconds() > expiry:
                warning_count += 1
                cd['last_warning_time'] = now
                cd['warning_count'] = warning_count
                
                # Persist to DB
                try:
                    db.update_session_warning_count(client_id, warning_count, now)
                    logger.info(f"✅ [TAB_SWITCH] Persisted warning to DB: client={client_id}, count={warning_count}")
                except Exception as e:
                    logger.error(f"❌ [TAB_SWITCH] Failed to persist warning: {e}")
                
                manager.client_data[client_id] = cd
                logger.warning(f"🚨 [TAB_SWITCH] WARNING ISSUED for {client_id}: state={state} | Count: {warning_count}/{max_warnings}")
                
                # Check if max warnings reached
                if warning_count >= max_warnings:
                    cd['session_ended'] = True
                    logger.critical(f"🛑 [SESSION_END] {client_id} reached max warnings (3) - Session ENDED")
                    return {"status": "session_ended", "warning_count": warning_count, "message": "Session ended: 3 warnings have been issued"}
                
                return {"status": "warning", "warning_count": warning_count, "warnings_remaining": max_warnings - warning_count}
            else:
                elapsed = (now - last_warn).total_seconds()
                logger.debug(f"⏳ [TAB_SWITCH] Grace period active for {client_id}: {elapsed:.1f}s elapsed, {expiry - elapsed:.1f}s remaining")
                return {"status": "grace_period", "grace_remaining": max(0, expiry - elapsed)}
        else:
            logger.debug(f"ℹ️ [TAB_SWITCH] Visible/focus state for {client_id} - no warning")
            return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ [TAB_SWITCH] Error handling tab_switch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/report/{client_id}")
async def get_report(client_id: str):
    """Get violation report for a client"""
    try:
        violations = db.get_violations(client_id)
        session = db.get_session(client_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Compute aggregated metrics from violation details if available
        integrity_vals = []
        visibility_vals = []
        for v in violations:
            try:
                details = v.get('details')
                if isinstance(details, str):
                    import json as _json
                    details_obj = _json.loads(details)
                else:
                    details_obj = details or {}
                if details_obj.get('integrity_score') is not None:
                    integrity_vals.append(float(details_obj.get('integrity_score')))
                if details_obj.get('visibility_pct') is not None:
                    visibility_vals.append(float(details_obj.get('visibility_pct')))
            except Exception:
                continue

        integrity_avg = round(sum(integrity_vals) / len(integrity_vals), 2) if integrity_vals else None
        visibility_avg = round(sum(visibility_vals) / len(visibility_vals), 2) if visibility_vals else None

        return {
            "client_id": client_id,
            "session_duration": str(session.get('duration', 'N/A')),
            "violation_count": len(violations),
            "violations": violations,
            "severity_summary": summarize_violations(violations),
            "integrity_score_avg": integrity_avg,
            "visibility_pct_avg": visibility_avg,
            "generated_at": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating report for {client_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate report")

@app.get("/api/violations/{client_id}")
async def get_violations(client_id: str, v_type: str = None):
    """Get all violations for a client. Optionally filter by `v_type` (e.g. tab_switch)."""
    try:
        violations = db.get_violations(client_id)
        if v_type:
            filtered = [v for v in violations if (v.get('violation_type') == v_type or (v.get('details') and isinstance(v.get('details'), str) and v_type in v.get('details')))]
            return {
                "client_id": client_id,
                "filter": v_type,
                "count": len(filtered),
                "violations": filtered
            }
        return {
            "client_id": client_id,
            "count": len(violations),
            "violations": violations
        }
    except Exception as e:
        logger.error(f"Error retrieving violations: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve violations")


@app.get('/api/session/summary')
async def session_summary(client_id: str = Query(..., description='Client id to summarize')):
    """Return aggregated violation counts for a session without ending it."""
    try:
        violations = db.get_violations(client_id)
        summary = summarize_violations(violations)
        return {
            'client_id': client_id,
            'violation_count': len(violations),
            'severity_summary': summary,
            'violations': violations[:50]  # sample recent violations (limit 50)
        }
    except Exception as e:
        logger.error(f'Error generating session summary for {client_id}: {e}')
        raise HTTPException(status_code=500, detail='Failed to generate session summary')





@app.get("/api/evidence")
async def list_evidence():
    """List saved evidence image files (admin)"""
    import os
    try:
        evidence_dir = os.path.join(os.getcwd(), 'data', 'evidence')
        if not os.path.exists(evidence_dir):
            return {"files": [], "count": 0}

        files = []
        for fname in sorted(os.listdir(evidence_dir), reverse=True):
            full = os.path.join(evidence_dir, fname)
            try:
                stat = os.stat(full)
                files.append({
                    "filename": fname,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except Exception:
                continue

        return {"files": files, "count": len(files)}
    except Exception as e:
        logger.error(f"Error listing evidence: {e}")
        raise HTTPException(status_code=500, detail="Failed to list evidence")


@app.get("/api/evidence/{filename}")
async def download_evidence(filename: str):
    """Download a specific evidence file"""
    import os
    from fastapi.responses import FileResponse

    try:
        evidence_dir = os.path.join(os.getcwd(), 'data', 'evidence')
        # prevent path traversal
        safe_path = os.path.normpath(os.path.join(evidence_dir, filename))
        if not safe_path.startswith(os.path.normpath(evidence_dir)):
            raise HTTPException(status_code=400, detail="Invalid filename")
        if not os.path.exists(safe_path):
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(path=safe_path, media_type='image/jpeg', filename=filename)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving evidence file {filename}: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve evidence file")

@app.delete("/api/session/{client_id}")
async def delete_session(client_id: str):
    """Delete a session and all associated data"""
    try:
        db.delete_session(client_id)
        logger.info(f"Session deleted for {client_id}")
        return {
            "status": "session_deleted",
            "client_id": client_id
        }
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete session")

# WebSocket endpoint
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for real-time frame processing"""
    logger.info(f"🔌 WebSocket connection attempt from {client_id}")
    try:
        await manager.connect(client_id, websocket)
    except Exception as e:
        logger.error(f"❌ Failed to accept WebSocket connection for {client_id}: {e}")
        try:
            await websocket.close(code=1011, reason="Connection setup failed")
        except:
            pass
        return
    
    try:
        while True:
            # Receive either a binary frame or a text config message
            msg = await websocket.receive()
            # clear/reset per-loop data buffer; may be set by decoded frame_b64
            data = None

            # Text messages carry JSON config
            if msg.get('type') == 'websocket.receive' and 'text' in msg and msg.get('text'):
                try:
                    payload = json.loads(msg.get('text'))
                    # Accept base64-encoded frames sent as text when binary frames fail on some clients
                    if isinstance(payload, dict) and payload.get('type') == 'frame_b64' and payload.get('data'):
                        try:
                            import base64
                            data = base64.b64decode(payload.get('data'))
                            logger.info(f"📥 Received frame_b64 from {client_id}: {len(data)} bytes")
                            # proceed to detection below using 'data' variable
                        except Exception:
                            logger.exception('Failed to decode frame_b64')
                            data = None
                        # do not `continue` here - let the shared detection handling below process `data`
                    # Support client-side re-registration: a client can send a 'register'
                    # message with a new client_id to rebind this websocket to that id.
                    if isinstance(payload, dict) and payload.get('type') == 'register':
                        new_id = payload.get('client_id')
                        if new_id:
                            if new_id != client_id:
                                logger.info(f"🔁 [REGISTER] Rebinding websocket from {client_id} -> {new_id}")
                            else:
                                logger.info(f"✅ [REGISTER] Client {new_id} confirmed registration (same ID)")
                            # close any existing websocket for the new_id
                            existing = manager.active_connections.get(new_id)
                            if existing and existing is not websocket:
                                try:
                                    await existing.close(code=1000)
                                except Exception:
                                    pass

                            # move connection mapping and client_data
                            manager.active_connections[new_id] = websocket
                            # transfer client_data if present
                            if client_id in manager.client_data:
                                manager.client_data[new_id] = manager.client_data.pop(client_id)
                            else:
                                manager.client_data[new_id] = {
                                    'connected_at': datetime.now(),
                                    'frames_received': 0,
                                    'violations': 0,
                                    'warning_count': 0,
                                    'max_warnings': 3,
                                    'session_ended': False,
                                    'last_warning_time': None,
                                    'warning_expiry_seconds': 8
                                }

                            # ensure DB session exists for new_id
                            try:
                                db.create_session(new_id, datetime.now())
                            except Exception:
                                logger.debug('Session may already exist or creation failed')
                            
                            # Update client_id for this connection
                            client_id = new_id
                            logger.info(f"✅ [REGISTER] Updated connection client_id to: {client_id}")

                            # set the local client_id variable so the rest of the loop uses new id
                            client_id = new_id
                            success = await manager.send_message(client_id, {"status": "ok", "message": "registered"})
                            if not success:
                                logger.warning(f"⚠️ Failed to send registration confirmation to {client_id}")
                            continue
                        # If client sent a config update
                        if isinstance(payload, dict) and payload.get('type') == 'config':
                            cfg = payload.get('config', {})
                            cd = manager.client_data.get(client_id, {})
                            cd['config'] = cfg
                            manager.client_data[client_id] = cd
                            logger.info(f"🔧 Updated config for {client_id}: {cfg}")
                            # reply ack
                            success = await manager.send_message(client_id, {"status": "ok", "message": "config updated"})
                            if not success:
                                logger.warning(f"⚠️ Failed to send config ack to {client_id}")
                            continue
                        # handle tab_switch messages coming from client
                        if isinstance(payload, dict) and payload.get('type') == 'tab_switch':
                            state = payload.get('state')
                            logger.info(f"🔎 Tab switch event from {client_id}: {state}")
                            # store as a violation in DB
                            try:
                                v_store = {
                                    'type': 'tab_switch',
                                    'state': state,
                                    'confidence': 1.0,
                                    '_snapshot_time': datetime.now().isoformat()
                                }
                                db.store_violation(client_id, v_store, datetime.now())
                            except Exception:
                                logger.exception('Failed to store tab_switch violation')

                            # Update client counters and apply same warning logic synchronously
                            cd = manager.client_data.get(client_id, {})
                            cd.setdefault('tab_switch_count', 0)
                            cd['tab_switch_count'] = cd.get('tab_switch_count', 0) + 1

                            # determine expiry from config or defaults
                            client_cfg = cd.get('config', {})
                            try:
                                expiry = int(client_cfg.get('warning_expiry_seconds', cd.get('warning_expiry_seconds', 8)))
                            except Exception:
                                expiry = int(cd.get('warning_expiry_seconds', 8))

                            now = datetime.now()
                            last_warn = cd.get('last_warning_time')
                            if last_warn is None or (now - last_warn).total_seconds() > expiry:
                                cd['warning_count'] = cd.get('warning_count', 0) + 1
                                cd['last_warning_time'] = now
                                try:
                                    db.update_session_warning_count(client_id, cd['warning_count'], now)
                                except Exception:
                                    logger.exception('Failed to persist warning count for tab_switch')

                                # check for session end
                                if cd['warning_count'] >= cd.get('max_warnings', 3):
                                    cd['session_ended'] = True
                                    logger.critical(f"🛑 Session ENDED for {client_id}: Maximum 3 warnings reached (tab_switch)")
                                    # compile summary
                                    try:
                                        vlist = db.get_violations(client_id) or []
                                        summary = summarize_violations(vlist)
                                    except Exception:
                                        summary = {}
                                    await manager.send_message(client_id, {
                                        "status": "session_ended",
                                        "message": "Session ended: 3 warnings have been issued",
                                        "warning_count": cd['warning_count'],
                                        "violations_detected": 1,
                                        "violations": [{'type': 'tab_switch', 'state': state}],
                                        "severity_summary": summary,
                                        "timestamp": datetime.now().isoformat()
                                    })
                                    manager.client_data[client_id] = cd
                                    return
                                else:
                                    warnings_remaining = cd.get('max_warnings', 3) - cd.get('warning_count', 0)
                                    # send a warning message
                                    await manager.send_message(client_id, {
                                        "status": "ok",
                                        "message": "tab_switch warning",
                                        "warning_count": cd.get('warning_count', 0),
                                        "warnings_remaining": warnings_remaining,
                                        "violations_detected": 1,
                                        "violations": [{'type': 'tab_switch', 'state': state}],
                                        "timestamp": datetime.now().isoformat()
                                    })
                                    manager.client_data[client_id] = cd
                                    continue
                except Exception:
                    logger.debug("Failed to parse client text message as JSON config")

            # Binary frames (or already-decoded `data` from a text frame_b64)
            if msg.get('type') == 'websocket.receive' and 'bytes' in msg and msg.get('bytes'):
                data = msg.get('bytes')
            else:
                # if no binary bytes and no decoded data available, ignore message
                if data is None:
                    continue

            if not data:
                continue

            # Update frame count
            manager.client_data[client_id]["frames_received"] += 1

            # Lightweight per-frame logging to help debug client connectivity
            try:
                logger.info(f"📥 Frame from {client_id}: {len(data)} bytes (frames_received={manager.client_data[client_id]['frames_received']})")
            except Exception:
                pass

            # Get client config if present
            cd = manager.client_data.get(client_id, {})
            client_cfg = cd.get('config', {})
            # allow client to set persistence and expiry via config
            try:
                persistence = int(client_cfg.get('persistence', cd.get('consec_threshold', 2)))
            except Exception:
                persistence = int(cd.get('consec_threshold', 2))
            try:
                expiry = int(client_cfg.get('warning_expiry_seconds', cd.get('warning_expiry_seconds', 8)))
            except Exception:
                expiry = int(cd.get('warning_expiry_seconds', 8))

            # Detect violations and compute metrics
            try:
                violations, metrics = detector.detect_with_metrics(data, client_config=client_cfg)
            except Exception:
                # Fallback to older detect() if new method unavailable
                violations = detector.detect(data, client_config=client_cfg)
                metrics = { 'integrity_score': 0.0, 'visibility_pct': 0.0 }
            
            # Store violations in database (save evidence bytes only for DB storage)
            client_friendly = []

            # Initialize consecutive counters if not present
            cd = manager.client_data.get(client_id, {})
            cd.setdefault('consec_looking_away', 0)
            cd.setdefault('consec_face_out_of_box', 0)
            cd.setdefault('consec_prohibited_items', 0)
            cd.setdefault('consec_multiple_persons', 0)
            cd.setdefault('tab_switch_count', 0)
            cd.setdefault('warning_count', 0)
            cd.setdefault('max_warnings', 3)
            cd.setdefault('session_ended', False)
            manager.client_data[client_id] = cd

            # Check if session already ended (max warnings reached)
            if cd.get('session_ended'):
                await manager.send_message(client_id, {
                    "status": "session_ended",
                    "message": "Session ended: Maximum 3 warnings reached",
                    "violations_detected": 0,
                    "violations": [],
                    "timestamp": datetime.now().isoformat()
                })
                return

            if violations:
                for violation in violations:
                    try:
                        # Prepare copy for DB with raw bytes and snapshot timestamp
                        v_store = dict(violation)
                        # attach latest metrics so report model can consume them
                        try:
                            v_store['integrity_score'] = metrics.get('integrity_score')
                            v_store['visibility_pct'] = metrics.get('visibility_pct')
                        except Exception:
                            pass
                        v_store['_evidence_bytes'] = data
                        v_store['_snapshot_time'] = datetime.now().isoformat()
                        db.store_violation(client_id, v_store, datetime.now())
                    except Exception:
                        logger.exception("Failed to store violation")

                    # Decide whether to surface certain transient violations based on consecutive frames
                    v_type = violation.get('type')
                    suppress = False
                    # read persistence from client config when available; default to 1 (report immediately)
                    persistence = 1
                    try:
                        persistence = int(cd.get('config', {}).get('persistence', 1))
                    except Exception:
                        persistence = 1

                    if v_type == 'looking_away':
                        cd['consec_looking_away'] += 1
                        # require 'persistence' consecutive frames to report
                        if cd['consec_looking_away'] < persistence:
                            suppress = True
                        else:
                            # once reported, keep reporting until cleared by a non-looking_away
                            pass
                    elif v_type == 'face_out_of_box':
                        cd['consec_face_out_of_box'] += 1
                        if cd['consec_face_out_of_box'] < persistence:
                            suppress = True
                    elif v_type == 'prohibited_items' or v_type == 'phone':
                        # treat phone/prohibited items with persistence to avoid false positives
                        cd['consec_prohibited_items'] += 1
                        if cd['consec_prohibited_items'] < persistence:
                            suppress = True
                    elif v_type == 'multiple_persons':
                        cd['consec_multiple_persons'] += 1
                        if cd['consec_multiple_persons'] < persistence:
                            suppress = True
                    elif v_type == 'tab_switch':
                        # immediate attention for tab switching
                        cd['tab_switch_count'] = cd.get('tab_switch_count', 0) + 1
                        # do not use persistence for tab switching; treat as immediate
                        suppress = False
                    else:
                        # Reset counters when other or normal status
                        cd['consec_looking_away'] = 0
                        cd['consec_face_out_of_box'] = 0

                    # Prepare a client-safe copy (no raw bytes)
                    v_client = {k: v for k, v in violation.items() if k != '_evidence_bytes' and k != '_snapshot_time'}

                    if not suppress:
                        client_friendly.append(v_client)
                        manager.client_data[client_id]["violations"] += 1
                        
                        # Check if previous warning has expired (grace period)
                        now = datetime.now()
                        last_warn = cd.get('last_warning_time')
                        
                        if last_warn is None or (now - last_warn).total_seconds() > expiry:
                            # Warning expired or first warning - increment count
                            cd['warning_count'] = cd.get('warning_count', 0) + 1
                            cd['last_warning_time'] = now
                            warnings_remaining = cd['max_warnings'] - cd['warning_count']
                            
                            # Persist to database
                            try:
                                db.update_session_warning_count(client_id, cd['warning_count'], now)
                            except Exception as e:
                                logger.error(f"Failed to persist warning count: {e}")
                            
                            logger.warning(f"⚠️ Violation detected for {client_id}: {v_type} (Warning {cd['warning_count']}/{cd['max_warnings']})")
                            
                            # Check if max warnings reached
                            if cd['warning_count'] >= cd['max_warnings']:
                                cd['session_ended'] = True
                                logger.critical(f"🛑 Session ENDED for {client_id}: Maximum 3 warnings reached")
                                await manager.send_message(client_id, {
                                    "status": "session_ended",
                                    "message": "Session ended: 3 warnings have been issued",
                                    "warning_count": cd['warning_count'],
                                    "violations_detected": len(client_friendly),
                                    "violations": client_friendly,
                                    "timestamp": datetime.now().isoformat()
                                })
                                return
                            
                            # Send warning with remaining count
                            v_client['warnings_remaining'] = warnings_remaining
                        else:
                            # Warning is still active, just log violation without incrementing warning count
                            elapsed = (now - last_warn).total_seconds()
                            remaining_grace = expiry - elapsed
                            logger.info(f"(violation during active warning period) for {client_id}: {v_type} ({remaining_grace:.1f}s grace remaining)")
                    else:
                        logger.info(f"(suppressed transient {v_type}) for {client_id} (count={cd.get('consec_looking_away')}/{cd.get('consec_face_out_of_box')})")
            else:
                # No violations --> reset consecutive counters for all types
                cd['consec_looking_away'] = 0
                cd['consec_face_out_of_box'] = 0
                cd['consec_prohibited_items'] = 0
                cd['consec_multiple_persons'] = 0
            
            # Send feedback to client with metrics
            await manager.send_message(client_id, {
                "status": "ok",
                "violations_detected": len(client_friendly),
                "violations": client_friendly,
                "warning_count": cd.get('warning_count', 0),
                "warnings_remaining": cd.get('max_warnings', 3) - cd.get('warning_count', 0),
                "integrity_score": metrics.get('integrity_score'),
                "visibility_pct": metrics.get('visibility_pct'),
                "timestamp": datetime.now().isoformat()
            })
    
    except WebSocketDisconnect:
        await manager.disconnect(client_id)
        logger.info(f"WebSocket disconnected for {client_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
        await manager.disconnect(client_id)
        try:
            await websocket.close(code=1011, reason="Server error")
        except:
            pass

# Helper functions
def summarize_violations(violations: List[dict]) -> dict:
    """Summarize violations by type"""
    # Normalize common aliases to canonical names for clearer summaries
    alias_map = {
        'phone': 'prohibited_items',
        'mobile': 'prohibited_items',
        'cellphone': 'prohibited_items',
        'multiple_people': 'multiple_persons',
        'multi_person': 'multiple_persons'
    }
    summary = {}
    for violation in violations:
        v_type = violation.get('type', 'unknown')
        # if violation has a nested object with 'class' or 'label', prefer canonical
        if isinstance(v_type, str):
            v_type = alias_map.get(v_type, v_type)
        else:
            v_type = str(v_type)

        summary[v_type] = summary.get(v_type, 0) + 1
    return summary

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

@app.get("/api/debug/detect")
async def debug_detect():
    """Debug endpoint - test detection on a sample frame"""
    import cv2
    import numpy as np
    try:
        # Try to load a real image, fallback to blank
        frame = cv2.imread('backend/training/dataset/images/train/train_0029.jpg')
        if frame is None:
            frame = cv2.imread('training/dataset/images/train/train_0029.jpg')
        if frame is None:
            # Fallback: create blank
            frame = np.ones((480, 640, 3), dtype=np.uint8) * 200
        
        _, buffer = cv2.imencode('.jpg', frame)
        violations = detector.detect(buffer.tobytes())
        
        return {
            "violations_count": len(violations),
            "violations": violations,
            "debug": {
                "face_cascade_available": detector.face_cascade is not None,
                "dnn_net_available": detector.dnn_net is not None,
                "yolo_model_loaded": detector.yolo_model is not None,
                "confidence_threshold": detector.confidence_threshold
            }
        }
    except Exception as e:
        logger.error(f"Debug detection error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.post('/api/debug/upload')
async def debug_upload(file: UploadFile = File(...)):
        """Upload an image from the browser and run detection (useful when camera is blocked)."""
        try:
                data = await file.read()
                violations = detector.detect(data)
                return {"violations_count": len(violations), "violations": violations}
        except Exception as e:
                logger.error(f"Upload debug error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})


@app.post('/api/frame/{client_id}')
async def upload_frame_fallback(client_id: str, file: UploadFile = File(...)):
    """HTTP fallback for clients that cannot use WebSocket: upload a single frame for detection."""
    try:
        data = await file.read()

        # run detection and compute metrics
        try:
            violations, metrics = detector.detect_with_metrics(data)
        except Exception:
            violations = detector.detect(data)
            metrics = {'integrity_score': 0.0, 'visibility_pct': 0.0}

        # store each violation (annotated evidence will be saved by db)
        for v in violations:
            try:
                v_store = dict(v)
                try:
                    v_store['integrity_score'] = metrics.get('integrity_score')
                    v_store['visibility_pct'] = metrics.get('visibility_pct')
                except Exception:
                    pass
                v_store['_evidence_bytes'] = data
                v_store['_snapshot_time'] = datetime.now().isoformat()
                db.store_violation(client_id, v_store, datetime.now())
            except Exception:
                logger.exception('Failed to store violation from HTTP upload')

        # Update session warning_count based on last_warning_time stored in DB
        session = db.get_session(client_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')

        warning_count = session.get('warning_count') or 0
        last_warn_iso = session.get('last_warning_time')
        last_warn = datetime.fromisoformat(last_warn_iso) if last_warn_iso else None
        expiry = 30

        # determine if any of the violations should trigger a warning (use same heuristics as WS)
        triggered = False
        for v in violations:
            v_type = v.get('type')
            if v_type in ('looking_away', 'face_out_of_box', 'no_face', 'multiple_persons', 'prohibited_items'):
                # For HTTP fallback we consider them immediate
                now = datetime.now()
                if last_warn is None or (now - last_warn).total_seconds() > expiry:
                    warning_count += 1
                    last_warn = now
                    db.update_session_warning_count(client_id, warning_count, last_warn)
                    triggered = True
                    break
        session_ended = False
        if warning_count >= 3:
            session_ended = True
            try:
                db.end_session(client_id, datetime.now())
            except Exception:
                logger.exception('Failed to end session after 3 warnings')

        return {
            'violations_detected': len(violations),
            'violations': violations,
            'warning_count': warning_count,
            'warnings_remaining': max(0, 3 - warning_count),
            'session_ended': session_ended,
            'integrity_score': metrics.get('integrity_score'),
            'visibility_pct': metrics.get('visibility_pct')
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'HTTP frame upload error: {e}')
        raise HTTPException(status_code=500, detail='Frame processing failed')


@app.get('/test_page', response_class=HTMLResponse)
async def test_page():
        """Simple page to test camera access and one-shot websocket/image upload."""
        html = r'''
<!doctype html>
<html>
    <head>
        <meta charset="utf-8" />
        <title>Live Proctoring Test Page</title>
    </head>
    <body>
        <h2>Live Proctoring - Quick Test</h2>
        <div>
            <button id="startCam">Start Camera</button>
            <button id="connectWS">Connect WS</button>
            <button id="sendFrame">Send One Frame (WS)</button>
            <input id="upload" type="file" accept="image/*" />
            <button id="uploadBtn">Upload Image</button>
        </div>
        <video id="video" autoplay playsinline style="width:320px;height:240px;border:1px solid #ccc"></video>
        <pre id="log" style="white-space:pre-wrap;border:1px solid #eee;padding:8px;height:240px;overflow:auto"></pre>

        <script>
            const log = (m) => { const p = document.getElementById('log'); p.textContent = (new Date().toLocaleTimeString()) + ' - ' + m + '\n' + p.textContent; };
            let stream = null;
            let ws = null;

            document.getElementById('startCam').onclick = async () => {
                try {
                    stream = await navigator.mediaDevices.getUserMedia({video:true});
                    document.getElementById('video').srcObject = stream;
                    log('Camera started');
                } catch (e) {
                    log('Camera error: ' + e.toString());
                }
            };

            document.getElementById('connectWS').onclick = () => {
                try {
                    ws = new WebSocket('ws://127.0.0.1:8000/ws/test_page_client');
                    ws.onopen = () => log('WS open');
                    ws.onmessage = (ev) => log('WS msg: ' + ev.data);
                    ws.onerror = (ev) => log('WS error');
                    ws.onclose = () => log('WS closed');
                } catch (e) { log('WS connect error: ' + e.toString()); }
            };

            document.getElementById('sendFrame').onclick = async () => {
                try {
                    if (!stream) { log('No camera stream'); return; }
                    if (!ws || ws.readyState !== WebSocket.OPEN) { log('WS not open'); return; }
                    const video = document.getElementById('video');
                    const c = document.createElement('canvas'); c.width = video.videoWidth || 640; c.height = video.videoHeight || 480;
                    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
                    c.toBlob(async (blob) => {
                        const buf = await blob.arrayBuffer();
                        ws.send(buf);
                        log('Sent one frame (' + blob.size + ' bytes)');
                    }, 'image/jpeg', 0.8);
                } catch (e) { log('sendFrame error: ' + e.toString()); }
            };

            document.getElementById('uploadBtn').onclick = async () => {
                const f = document.getElementById('upload').files[0];
                if (!f) { log('No file selected'); return; }
                try {
                    const fd = new FormData(); fd.append('file', f);
                    log('Uploading ' + f.name);
                    const r = await fetch('/api/debug/upload', {method:'POST', body:fd});
                    const j = await r.json();
                    log('Upload response: ' + JSON.stringify(j, null, 2));
                } catch (e) { log('upload error: ' + e.toString()); }
            };
        </script>
    </body>
</html>
'''
        return HTMLResponse(content=html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
