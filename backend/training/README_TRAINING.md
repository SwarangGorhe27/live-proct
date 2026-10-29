Training augmentation and harness

Files:
- `augment_dataset.py`: create augmented YOLO-format dataset from `backend/training/dataset` into `backend/training/dataset_aug`.
- `train_harness.py`: training script that uses `ultralytics.YOLO` to fine-tune a model.
- `requirements_training.txt`: minimal Python packages needed for augmentation + training.

Quick start (macOS/Linux):

1. Create a virtual environment and install packages:

```bash
python -m venv backend_env_train
source backend_env_train/bin/activate
pip install -r backend/training/requirements_training.txt
```

2. Generate or prepare dataset (there's already a small synthetic generator):

```bash
python backend/training/generate_synthetic_dataset.py
```

3. Augment the dataset (creates `backend/training/dataset_aug`):

```bash
python backend/training/augment_dataset.py --src backend/training/dataset --out backend/training/dataset_aug --aug-per-image 3 --multi-face
```

4. Edit `backend/training/data_template.yaml` or create a new YAML that points `train:` and `val:` to the `dataset_aug/images/*` directories.

5. Train using the harness:

```bash
python backend/training/train_harness.py --data backend/training/data_template.yaml --model yolov8n.pt --epochs 50
```

Notes:
- `augment_dataset.py` uses `albumentations`. If you have GPU/CUDA, `ultralytics` will use it when available.
- The multi-face compositing is a simple overlay; for high-quality synthetic multi-face examples consider using more advanced blending or real multi-face photos.
