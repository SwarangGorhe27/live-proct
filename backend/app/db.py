import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "proctoring.db"):
        self.db_path = db_path
        self.connection: Optional[sqlite3.Connection] = None
    
    def connect(self):
        """Connect to database and create tables"""
        try:
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            self._init_tables()
            logger.info(f"✅ Database connected: {self.db_path}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to database: {e}")
            raise
    
    def _init_tables(self):
        """Initialize database tables"""
        try:
            cursor = self.connection.cursor()
            
            # Sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT UNIQUE NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    warning_count INTEGER DEFAULT 0,
                    last_warning_time TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Violations table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    violation_type TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    details TEXT,
                    severity TEXT DEFAULT 'medium',
                    evidence_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES sessions(client_id)
                )
            ''')
            
            # Create indexes for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_client_id ON violations(client_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON violations(timestamp)')
            
            # Ensure necessary columns exist for older DBs
            try:
                cursor.execute("PRAGMA table_info(violations)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'evidence_path' not in cols:
                    cursor.execute("ALTER TABLE violations ADD COLUMN evidence_path TEXT")
                
                # Ensure sessions table has warning tracking columns
                cursor.execute("PRAGMA table_info(sessions)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'warning_count' not in cols:
                    cursor.execute("ALTER TABLE sessions ADD COLUMN warning_count INTEGER DEFAULT 0")
                if 'last_warning_time' not in cols:
                    cursor.execute("ALTER TABLE sessions ADD COLUMN last_warning_time TIMESTAMP")
            except Exception as e:
                logger.warning(f"Could not migrate columns: {e}")
                pass

            self.connection.commit()
            logger.info("✅ Database tables initialized")
        except Exception as e:
            logger.error(f"❌ Error initializing tables: {e}")
            raise
    
    def create_session(self, client_id: str, start_time: datetime) -> bool:
        """Create a new session"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                'INSERT INTO sessions (client_id, start_time) VALUES (?, ?)',
                (client_id, start_time)
            )
            self.connection.commit()
            logger.info(f"✅ Session created for {client_id}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"⚠️ Session already exists for {client_id}")
            return False
        except Exception as e:
            logger.error(f"❌ Error creating session: {e}")
            raise
    
    def end_session(self, client_id: str, end_time: datetime) -> bool:
        """End an existing session"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                'UPDATE sessions SET end_time = ? WHERE client_id = ?',
                (end_time, client_id)
            )
            self.connection.commit()
            logger.info(f"✅ Session ended for {client_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error ending session: {e}")
            raise
    
    def store_violation(self, client_id: str, violation: Dict, timestamp: datetime) -> bool:
        """Store a violation in database"""
        try:
            cursor = self.connection.cursor()
            # Optionally save evidence bytes to disk if provided in violation dict
            evidence_path = None
            if violation.get('_evidence_bytes'):
                try:
                    import os
                    from uuid import uuid4

                    # Attempt to annotate image with boxes/confidences before saving
                    try:
                        import cv2
                        import numpy as np
                        nparr = np.frombuffer(violation.get('_evidence_bytes'), np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if img is not None:
                            # Draw face boxes if present
                            faces = violation.get('faces') or []
                            for f in faces:
                                bbox = f.get('bbox') if isinstance(f, dict) else None
                                if bbox and len(bbox) >= 4:
                                    x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
                                    cv2.rectangle(img, (x1, y1), (x2, y2), (50,205,50), 2)
                                    conf = f.get('confidence') or f.get('gaze_score')
                                    if conf is not None:
                                        try:
                                            cv2.putText(img, f"{conf:.2f}", (x1+4, max(y1-6,14)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50,205,50), 2)
                                        except Exception:
                                            pass
                            # Draw boxes for prohibited items
                            boxes = violation.get('boxes') or []
                            for b in boxes:
                                bbox = b.get('bbox') if isinstance(b, dict) else None
                                if bbox and len(bbox) >= 4:
                                    x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
                                    cv2.rectangle(img, (x1, y1), (x2, y2), (0,69,255), 2)
                                    conf = b.get('confidence')
                                    label = b.get('class_name') or b.get('class') or 'obj'
                                    try:
                                        if conf is not None:
                                            text = f"{label} {conf:.2f}"
                                        else:
                                            text = f"{label}"
                                        cv2.putText(img, text, (x1+4, max(y1-6,14)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,69,255), 2)
                                    except Exception:
                                        pass
                            # Save annotated version back into bytes so we store annotated file
                            try:
                                success, buf = cv2.imencode('.jpg', img)
                                if success:
                                    violation['_evidence_bytes'] = buf.tobytes()
                            except Exception:
                                pass
                    except Exception:
                        # CV2 may not be available or annotation failed; continue to save raw bytes
                        pass

                    evidence_dir = os.path.join('data', 'evidence')
                    os.makedirs(evidence_dir, exist_ok=True)
                    filename = f"{client_id}_{datetime.now().strftime('%Y%m%dT%H%M%S')}_{uuid4().hex}.jpg"
                    evidence_path = os.path.join(evidence_dir, filename)
                    with open(evidence_path, 'wb') as f:
                        f.write(violation.get('_evidence_bytes'))
                    # Replace raw bytes in details with path
                except Exception as e:
                    logger.error(f"❌ Failed to write evidence file: {e}")

            cursor.execute(
                '''INSERT INTO violations 
                   (client_id, violation_type, timestamp, details, severity, evidence_path) 
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    client_id,
                    violation.get('type', 'unknown'),
                    timestamp,
                    json.dumps({k:v for k,v in violation.items() if k != '_evidence_bytes'}),
                    violation.get('severity', 'medium'),
                    evidence_path
                )
            )
            self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error storing violation: {e}")
            return False
    
    def get_violations(self, client_id: str) -> List[Dict]:
        """Get all violations for a client"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                '''SELECT * FROM violations 
                   WHERE client_id = ? 
                   ORDER BY timestamp DESC''',
                (client_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Error retrieving violations: {e}")
            return []
    
    def get_session(self, client_id: str) -> Optional[Dict]:
        """Get session details for a client"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                'SELECT * FROM sessions WHERE client_id = ?',
                (client_id,)
            )
            row = cursor.fetchone()
            if row:
                session = dict(row)
                if session['end_time']:
                    start = datetime.fromisoformat(session['start_time'])
                    end = datetime.fromisoformat(session['end_time'])
                    session['duration'] = str(end - start)
                return session
            return None
        except Exception as e:
            logger.error(f"❌ Error retrieving session: {e}")
            return None
    
    def delete_session(self, client_id: str) -> bool:
        """Delete a session and all associated violations"""
        try:
            cursor = self.connection.cursor()
            cursor.execute('DELETE FROM violations WHERE client_id = ?', (client_id,))
            cursor.execute('DELETE FROM sessions WHERE client_id = ?', (client_id,))
            self.connection.commit()
            logger.info(f"✅ Session and violations deleted for {client_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error deleting session: {e}")
            return False
    
    def get_all_sessions(self) -> List[Dict]:
        """Get all sessions"""
        try:
            cursor = self.connection.cursor()
            cursor.execute('SELECT * FROM sessions ORDER BY created_at DESC')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Error retrieving sessions: {e}")
            return []
    
    def get_warning_count(self, client_id: str) -> int:
        """Get number of unique warning violations for a client (warnings that were counted, not suppressed)"""
        try:
            cursor = self.connection.cursor()
            # Count violations where they triggered a warning (would need a flag in violations table)
            # For now, we'll count non-looking_away violations as those are most likely to trigger warnings
            cursor.execute(
                '''SELECT COUNT(DISTINCT timestamp) FROM violations 
                   WHERE client_id = ? AND violation_type != 'looking_away'
                   ORDER BY timestamp ASC''',
                (client_id,)
            )
            count = cursor.fetchone()[0]
            return count if count else 0
        except Exception as e:
            logger.error(f"❌ Error retrieving warning count: {e}")
            return 0
    
    def update_session_warning_count(self, client_id: str, warning_count: int, last_warning_time: Optional[datetime] = None) -> bool:
        """Update warning count and last warning time in session"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                'UPDATE sessions SET warning_count = ?, last_warning_time = ? WHERE client_id = ?',
                (warning_count, last_warning_time, client_id)
            )
            self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error updating warning count: {e}")
            return False
    
    def close(self):
        """Close database connection"""
        try:
            if self.connection:
                self.connection.close()
                logger.info("✅ Database connection closed")
        except Exception as e:
            logger.error(f"❌ Error closing database: {e}")
