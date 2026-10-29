import React, { useEffect, useRef, useState } from 'react';
import './App.css';
function App() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const overlayRef = useRef(null);
  const wsRef = useRef(null);
  const [isRunning, setIsRunning] = useState(false);
  const isRunningRef = useRef(false);
  const pingRef = useRef(null);
  const [violations, setViolations] = useState([]);
  const [clientId, setClientId] = useState(() => {
    try {
      const saved = localStorage.getItem('clientId');
      if (saved) {
        console.log('✅ Loaded clientId from localStorage:', saved);
        return saved;
      }
    } catch (e) {
      console.warn('localStorage error:', e);
    }
    const newId = 'student_' + Math.random().toString(36).substr(2, 9);
    console.log('🔷 Generated new clientId:', newId);
    try {
      localStorage.setItem('clientId', newId);
    } catch (e) {
      console.warn('Failed to save clientId to localStorage:', e);
    }
    return newId;
  });
  const [sessionActive, setSessionActive] = useState(false);
  const [status, setStatus] = useState('Ready');
  const [lastViolation, setLastViolation] = useState(null);
  const [autoMode, setAutoMode] = useState(true);
  const [warningCount, setWarningCount] = useState(0);
  const [warningsRemaining, setWarningsRemaining] = useState(3);
  const [integrityScore, setIntegrityScore] = useState(null);
  const [visibilityPct, setVisibilityPct] = useState(null);
  const [sessionSummary, setSessionSummary] = useState(null);
  // Calibration state (fractions) - Full frame coverage
  const [leftPct, setLeftPct] = useState(0.0);
  const [topPct, setTopPct] = useState(0.0);
  const [rightPct, setRightPct] = useState(1.0);
  const [bottomPct, setBottomPct] = useState(1.0);
  const [horizLow, setHorizLow] = useState(0.20);
  const [horizHigh, setHorizHigh] = useState(0.80);
  const [vertTolerance, setVertTolerance] = useState(0.30);
  const [persistence, setPersistence] = useState(2);
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // Tab / visibility handling: send HTTP request when user switches tabs or blurs
  useEffect(() => {
    const onVisibility = () => {
      const hidden = document.hidden;
      // Send tab switch event via HTTP (more reliable than WS for critical events)
      const state = hidden ? 'hidden' : 'visible';
      fetch(`http://127.0.0.1:8000/api/tab_switch?client_id=${encodeURIComponent(clientId)}&state=${encodeURIComponent(state)}`, {
        method: 'POST'
      }).catch(e => console.warn('Failed to send tab_switch', e));
      setStatus(hidden ? '⚠️ Tab hidden' : '🟢 Tab active');
    };
    const onBlur = () => {
      fetch(`http://127.0.0.1:8000/api/tab_switch?client_id=${encodeURIComponent(clientId)}&state=blur`, {
        method: 'POST'
      }).catch(e => console.warn('Failed to send blur', e));
      setStatus('⚠️ Window blurred');
    };
    const onFocus = () => {
      fetch(`http://127.0.0.1:8000/api/tab_switch?client_id=${encodeURIComponent(clientId)}&state=focus`, {
        method: 'POST'
      }).catch(e => console.warn('Failed to send focus', e));
      setStatus('🟢 Window focused');
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('blur', onBlur);
    window.addEventListener('focus', onFocus);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  // Auto-start session, camera and websocket when component mounts (if autoMode)
  useEffect(() => {
    if (autoMode) {
      (async () => {
        try {
          await startSession();
        } catch (e) {
          console.error('Auto start error', e);
        }
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMode]);
  const startSession = async () => {
    try {
      console.log('🟢 startSession called with clientId:', clientId);
      try {
        localStorage.setItem('clientId', clientId);
      } catch (e) {}

      // Ensure backend is bound to this client id: call rebind endpoint.
      try {
        await fetch(`http://127.0.0.1:8000/api/session/rebind?new_client_id=${encodeURIComponent(clientId)}`, {
          method: 'POST'
        });
      } catch (e) {
        console.warn('Rebind request failed (continuing):', e);
      }
      const response = await fetch(`http://127.0.0.1:8000/api/session/start?client_id=${clientId}`, {
        method: 'POST'
      });
      if (!response.ok) throw new Error('Failed to start session');
      setSessionActive(true);
      setStatus('Starting video capture...');
      await startVideoCapture();
    } catch (error) {
      setStatus('❌ Error: ' + error.message);
    }
  };
  const startVideoCapture = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: {
            ideal: 640
          },
          height: {
            ideal: 480
          }
        }
      });
      videoRef.current.srcObject = stream;
      videoRef.current.onloadedmetadata = () => {
        console.log('Video metadata loaded');
        videoRef.current.play();
        isRunningRef.current = true;
        setIsRunning(true);
        setStatus('🎥 Recording...');
        setupWebSocket();
        captureFrames();
      };

      // Fallback: start capture even if metadata event doesn't fire
      // This ensures frames are sent even on browsers that don't emit onloadedmetadata
      setTimeout(() => {
        if (videoRef.current && videoRef.current.videoWidth === 0) {
          console.log('Fallback: starting capture without metadata event');
          videoRef.current.play();
          isRunningRef.current = true;
        setIsRunning(true);
          setStatus('🎥 Recording...');
          setupWebSocket();
          captureFrames();
        }
      }, 1000);
    } catch (error) {
      setStatus('❌ Camera access denied');
    }
  };
  const setupWebSocket = () => {
    const url = `ws://127.0.0.1:8000/ws/${clientId}`;
    console.log('🔌 WebSocket connecting to:', url);
    const connect = () => {
      wsRef.current = new WebSocket(url);
      wsRef.current.onopen = () => {
        console.log('✅ WebSocket Connected (clientId:', clientId, ')');
        setStatus('🟢 Connected');
        // set binary type for efficient frame transmission
        try {
          wsRef.current.binaryType = 'arraybuffer';
        } catch (e) {}
        // CRITICAL: Send register message immediately to bind this WS to the client_id
        try {
          wsRef.current.send(JSON.stringify({
            type: 'register',
            client_id: clientId
          }));
          console.log('📤 Register message sent with clientId:', clientId);
        } catch (e) {
          console.warn('Failed to send register', e);
        }
        // start heartbeat ping every 20s to keep connection alive
        try {
          if (pingRef.current) clearInterval(pingRef.current);
          pingRef.current = setInterval(() => {
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({
                type: 'ping'
              }));
            }
          }, 20000);
        } catch (e) {
          console.warn('Failed to start ping', e);
        }
      };
      wsRef.current.onmessage = event => {
        try {
          const data = JSON.parse(event.data);
          handleViolationsFromServer(data);
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };
      wsRef.current.onerror = () => {
        setStatus('❌ Connection error');
      };
      wsRef.current.onclose = () => {
        console.log('WebSocket Disconnected');
        setStatus('⚪ Disconnected');
        // stop heartbeat
        try {
          if (pingRef.current) {
            clearInterval(pingRef.current);
            pingRef.current = null;
          }
        } catch (e) {}
        // attempt reconnect after a short delay
        setTimeout(() => connect(), 1000);
      };
    };
    connect();
  };
  const handleViolationsFromServer = data => {
    // Check if session ended
    if (data.status === 'session_ended') {
      setStatus('🛑 SESSION ENDED - 3 warnings reached');
      setWarningCount(data.warning_count || 0);
      isRunningRef.current = false;
      setIsRunning(false);
      stopSession();
      return;
    }

    // Update warning count from server
    if (data.warning_count !== undefined) {
      setWarningCount(data.warning_count);
    }
    if (data.warnings_remaining !== undefined) {
      setWarningsRemaining(data.warnings_remaining);
    }
    if (data.integrity_score !== undefined) {
      setIntegrityScore(data.integrity_score);
    }
    if (data.visibility_pct !== undefined) {
      // show as rounded percent
      try {
        const rounded = Math.round(Number(data.visibility_pct));
        setVisibilityPct(rounded);
      } catch (e) {
        setVisibilityPct(data.visibility_pct);
      }
    }

    // Draw boxes if provided in violations
    if (data.violations && data.violations.length > 0) {
      const boxes = [];
      data.violations.forEach(v => {
        if (v.boxes && Array.isArray(v.boxes)) {
          v.boxes.forEach(b => {
            if (b.bbox) boxes.push({
              bbox: b.bbox,
              label: b.class_name || b.type,
              confidence: b.confidence,
              type: v.type
            });
          });
        }
        if (v.faces && Array.isArray(v.faces)) {
          v.faces.forEach(f => {
            const bbox = f.bbox || f;
            const confidence = f.confidence || f.gaze_score || null;
            boxes.push({
              bbox: bbox,
              label: 'face',
              confidence: confidence,
              type: v.type
            });
          });
        }
      });
      if (boxes.length > 0) drawOverlayBoxes(boxes);
    }
    if (data.violations_detected > 0) {
      const violationSummary = data.violations.map(v => {
        if (v.type === 'multiple_persons') return `👤 ${v.count} people detected`;
        if (v.type === 'prohibited_items') return `📱 Phone detected`;
        if (v.type === 'no_face') return '❌ No face detected';
        if (v.type === 'face_out_of_box') return `↔️ Face out of box (${v.count})`;
        if (v.type === 'looking_away') return `👀 Looking away (${v.count})`;
        return v.type;
      }).join(' | ');
      setLastViolation(violationSummary);
      setViolations(prev => [...prev, {
        timestamp: new Date().toLocaleTimeString(),
        summary: violationSummary,
        raw: data.violations
      }]);
      const warnMsg = data.warnings_remaining > 0 ? ` [${data.warnings_remaining} warnings remaining]` : '';
      setStatus(`⚠️ WARNING ${data.warning_count}/3${warnMsg}: ${violationSummary}`);
    } else {
      setStatus('✅ No violations');
    }
  };
  const clearOverlay = () => {
    const canvas = overlayRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  };
  const drawOverlayBoxes = boxes => {
    const canvas = overlayRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    // Ensure overlay size matches video
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    boxes.forEach(b => {
      try {
        const [x1, y1, x2, y2] = b.bbox.map(n => Number(n));
        // choose color by type
        let color = '#ff3333'; // default red for prohibited
        if (b.type === 'looking_away') color = '#ff8c00'; // orange
        else if (b.type === 'face_out_of_box') color = '#ffd700'; // gold
        else if (b.label === 'face') color = '#33cc33'; // green

        ctx.strokeStyle = color;
        ctx.lineWidth = 5;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
        const label = `${b.label || 'obj'} ${b.confidence ? Number(b.confidence).toFixed(2) : ''}`;
        ctx.fillStyle = color;
        ctx.font = 'bold 16px sans-serif';
        // draw background for label
        const textW = ctx.measureText(label).width + 8;
        const textH = 18;
        ctx.fillRect(x1 + 2, Math.max(y1 - textH, 2), textW, textH);
        ctx.fillStyle = '#ffffff';
        ctx.fillText(label, x1 + 6, Math.max(y1 - 4, 14));
      } catch (e) {
        // ignore
      }
    });

    // Clear overlay after 1.5s
    setTimeout(clearOverlay, 1500);
  };
  const drawAllowedBox = () => {
    const canvas = overlayRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    // Draw translucent allowed box border
    const w = canvas.width,
      h = canvas.height;
    const x1 = Math.round(w * leftPct);
    const y1 = Math.round(h * topPct);
    const x2 = Math.round(w * rightPct);
    const y2 = Math.round(h * bottomPct);
    ctx.strokeStyle = 'rgba(0,150,255,0.9)';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.setLineDash([]);
  };
  const captureFrames = () => {
    if (!isRunningRef.current || !videoRef.current) {
      console.log('captureFrames early return - isRunning:', isRunning, 'videoRef:', videoRef.current ? 'exists' : 'null');
      return;
    }
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const video = videoRef.current;
    if (video.videoWidth === 0 || video.videoHeight === 0) {
      console.warn('Video dimensions not ready:', video.videoWidth, 'x', video.videoHeight);
      setTimeout(captureFrames, 500);
      return;
    }
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0);

    // draw allowed box every capture so it stays visible
    drawAllowedBox();
    canvas.toBlob(blob => {
      if (!blob) return;
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        // Always send frames as base64 text (more reliable than raw binary)
        const dataUrl = canvas.toDataURL('image/jpeg', 0.7);
        const b64 = dataUrl.split(',')[1];
        if (b64) {
          try {
            const msg = JSON.stringify({
              type: 'frame_b64',
              data: b64
            });
            wsRef.current.send(msg);
            console.log('✅ Frame sent (clientId:', clientId, ') size:', b64.length);
          } catch (e) {
            console.warn('Failed to send frame', e);
          }
        }
      } else {
        const wsState = wsRef.current ? wsRef.current.readyState : 'null';
        console.warn('Frame NOT sent - WS state:', wsState, '(1=OPEN, 2=CLOSING, 3=CLOSED), clientId:', clientId);
      }
    }, 'image/jpeg', 0.7);
    setTimeout(captureFrames, 500);
  };
  const stopSession = async () => {
    try {
      isRunningRef.current = false;
      setIsRunning(false);
      if (videoRef.current && videoRef.current.srcObject) {
        videoRef.current.srcObject.getTracks().forEach(track => track.stop());
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
      try {
        if (pingRef.current) {
          clearInterval(pingRef.current);
          pingRef.current = null;
        }
      } catch (e) {}
      const resp = await fetch(`http://127.0.0.1:8000/api/session/end?client_id=${clientId}`, {
        method: 'POST'
      });
      const summary = await resp.json().catch(() => null);
      setSessionActive(false);
      setStatus('Session ended');
      if (summary) {
        setSessionSummary(summary);
      }
    } catch (error) {
      setStatus('❌ Error: ' + error.message);
    }
  };
  const getReport = async () => {
    try {
      const response = await fetch(`http://127.0.0.1:8000/api/report/${clientId}`);
      const data = await response.json();
      alert(`Violation Report for ${clientId}\n━━━━━━━━━━━━━━━━━━━━━━━\nTotal Violations: ${data.violation_count}\nDuration: ${data.session_duration}\n\nViolation Summary:\n${Object.entries(data.severity_summary).map(([type, count]) => `  • ${type}: ${count}`).join('\n')}`);
    } catch (error) {
      alert('Error fetching report: ' + error.message);
    }
  };

  return (
    <div className="App">
      <div className="container">
        <div className="header">
          <h1>Live Proctoring</h1>
          <p className="student-id">Student: {clientId}</p>
          <div className="warning-counter">
            <span style={{ fontSize: '14px', fontWeight: 'normal', color: warningCount >= 3 ? '#c00' : '#666' }}>
              Warnings: {warningCount}/3
            </span>
            {integrityScore !== null && (
              <span style={{ marginLeft: '1rem', fontSize: '13px', color: '#666' }}>
                Integrity: {integrityScore}
              </span>
            )}
          </div>
        </div>

        <div className="content">
          <div className="video-section">
            <div className="video-container">
              <video ref={videoRef} className="video-feed" playsInline />
              <canvas ref={overlayRef} className="overlay-canvas" />
              <canvas ref={canvasRef} style={{ display: 'none' }} />
              <div className="status-badge">{status}</div>
            </div>
          </div>

          <div className="controls-section">
            <div className="setup-panel">
              <input
                type="text"
                value={clientId}
                onChange={(e) => {
                  setClientId(e.target.value);
                  try { localStorage.setItem('clientId', e.target.value); } catch (err) {}
                }}
                placeholder="Student ID"
                disabled={sessionActive}
                className="student-input"
              />
              {!sessionActive ? (
                <button onClick={startSession} className="btn-start">Start Session</button>
              ) : (
                <button onClick={stopSession} className="btn-stop">End Session</button>
              )}
              {sessionSummary && (
                <div className="session-summary">
                  <strong>Session Summary</strong>
                  <div>Violations: {sessionSummary.violation_count}</div>
                  <div style={{ marginTop: '0.5rem', fontSize: '0.8rem' }}>
                    <strong>Severity:</strong>
                    <pre style={{ whiteSpace: 'pre-wrap', marginTop: '0.25rem' }}>
                      {JSON.stringify(sessionSummary.severity_summary, null, 2)}
                    </pre>
                  </div>
                  <button onClick={() => setSessionSummary(null)} className="btn" style={{ marginTop: '0.5rem' }}>
                    Dismiss
                  </button>
                </div>
              )}
              <div className="calibration">
                All logs are recorded in the backend database. No UI display needed.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
