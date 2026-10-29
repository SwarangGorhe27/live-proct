import cv2
import numpy as np
from ultralytics import YOLO
import logging
from typing import List, Dict
import os

logger = logging.getLogger(__name__)


def compute_iou(box1, box2):
    """Compute Intersection over Union (IoU) for two boxes [x1,y1,x2,y2]."""
    try:
        x1_min, y1_min, x1_max, y1_max = box1
        x2_min, y2_min, x2_max, y2_max = box2
        # Intersection
        xi_min = max(x1_min, x2_min)
        yi_min = max(y1_min, y2_min)
        xi_max = min(x1_max, x2_max)
        yi_max = min(y1_max, y2_max)
        if xi_max < xi_min or yi_max < yi_min:
            return 0.0
        inter_area = (xi_max - xi_min) * (yi_max - yi_min)
        # Union
        box1_area = (x1_max - x1_min) * (y1_max - y1_min)
        box2_area = (x2_max - x2_min) * (y2_max - y2_min)
        union_area = box1_area + box2_area - inter_area
        if union_area == 0:
            return 0.0
        return float(inter_area) / float(union_area)
    except Exception:
        return 0.0


def deduplicate_boxes(all_boxes, iou_threshold=0.3):
    """Deduplicate overlapping boxes using IoU; keep highest-confidence box."""
    if not all_boxes:
        return []
    # all_boxes = list of [bbox, confidence]
    sorted_boxes = sorted(all_boxes, key=lambda x: x[1] if x[1] is not None else 0.0, reverse=True)
    kept = []
    for box, conf in sorted_boxes:
        is_duplicate = False
        for kept_box, _ in kept:
            iou = compute_iou(box, kept_box)
            if iou > iou_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append((box, conf))
    return kept


class ProctorDetector:
    def __init__(self, model_name: str = None):
        """Initialize the YOLO detector and face detectors (Haar + DNN)."""
        try:
            # Use pre-trained model
            if model_name is None:
                model_name = "yolov8n.pt"
            
            # Load YOLO model with weights_only=False for compatibility with PyTorch safe loading
            import torch
            # Temporarily patch torch.load to allow unsafe loading
            original_load = torch.load
            def patched_load(*args, **kwargs):
                kwargs.setdefault('weights_only', False)
                return original_load(*args, **kwargs)
            torch.load = patched_load
            
            self.yolo_model = YOLO(model_name)
            
            # Restore original torch.load
            torch.load = original_load
            self.confidence_threshold = 0.25  # Lower for better detection

            # Map of COCO class ids -> human-readable (COCO classes)
            self.violation_classes = {
                0: "person",
                32: "sports ball",
                39: "bottle",
                40: "wine glass",
                41: "cup",
                42: "fork",
                43: "knife",
                44: "spoon",
                45: "bowl",
                67: "cellphone"  # Mobile phone from COCO
            }

            # Initialize OpenCV face detector (Haar cascade)
            try:
                self.face_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
                if self.face_cascade.empty():
                    logger.warning("Face cascade loaded but is empty")
            except Exception:
                self.face_cascade = None

            # Initialize DNN face detector (more reliable than Haar)
            self.dnn_net = None
            try:
                # Prefer standard res10 SSD model if present under backend/models
                # Build paths relative to this file (backend/app) to avoid cwd issues
                from pathlib import Path
                backend_dir = Path(__file__).resolve().parents[1]
                prototxt_path = str(backend_dir / 'models' / 'deploy.prototxt')
                caffemodel_path = str(backend_dir / 'models' / 'res10_300x300_ssd_iter_140000.caffemodel')

                # Fallback: check OpenCV sample paths if not present in repo
                if not (os.path.exists(prototxt_path) and os.path.exists(caffemodel_path)):
                    prototxt_path = os.path.join(cv2.data.samples, 'dnn', 'face_detector', 'deploy.prototxt')
                    caffemodel_path = os.path.join(cv2.data.samples, 'dnn', 'face_detector', 'res10_300x300_ssd_iter_140000.caffemodel')

                if os.path.exists(prototxt_path) and os.path.exists(caffemodel_path):
                    self.dnn_net = cv2.dnn.readNetFromCaffe(prototxt_path, caffemodel_path)
                    logger.info(f"✅ DNN face detector loaded from {prototxt_path} and {caffemodel_path}")
                else:
                    logger.debug(f"DNN model files not found: {prototxt_path}, {caffemodel_path}")
            except Exception as e:
                logger.debug(f"DNN face detector not available: {e}")

            # Optional: MediaPipe face detector for robust webcam detection
            self.mp_face = None
            try:
                import mediapipe as mp
                mp_face = mp.solutions.face_detection
                # keep a lightweight detector instance; detection called per-frame
                self.mp_face = mp_face.FaceDetection(min_detection_confidence=0.5)
                logger.info("✅ MediaPipe face detector initialized")
                # Also initialize FaceMesh for landmarks/gaze if available
                try:
                    mp_mesh = mp.solutions.face_mesh
                    # static_image_mode=False for video, max_num_faces=4
                    self.mp_mesh = mp_mesh.FaceMesh(static_image_mode=False, max_num_faces=4,
                                                     refine_landmarks=True, min_detection_confidence=0.5,
                                                     min_tracking_confidence=0.5)
                    logger.info("✅ MediaPipe FaceMesh initialized for landmarks/gaze")
                except Exception as e:
                    self.mp_mesh = None
                    logger.debug(f"MediaPipe FaceMesh not available: {e}")
            except Exception as e:
                self.mp_mesh = None
                logger.debug(f"MediaPipe not available or failed to initialize: {e}")

            # High-accuracy: RetinaFace (via InsightFace) - best accuracy for face detection
            self.retinaface = None
            try:
                import insightface
                app = insightface.app.FaceAnalysis(allowed_modules=['detection'], providers=['CoreML', 'CPUExecutionProvider'])
                app.prepare(ctx_id=-1)  # -1 = CPU only
                self.retinaface = app
                logger.info("✅ RetinaFace (InsightFace) face detector initialized - BEST ACCURACY")
            except Exception as e:
                logger.debug(f"RetinaFace not available: {e}")

            logger.info(f"✅ YOLO model '{model_name}' loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load YOLO model: {e}")
            raise RuntimeError(f"Failed to initialize detector: {e}")

    def detect(self, frame_bytes: bytes, client_config: dict = None) -> List[Dict]:
        """
        Detect proctoring violations in a frame.

        Args:
            frame_bytes: Raw frame data in bytes

        Returns:
            List of violations detected with bounding boxes.
        """
        violations: List[Dict] = []

        try:
            # Convert bytes to numpy array and decode
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                logger.warning("Failed to decode frame")
                return violations

            # Collect face detections from all available detectors (RetinaFace primary + MediaPipe + DNN), then deduplicate
            all_face_detections = []  # list of (box, confidence)

            # Try RetinaFace FIRST (highest accuracy - state-of-the-art)
            try:
                if self.retinaface is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    detections = self.retinaface.get(rgb)
                    if detections:
                        for det in detections:
                            bbox = det.bbox  # [x1, y1, x2, y2]
                            score = float(det.det_score)
                            box = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                            all_face_detections.append((box, score))
                        logger.debug(f"RetinaFace detected {len(detections)} faces with high accuracy")
            except Exception as e:
                logger.debug(f"RetinaFace detection failed: {e}")

            # Try MediaPipe as backup (lightweight, good for webcams)
            try:
                if self.mp_face is not None and len(all_face_detections) == 0:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_results = self.mp_face.process(rgb)
                    if mp_results and getattr(mp_results, 'detections', None):
                        for det in mp_results.detections:
                            score = None
                            try:
                                score = float(det.score[0])
                            except Exception:
                                score = 0.7
                            # bounding box is relative
                            bbox_rel = det.location_data.relative_bounding_box
                            x = int(bbox_rel.xmin * frame.shape[1])
                            y = int(bbox_rel.ymin * frame.shape[0])
                            w = int(bbox_rel.width * frame.shape[1])
                            h = int(bbox_rel.height * frame.shape[0])
                            box = [float(x), float(y), float(x + w), float(y + h)]
                            all_face_detections.append((box, score))
                        if len(all_face_detections) > 0:
                            logger.debug(f"MediaPipe detected {len(all_face_detections)} faces")
            except Exception as e:
                logger.debug(f"MediaPipe detection failed: {e}")

            # Disable Haar cascade (too many false positives even with strict params)
            # Haar detection disabled - using only MediaPipe and DNN which are more reliable

            # Also try DNN
            try:
                if self.dnn_net is not None:
                    blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300), [104, 117, 123], False, False)
                    self.dnn_net.setInput(blob)
                    detections = self.dnn_net.forward()
                    
                    for i in range(detections.shape[2]):
                        confidence = float(detections[0, 0, i, 2])
                        if confidence > 0.7:
                            box = detections[0, 0, i, 3:7] * [frame.shape[1], frame.shape[0], frame.shape[1], frame.shape[0]]
                            (x1, y1, x2, y2) = box.astype('int')
                            box_list = [float(x1), float(y1), float(x2), float(y2)]
                            all_face_detections.append((box_list, confidence))
                    if detections.shape[2] > 0:
                        logger.debug(f"DNN scanned {detections.shape[2]} potential detections")
            except Exception as e:
                logger.debug(f"DNN detection failed: {e}")

            # Deduplicate overlapping boxes from different detectors
            dedup_boxes = deduplicate_boxes(all_face_detections, iou_threshold=0.3)
            final_face_boxes = [[float(x) for x in box] for box, _ in dedup_boxes]
            face_confidences = [conf if conf is not None else 0.8 for _, conf in dedup_boxes]
            face_count = len(final_face_boxes)
            logger.debug(f"After dedup: {face_count} faces from {len(all_face_detections)} detections")

            # Prepare gaze and box checks
            gaze_warnings = []
            face_out_of_box = []

            # Define allowed central box (where face should be). This is a sensible default
            h, w = frame.shape[0], frame.shape[1]

            # Allow override from client_config (values as fractions 0..1)
            cfg = client_config or {}
            left_pct = float(cfg.get('left_pct', 0.25))
            top_pct = float(cfg.get('top_pct', 0.15))
            right_pct = float(cfg.get('right_pct', 0.75))
            bottom_pct = float(cfg.get('bottom_pct', 0.85))

            allowed_box = [
                int(w * left_pct),
                int(h * top_pct),
                int(w * right_pct),
                int(h * bottom_pct)
            ]

            # If FaceMesh available, process landmarks once
            mesh_results = None
            if getattr(self, 'mp_mesh', None) is not None:
                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mesh_results = self.mp_mesh.process(rgb)
                except Exception as e:
                    mesh_results = None
                    logger.debug(f"FaceMesh processing failed: {e}")

            # Match mesh landmarks to final face boxes and compute simple gaze heuristic
            matched_landmarks = [None] * face_count
            if mesh_results and getattr(mesh_results, 'multi_face_landmarks', None):
                try:
                    # For each mesh face, compute its bounding box and match to dedup boxes by IoU / center distance
                    mesh_boxes = []
                    for lm in mesh_results.multi_face_landmarks:
                        xs = [p.x for p in lm.landmark]
                        ys = [p.y for p in lm.landmark]
                        x_min = int(min(xs) * w)
                        x_max = int(max(xs) * w)
                        y_min = int(min(ys) * h)
                        y_max = int(max(ys) * h)
                        mesh_boxes.append(((x_min, y_min, x_max, y_max), lm))

                    # For each final face box, find best matching mesh box by IoU
                    for fi, fbox in enumerate(final_face_boxes):
                        best_i = None
                        best_iou = 0.0
                        for mi, (mbox, lm) in enumerate(mesh_boxes):
                            iou = compute_iou(fbox, mbox)
                            if iou > best_iou:
                                best_iou = iou
                                best_i = mi
                        if best_i is not None and best_iou > 0.05:
                            matched_landmarks[fi] = mesh_boxes[best_i][1]
                except Exception as e:
                    logger.debug(f"Error matching mesh landmarks: {e}")

            # For each face, compute center and check allowed box; compute gaze if landmarks available
            for idx, box in enumerate(final_face_boxes):
                try:
                    x1, y1, x2, y2 = [int(v) for v in box]
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)

                    # Check if face center is inside allowed_box
                    if not (allowed_box[0] <= cx <= allowed_box[2] and allowed_box[1] <= cy <= allowed_box[3]):
                        face_out_of_box.append({"bbox": box, "center": [cx, cy]})

                    # Gaze estimation using landmarks if available
                    lm = matched_landmarks[idx] if idx < len(matched_landmarks) else None
                    if lm is not None:
                        # Use iris/eye corner landmarks if available
                        try:
                            # Common MediaPipe indices: left eye corners 33 (outer), 133 (inner), right 362, 263
                            # Iris center indices 468 (left), 473 (right) when refine_landmarks=True
                            def lm_to_xy(i):
                                p = lm.landmark[i]
                                return (int(p.x * w), int(p.y * h))

                            left_outer = lm_to_xy(33)
                            left_inner = lm_to_xy(133)
                            right_outer = lm_to_xy(362)
                            right_inner = lm_to_xy(263)
                            # prefer iris if available
                            try:
                                left_iris = lm_to_xy(468)
                                right_iris = lm_to_xy(473)
                            except Exception:
                                # fallback to average of eye landmarks
                                left_iris = ((left_outer[0] + left_inner[0]) // 2, (left_outer[1] + left_inner[1]) // 2)
                                right_iris = ((right_outer[0] + right_inner[0]) // 2, (right_outer[1] + right_inner[1]) // 2)

                            # For each eye compute normalized horizontal iris position between inner and outer
                            def normalized_pos(iris, inner, outer):
                                if outer[0] == inner[0]:
                                    return 0.5
                                return (iris[0] - inner[0]) / float(outer[0] - inner[0])

                            left_norm = normalized_pos(left_iris, left_inner, left_outer)
                            right_norm = normalized_pos(right_iris, right_inner, right_outer)
                            avg_norm = (left_norm + (1.0 - right_norm)) / 2.0

                            # avg_norm approx 0.5 when looking center
                            # Relax horizontal thresholds to reduce false positives for small head turns
                            looking_away = False
                            # allow override from client_config
                            HORIZ_LOW = float(cfg.get('horiz_low', 0.20))
                            HORIZ_HIGH = float(cfg.get('horiz_high', 0.80))

                            # Compute a simple vertical normalized score if top/bottom landmarks available
                            # Use MediaPipe approximate indices for eyelid top/bottom when available
                            try:
                                left_top = lm_to_xy(159)
                                left_bottom = lm_to_xy(145)
                                right_top = lm_to_xy(386)
                                right_bottom = lm_to_xy(374)
                                # left vertical normalized
                                def vnorm(iris, top, bottom):
                                    if bottom[1] == top[1]:
                                        return 0.5
                                    return (iris[1] - top[1]) / float(bottom[1] - top[1])
                                lv = vnorm(left_iris, left_top, left_bottom)
                                rv = vnorm(right_iris, right_top, right_bottom)
                                vert_norm = (lv + rv) / 2.0
                            except Exception:
                                vert_norm = 0.5

                            # If user is looking far up/down (vert_norm far from 0.5) tolerate horizontal shift
                            vert_tolerance = float(cfg.get('vert_tolerance', 0.30))
                            if avg_norm < HORIZ_LOW or avg_norm > HORIZ_HIGH:
                                # If vertical is within normal range, mark as looking away
                                if abs(vert_norm - 0.5) < vert_tolerance:
                                    looking_away = True
                                else:
                                    # likely looking up/down; don't treat as horizontal looking away
                                    looking_away = False

                            if looking_away:
                                gaze_warnings.append({"bbox": box, "gaze_score": float(avg_norm)})
                        except Exception as e:
                            logger.debug(f"Error computing gaze for face {idx}: {e}")
                            pass
                except Exception:
                    continue

            # Add gaze/box violations
            if face_out_of_box:
                violations.append({
                    "type": "face_out_of_box",
                    "count": len(face_out_of_box),
                    "severity": "medium",
                    "faces": face_out_of_box,
                    "confidence": 0.85
                })

            if gaze_warnings:
                violations.append({
                    "type": "looking_away",
                    "count": len(gaze_warnings),
                    "severity": "medium",
                    "faces": gaze_warnings,
                    "confidence": 0.75
                })

            # Run YOLO detection for prohibited items
            results = self.yolo_model(frame, conf=self.confidence_threshold, verbose=False)
            
            cellphone_boxes = []
            person_count_yolo = 0

            if results and results[0].boxes:
                result = results[0]
                
                for box in result.boxes:
                    try:
                        # Extract class id and confidence
                        cls = None
                        conf = None
                        if hasattr(box, 'cls'):
                            try:
                                cls = int(box.cls[0])
                            except Exception:
                                cls = int(box.cls)
                        if hasattr(box, 'conf'):
                            try:
                                conf = float(box.conf[0])
                            except Exception:
                                conf = float(box.conf)

                        if cls is None:
                            continue

                        # Extract bounding box coordinates
                        bbox = None
                        if hasattr(box, 'xyxy'):
                            try:
                                coords = box.xyxy[0]
                                bbox = [float(c) for c in coords]
                            except Exception:
                                pass

                        # Determine class name from model if available
                        cls_name = None
                        try:
                            if hasattr(result, 'names') and result.names is not None:
                                # result.names may be a dict or list
                                try:
                                    cls_name = result.names.get(cls, None)
                                except Exception:
                                    try:
                                        cls_name = result.names[int(cls)]
                                    except Exception:
                                        cls_name = None
                        except Exception:
                            cls_name = None

                        # Normalize class name for matching
                        norm_name = ''
                        if cls_name:
                            norm_name = str(cls_name).lower().replace(' ', '_')

                        # Count persons (class 0)
                        if cls == 0 or norm_name == 'person':
                            person_count_yolo += 1

                        # Detect cellphones: accept COCO id 67 or name variants containing 'cell' or 'phone'
                        elif cls == 67 or ('cell' in norm_name) or ('phone' in norm_name):
                            cellphone_boxes.append({
                                "class": cls,
                                "class_name": cls_name if cls_name is not None else "cellphone",
                                "confidence": conf if conf is not None else 0.0,
                                "bbox": bbox
                            })

                    except Exception as e:
                        logger.debug(f"Error processing detection box: {e}")
                        continue

            # Generate violations
            
            # Check for no face
            if face_count == 0:
                violations.append({
                    "type": "no_face",
                    "confidence": 0.9,
                    "severity": "high",
                    "faces": []
                })
            
            # Check for multiple persons
            elif face_count > 1:
                violations.append({
                    "type": "multiple_persons",
                    "count": face_count,
                    "confidence": min(face_confidences) if face_confidences else 0.8,
                    "severity": "high",
                    # include merged face bounding boxes from all detectors with confidences
                    "faces": [
                        {"bbox": box, "confidence": conf}
                        for box, conf in zip(final_face_boxes, face_confidences)
                    ]
                })

            # Check for cellphones
            if cellphone_boxes:
                avg_conf = float(np.mean([d["confidence"] for d in cellphone_boxes]))
                max_conf = max(d["confidence"] for d in cellphone_boxes)
                severity = "high" if max_conf >= 0.5 else "medium"

                violations.append({
                    "type": "prohibited_items",
                    "items": [{"type": "cellphone", "confidence": d["confidence"]} for d in cellphone_boxes],
                    "confidence": avg_conf,
                    "severity": severity,
                    "boxes": cellphone_boxes
                })

            return violations

        except Exception as e:
            logger.error(f"❌ Error during detection: {e}")
            return violations

    def detect_with_metrics(self, frame_bytes: bytes, client_config: dict = None):
        """
        Run detection and compute simple frame-level metrics useful for reporting:
         - integrity_score: 0..100, higher is better
         - visibility_pct: percentage of frame area occupied by the largest detected face

        Returns: (violations, metrics_dict)
        """
        try:
            violations = self.detect(frame_bytes, client_config=client_config)

            # Decode frame to compute areas
            import numpy as np
            import cv2
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                w = h = 0
            else:
                h, w = frame.shape[:2]

            frame_area = float(max(1, w * h))

            # Find face bboxes from violations
            face_bboxes = []
            phone_detected = False
            phone_confidence = 0.0
            looking_away_count = 0

            for v in violations:
                vtype = v.get('type')
                if vtype in ('face_out_of_box', 'looking_away', 'multiple_persons') or v.get('faces'):
                    faces = v.get('faces') or []
                    for f in faces:
                        bbox = None
                        if isinstance(f, dict):
                            bbox = f.get('bbox')
                        elif isinstance(f, list) and len(f) >= 4:
                            bbox = f
                        if bbox and len(bbox) >= 4:
                            try:
                                x1, y1, x2, y2 = [float(x) for x in bbox[:4]]
                                area = max(0.0, (x2 - x1) * (y2 - y1))
                                face_bboxes.append({'bbox':[x1,y1,x2,y2], 'area': area})
                            except Exception:
                                continue
                if vtype == 'prohibited_items' or v.get('boxes'):
                    boxes = v.get('boxes') or []
                    for b in boxes:
                        try:
                            if b.get('class_name') and ('phone' in str(b.get('class_name')).lower() or 'cell' in str(b.get('class_name')).lower()):
                                phone_detected = True
                                phone_confidence = max(phone_confidence, float(b.get('confidence') or 0.0))
                        except Exception:
                            continue
                if vtype == 'looking_away':
                    looking_away_count += int(v.get('count', 1))

            # Compute visibility as largest face area / frame area * 100
            visibility_pct = 0.0
            if face_bboxes:
                largest = max(face_bboxes, key=lambda x: x['area'])
                visibility_pct = float(largest['area'] / frame_area) * 100.0

            # Compute integrity score starting at 100 and applying penalties
            integrity = 100.0
            # penalties
            for v in violations:
                vt = v.get('type')
                if vt == 'no_face':
                    integrity -= 70.0
                elif vt == 'multiple_persons':
                    integrity -= 45.0
                elif vt == 'prohibited_items':
                    # scale by avg confidence (0..1)
                    try:
                        avg_conf = float(v.get('confidence', 0.0))
                    except Exception:
                        avg_conf = 0.0
                    integrity -= min(55.0, 55.0 * avg_conf)
                elif vt == 'looking_away':
                    # penalize per-count with diminishing returns
                    cnt = int(v.get('count', 1))
                    integrity -= min(40.0, 12.0 * cnt)
                elif vt == 'face_out_of_box':
                    integrity -= min(30.0, 10.0 * int(v.get('count', 1)))

            # Adjust integrity by visibility if very small
            if visibility_pct < 5.0:
                integrity -= 10.0

            # Clamp
            integrity = max(0.0, min(100.0, integrity))

            metrics = {
                'integrity_score': round(integrity, 2),
                'visibility_pct': round(visibility_pct, 2),
                'frame_width': int(w),
                'frame_height': int(h)
            }

            return violations, metrics
        except Exception as e:
            logger.debug(f"Failed to compute metrics: {e}")
            return self.detect(frame_bytes, client_config=client_config), {'integrity_score': 0.0, 'visibility_pct': 0.0}
