Fine-tuning YOLOv8 for Better Face & Phone Detection

Overview
--
This document describes how to fine-tune a YOLOv8 model (Ultralytics) on a custom dataset to improve detection of faces, cellphones, and other exam-proctoring-relevant objects.

Prereqs
--
- Python 3.8+ with `ultralytics` installed in an environment with GPU (recommended).
- Dataset in YOLO format (images + `.txt` label files) or COCO format.

Data recommendations
--
- Collect diverse images of students using webcams in realistic exam setups.
- Annotate bounding boxes for `face`, `cellphone`, and any other classes you want to detect.
- Aim for at least a few hundred images per class; more is better.

Directory layout (YOLO format)
--
dataset/
  images/
    train/
    val/
  labels/
    train/
    val/

Example `data.yaml` (below) should point to the `images/train`, `images/val` paths and list `names`.

Training
--
1. Create a `data.yaml` file (see `data_template.yaml`).
2. Run the ultralytics train command (example):

```bash
source ../backend_env/bin/activate
pip install -U ultralytics
ultralytics train data=backend/training/data_template.yaml model=yolov8n.pt epochs=50 imgsz=640 batch=16 device=0
```

Tips
--
- Use `yolov8n.pt` for fast experiments, then move to `yolov8s`/`yolov8m` if you need better accuracy.
- Augmentations: horizontal flip, brightness, small rotations. Keep them realistic.
- If faces are small in frames, set `imgsz` higher (e.g., 960) or use multi-scale training.

Exporting
--
After training, export the best model for inference:

```bash
ultralytics export model=./runs/train/exp/weights/best.pt format=onnx
```

Integration
--
Replace `yolov8n.pt` in `backend/app/detector.py` with your trained `best.pt` (or point the `ProctorDetector` initializer to the path).
