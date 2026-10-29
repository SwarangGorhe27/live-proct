#!/usr/bin/env bash
set -euo pipefail

# Usage: ./train_yolo.sh --data backend/training/data_template.yaml --model yolov8n.pt --epochs 50

DATA=${1:-backend/training/data_template.yaml}
MODEL=${2:-yolov8n.pt}
EPOCHS=${3:-50}
DEVICE=${4:-auto}

echo "Starting YOLOv8 fine-tuning"
echo "DATA=$DATA MODEL=$MODEL EPOCHS=$EPOCHS DEVICE=$DEVICE"

python - <<PY
from ultralytics import YOLO
import os
import torch

data = '$DATA'
model = '$MODEL'
epochs = int($EPOCHS)
device = '$DEVICE'

# Resolve device: if user requested 'auto', prefer 'mps' on Apple silicon, else fallback to cpu
if device == 'auto':
	if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
		device = 'mps'
	elif torch.cuda.is_available():
		device = 0
	else:
		device = 'cpu'

print('Training with', data, model, epochs, 'device=', device)
YOLO(model).train(data=data, epochs=epochs, imgsz=640, device=device)
PY

echo "Training finished. Check runs/train for outputs."
