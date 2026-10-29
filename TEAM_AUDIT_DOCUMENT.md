# Live Proctoring — Team Audit (Plain Language)

**Date:** October 29, 2026  
**Audience:** Product, QA, and engineering (non-jargon first)  
**Project folders:** `backend/` (AI server) + `frontend/` (student camera screen)

---

## 1. What is this project?

This is a **live exam proctoring** system.

In simple words:

1. The student opens a web page and allows the webcam.
2. The page sends pictures of the student to our server every half-second.
3. The server’s AI looks at each picture and checks for cheating-like behavior.
4. Warnings are counted. After **3 warnings**, the session is treated as ended.
5. Everything important is saved so someone can review later (who, when, what happened, and a photo).

Think of it like a digital invigilator that watches the camera and keeps a report card.

---

## 2. What we have built (big picture)

| Piece | What it is | What it does |
|--------|------------|--------------|
| **Frontend** | A React web page | Shows camera, Start/End session, warnings, status messages |
| **Backend** | A Python FastAPI server | Receives video frames, runs AI, stores results |
| **Database** | SQLite file `proctoring.db` | Saves sessions and violations |
| **AI models** | YOLO + face detectors | Find phones and faces in the camera picture |
| **Evidence folder** | `backend/data/evidence/` | Saves snapshot images when a violation is logged |

```
Student browser  --->  Frontend (port 3000)
                           |
                           | camera frames + tab events
                           v
                     Backend (port 8000)
                           |
              +------------+------------+
              |                         |
         AI detector              SQLite + evidence photos
```

---

## 3. What the system can detect today

| Check | Plain meaning | How we do it |
|--------|----------------|--------------|
| **No face** | Student left the camera / face not visible | Face detector finds 0 faces |
| **Multiple people** | Another person appears on camera | Face detector finds more than 1 face |
| **Face out of box** | Face is outside the allowed screen area | Face center outside the “safe zone” |
| **Looking away** | Eyes/head seem turned away from screen | Gaze estimate (works best if MediaPipe is installed) |
| **Phone / prohibited item** | Mobile phone in view | YOLOv8 looks for “cellphone” |
| **Tab switch** | Student left the exam tab or window | Browser tells the server (not AI) |

**Also calculated:**

- **Integrity score** (0–100): rough “how clean was this session?” number  
- **Visibility %**: how big the face is in the frame  

**Rule:** **3 warnings**. After the third counted warning, the session ends.

---

## 4. How a normal exam session works

1. Open the student page → camera permission asked.
2. Session starts on the server (`/api/session/start`).
3. Live connection opens (WebSocket) so frames can stream quickly.
4. About **2 pictures per second** are sent.
5. Server replies with: OK / warning / session ended.
6. Student (or system) ends session → summary is available.
7. Reviewer can fetch a report and evidence images via API.

**Handy test page (no React needed):**  
`http://127.0.0.1:8000/test_page`

**API docs (for developers):**  
`http://127.0.0.1:8000/docs`

---

## 5. Backend — what exists

### Main files

| File / folder | Plain purpose |
|---------------|---------------|
| `backend/app/main.py` | The “front desk”: all APIs, WebSocket, warning rules |
| `backend/app/detector.py` | The “eyes”: AI that looks at each frame |
| `backend/app/db.py` | The “filing cabinet”: sessions + violations in SQLite |
| `backend/app/utils.py` | Extra helpers (mostly unused by the live API today) |
| `backend/models/` | Face model files |
| `backend/yolov8n.pt` | Phone-detection model weights |
| `backend/training/` | Optional scripts to retrain YOLO on custom photos |
| `backend/backend_env/` | Python virtual environment (isolated install) |

### Important APIs (short list)

- Health: `GET /api/health`
- Start / end session: `POST /api/session/start`, `POST /api/session/end`
- Live video: `WS /ws/{student_id}`
- Report: `GET /api/report/{student_id}`
- Violations list: `GET /api/violations/{student_id}`
- Evidence photos: `GET /api/evidence`
- Tab left/returned: `POST /api/tab_switch`

### Warning policy (as coded)

- Max warnings: **3**
- Some AI warnings wait for a short “persistence” (repeat frames) before counting, so one-frame glitches are less noisy
- Tab hide/blur can warn more immediately
- Warning “cool-down” is short (about **8 seconds** on the live WebSocket path)

---

## 6. Frontend — what exists

| Item | Plain purpose |
|------|---------------|
| Student screen | One page: video + Start/End + warning counter |
| Student ID | Auto-generated (`student_…`) and remembered in the browser |
| Status badge | Shows connection state and human-readable warnings |
| Overlay boxes | Briefly draws colored boxes on detected faces/phones |
| Session summary | After End Session, shows violation counts |

**Note for the team:** The React `src/` folder was missing from this copy of the project. It was **restored from a local build cache** so the app can run again. Treat that restore as recovered code; confirm it matches your expected latest UI before a formal release.

---

## 7. How to run (Windows) — for accuracy testing

### Already prepared

- Backend virtual environment: `backend/backend_env` (exists)
- Dependencies from `requirements.txt` are installable/installed there
- YOLO weights file: `backend/yolov8n.pt`

### Start backend

```cmd
cd backend
backend_env\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Or double-click / run: `START_BACKEND.bat` from the project root.

Backend URL: **http://127.0.0.1:8000**

### Start frontend

```cmd
cd frontend
npm start
```

Frontend URL: **http://localhost:3000**

Allow camera access when the browser asks.

### Quick accuracy smoke tests (manual)

| Test | What to do | Expected |
|------|------------|----------|
| Face visible | Sit in front of camera | Status tends toward “No violations” |
| Leave camera | Cover camera / walk away | “No face” warning |
| Second person | Another face enters frame | “Multiple people” |
| Phone | Hold phone toward camera | “Phone detected” |
| Look away | Turn head strongly left/right | “Looking away” (weaker if MediaPipe missing) |
| Switch tab | Open another browser tab | Tab-switch event / warning |
| 3 warnings | Trigger 3 real warnings | Session ends |

Also try: **http://127.0.0.1:8000/test_page** → Start Camera → Connect WS → Send One Frame.

---

## 8. What is stored for review

- **Session:** who (client id), start time, end time, warning count  
- **Violation rows:** type, time, severity, details JSON  
- **Evidence JPEG:** annotated snapshot when a violation is stored  

This is the audit trail for later human review.

---

## 9. Training pipeline (optional / advanced)

Under `backend/training/` there are scripts to:

1. Make sample / synthetic images  
2. Augment (vary) them  
3. Fine-tune YOLO for **face** and **cellphone**  

**Today’s live server still uses the default COCO YOLO (`yolov8n.pt`) for phones**, plus separate face detectors. A custom trained `best.pt` is **not auto-plugged in** unless someone points the detector to it.

---

## 10. Honest gaps & risks (for the team)

These are important so we don’t oversell “production ready”:

1. **No login / no passwords** — anyone who can reach the API can start sessions or download evidence.  
2. **CORS is wide open** — fine for local demo; not fine on the public internet without a gateway.  
3. **Looking-away detection** is a heuristic; accuracy depends on lighting, camera angle, and optional MediaPipe.  
4. **MediaPipe / InsightFace** are optional and may not be in `requirements.txt` — without them, face/gaze quality may drop to OpenCV DNN only.  
5. **Multiple people** = multiple *faces*. A second person not facing the camera may be missed.  
6. **Frontend was incomplete** in this workspace (`src/` missing) and had to be restored for local testing.  
7. **Hardcoded localhost** — student page always talks to `127.0.0.1:8000` (dev-only setup).  
8. Older docs say “PRODUCTION READY”; treat that as aspirational. Hardening (HTTPS, auth, rate limits, GPU sizing) is still needed for real exams.

---

## 11. Accuracy expectations (plain)

| Area | Rough expectation |
|------|-------------------|
| Phone in clear view | Usually good with YOLO |
| No face / face present | Usually good with DNN face model |
| Two clear faces | Usually good |
| Looking away | Hit-or-miss; needs good light and preferably MediaPipe |
| Brief glitches | Persistence setting reduces some false alarms |
| Dark room / tiny face / bad webcam | More misses and false alerts |

**Recommendation:** Run a **shared test script** with 10–15 scripted scenarios (phone, no face, second person, look away, tab switch) and record pass/fail before any live exam pilot.

---

## 12. One-line status for leadership

> We have a working local demo: student webcam → AI checks (face, people, phone, gaze, tab) → 3-strike warnings → SQLite report + photo evidence. Good for internal accuracy testing; not yet hardened for production exams.

---

## 13. Where to click / what to open while testing

| Link | Why |
|------|-----|
| http://localhost:3000 | Full student UI |
| http://127.0.0.1:8000/test_page | Minimal camera + one-frame test |
| http://127.0.0.1:8000/api/health | Is server alive? |
| http://127.0.0.1:8000/docs | Try APIs interactively |
| http://127.0.0.1:8000/api/report/{student_id} | After a session, see the report |

---

## 14. What we verified while preparing this audit

| Check | Result |
|------|--------|
| Backend venv (`backend/backend_env`) | Already present; deps load (FastAPI, YOLO, OpenCV) |
| Backend start | Running at **http://127.0.0.1:8000** |
| Health API | `healthy` |
| Session start/end | Works for test client `audit_test_001` |
| Models loaded | YOLO `yolov8n.pt` + OpenCV DNN face model |
| Frontend `src/` | Was missing; restored from babel cache so the app can run |
| Frontend start | Running at **http://localhost:3000** (eslint unused-var warnings only) |
| Built-in test page | **http://127.0.0.1:8000/test_page** available for camera accuracy checks |

---

*Document generated from a full codebase walkthrough of the Live Proctoring backend and frontend on this machine.*
