"""Training harness for YOLOv8 using ultralytics.

Usage:
    python train_harness.py --data backend/training/data_template.yaml --model yolov8n.pt --epochs 50 --device auto

This script expects the dataset to be prepared in YOLO format. Use `augment_dataset.py` to create
`backend/training/dataset_aug` and then edit the data YAML to point to the augmented dataset, or
pass a custom data yaml.
"""
import argparse
from ultralytics import YOLO
import torch


def resolve_device(device):
    if device == 'auto':
        # macOS mps support
        try:
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                return 'mps'
        except Exception:
            pass
        if torch.cuda.is_available():
            return 0
        return 'cpu'
    return device


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=str, default='backend/training/data_template.yaml')
    parser.add_argument('--model', type=str, default='yolov8n.pt')
    parser.add_argument('--epochs', type=int, default=50)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--device', type=str, default='auto')
    args = parser.parse_args()

    device = resolve_device(args.device)
    print(f"Training with data={args.data} model={args.model} epochs={args.epochs} device={device}")

    yolo = YOLO(args.model)
    yolo.train(data=args.data, epochs=args.epochs, imgsz=args.imgsz, device=device)
    print('Training finished. Check runs/train for outputs')

if __name__ == '__main__':
    main()
