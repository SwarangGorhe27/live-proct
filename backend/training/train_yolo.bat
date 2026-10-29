@echo off
REM Live Proctoring YOLO Training Script (Windows)

setlocal enabledelayedexpansion

REM Parse arguments
set DATA=%1
set MODEL=%2
set EPOCHS=%3
set DEVICE=%4

if "!DATA!"=="" set DATA=backend\training\data_template.yaml
if "!MODEL!"=="" set MODEL=yolov8n.pt
if "!EPOCHS!"=="" set EPOCHS=50
if "!DEVICE!"=="" set DEVICE=auto

echo.
echo Starting YOLOv8 fine-tuning
echo DATA=!DATA! MODEL=!MODEL! EPOCHS=!EPOCHS! DEVICE=!DEVICE!
echo.

REM Get the directory where this batch file is located
set PROJECT_ROOT=%~dp0
set PROJECT_ROOT=%PROJECT_ROOT:~0,-1%

set PYTHON_BIN=%PROJECT_ROOT%\backend_env\Scripts\python.exe

cd /d "%PROJECT_ROOT%"

REM Run training
%PYTHON_BIN% - <<PYTHON_SCRIPT
from ultralytics import YOLO
import os
import torch

data = r'!DATA!'
model = r'!MODEL!'
epochs = !EPOCHS!
device = '!DEVICE!'

print(f"Loading YOLO model: {model}")
yolo = YOLO(model)

print(f"Training on device: {device}")
print(f"Data config: {data}")
print(f"Epochs: {epochs}")

results = yolo.train(
    data=data,
    epochs=int(epochs),
    imgsz=640,
    device=device if device != 'auto' else 0,
    patience=20,
    batch=16
)

print("✅ Training completed!")
PYTHON_SCRIPT

if %ERRORLEVEL% neq 0 (
    echo ❌ Training failed
    pause
    exit /b 1
)

echo.
echo ✅ Training script completed!
pause
