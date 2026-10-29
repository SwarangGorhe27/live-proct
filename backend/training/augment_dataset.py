"""Dataset augmentation helper for YOLOv8 training.

Produces augmented images and YOLO-format labels based on images in
`backend/training/dataset/images/{train,val}` and labels in
`backend/training/dataset/labels/{train,val}`.

Features:
- Albumentations transforms (rotate, scale, brightness, flip, noise)
- Optional simple multi-face compositing (copy face crops into other images)
- Writes augmented dataset into `backend/training/dataset_aug/`

Usage:
    python augment_dataset.py --src backend/training/dataset --out backend/training/dataset_aug --aug-per-image 3

Note: Requires `albumentations`, `opencv-python` and `tqdm`.
"""

import os
import argparse
import random
import shutil
from pathlib import Path
from tqdm import tqdm

import cv2
import numpy as np
import albumentations as A

# Supported classes: 0->face, 1->cellphone (consistent with existing generator)

def read_yolo_labels(label_path):
    boxes = []
    if not os.path.exists(label_path):
        return boxes
    with open(label_path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5:
                cls = int(parts[0])
                xc = float(parts[1])
                yc = float(parts[2])
                w = float(parts[3])
                h = float(parts[4])
                boxes.append((cls, xc, yc, w, h))
    return boxes


def write_yolo_labels(label_path, boxes):
    os.makedirs(os.path.dirname(label_path), exist_ok=True)
    with open(label_path, 'w') as f:
        for c, xc, yc, w, h in boxes:
            f.write(f"{c} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n")


def yolo_to_xyxy(box, img_w, img_h):
    cls, xc, yc, w, h = box
    x1 = (xc - w / 2.0) * img_w
    y1 = (yc - h / 2.0) * img_h
    x2 = (xc + w / 2.0) * img_w
    y2 = (yc + h / 2.0) * img_h
    return [int(x1), int(y1), int(x2), int(y2), cls]


def xyxy_to_yolo(box, img_w, img_h):
    x1, y1, x2, y2, cls = box
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    xc = (x1 + x2) / 2.0 / img_w
    yc = (y1 + y2) / 2.0 / img_h
    return (cls, xc, yc, float(w) / img_w, float(h) / img_h)


def make_augmentations():
    aug = A.Compose([
        A.HorizontalFlip(p=0.5),
        A.ShiftScaleRotate(shift_limit=0.0625, scale_limit=0.15, rotate_limit=20, p=0.6, border_mode=0),
        A.RandomBrightnessContrast(p=0.5),
        A.GaussNoise(p=0.2),
    ], bbox_params=A.BboxParams(format='yolo', label_fields=['class_labels']))
    return aug


def augment_split(src_images_dir, src_labels_dir, dst_images_dir, dst_labels_dir, aug_per_image=2, multi_face=False):
    os.makedirs(dst_images_dir, exist_ok=True)
    os.makedirs(dst_labels_dir, exist_ok=True)

    image_files = sorted([f for f in os.listdir(src_images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    aug = make_augmentations()

    # collect face crops for simple compositing if requested
    face_crops = []
    if multi_face:
        for img_name in image_files:
            img_path = os.path.join(src_images_dir, img_name)
            label_path = os.path.join(src_labels_dir, Path(img_name).stem + '.txt')
            boxes = read_yolo_labels(label_path)
            if not boxes:
                continue
            img = cv2.imread(img_path)
            if img is None:
                continue
            h, w = img.shape[:2]
            for b in boxes:
                if b[0] == 0:  # face
                    x1, y1, x2, y2, _ = yolo_to_xyxy(b, w, h)
                    # clamp
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w-1, x2), min(h-1, y2)
                    if x2 - x1 > 10 and y2 - y1 > 10:
                        crop = img[y1:y2, x1:x2]
                        face_crops.append(crop)

    counter = 0
    for img_name in tqdm(image_files, desc=f'Augmenting {os.path.basename(src_images_dir)}'):
        src_img_path = os.path.join(src_images_dir, img_name)
        src_label_path = os.path.join(src_labels_dir, Path(img_name).stem + '.txt')
        img = cv2.imread(src_img_path)
        if img is None:
            continue
        h, w = img.shape[:2]
        boxes = read_yolo_labels(src_label_path)
        # write original image to dst
        dst_base = Path(dst_images_dir) / img_name
        cv2.imwrite(str(dst_base), img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        write_yolo_labels(os.path.join(dst_labels_dir, Path(img_name).stem + '.txt'), boxes)
        counter += 1

        # create augmentations
        for ai in range(aug_per_image):
            try:
                # prepare albumentations boxes format: [x_center, y_center, w, h]
                bboxes = []
                class_labels = []
                for b in boxes:
                    class_labels.append(int(b[0]))
                    bboxes.append([b[1], b[2], b[3], b[4]])

                augmented = aug(image=img, bboxes=bboxes, class_labels=class_labels)
                img_aug = augmented['image']
                bboxes_aug = augmented['bboxes']
                labels_aug = augmented['class_labels']

                # write augmented image and labels
                out_name = f"{Path(img_name).stem}_aug{ai}_{counter}.jpg"
                out_img_path = os.path.join(dst_images_dir, out_name)
                cv2.imwrite(out_img_path, img_aug, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

                # convert bboxes back to yolo with pixel sizes
                boxes_to_write = []
                for lbl, bb in zip(labels_aug, bboxes_aug):
                    # bb in format (xc, yc, w, h) normalized
                    boxes_to_write.append((int(lbl), float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])))

                write_yolo_labels(os.path.join(dst_labels_dir, Path(out_name).stem + '.txt'), boxes_to_write)
                counter += 1
            except Exception:
                continue

        # improved multi-face compositing: use rotation, mask smoothing, color-matching
        # and Poisson blending (seamlessClone) when available. Falls back to alpha blending.
        if multi_face and face_crops and random.random() < 0.35:
            try:
                base = img.copy()
                h, w = base.shape[:2]
                crop = random.choice(face_crops)
                ch, cw = crop.shape[:2]
                scale = random.uniform(0.5, 1.0)
                nw, nh = max(8, int(cw * scale)), max(8, int(ch * scale))
                if nw >= w or nh >= h:
                    # skip if too big
                    pass
                else:
                    # resize and apply small random rotation
                    crop_resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
                    angle = random.uniform(-18.0, 18.0)
                    M = cv2.getRotationMatrix2D((nw / 2.0, nh / 2.0), angle, 1.0)
                    crop_rot = cv2.warpAffine(crop_resized, M, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

                    # construct soft mask from crop alpha (non-dark areas)
                    try:
                        gray = cv2.cvtColor(crop_rot, cv2.COLOR_BGR2GRAY)
                        _, mask = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
                        mask = cv2.GaussianBlur(mask, (9, 9), 0)
                        _, mask = cv2.threshold(mask, 10, 255, cv2.THRESH_BINARY)
                    except Exception:
                        mask = 255 * np.ones((nh, nw), dtype=np.uint8)

                    # choose random position ensuring fully inside
                    x = random.randint(10, max(10, w - nw - 10))
                    y = random.randint(10, max(10, h - nh - 10))

                    # color-match: adjust crop brightness to target region mean (HSV V channel)
                    try:
                        dst_region = base[y:y+nh, x:x+nw]
                        if dst_region.shape[0] == nh and dst_region.shape[1] == nw:
                            src_hsv = cv2.cvtColor(crop_rot, cv2.COLOR_BGR2HSV).astype(np.float32)
                            dst_hsv = cv2.cvtColor(dst_region, cv2.COLOR_BGR2HSV).astype(np.float32)
                            src_v = np.mean(src_hsv[:, :, 2])
                            dst_v = np.mean(dst_hsv[:, :, 2])
                            if src_v > 1e-3:
                                ratio = float(dst_v / (src_v + 1e-6))
                                src_hsv[:, :, 2] = np.clip(src_hsv[:, :, 2] * ratio, 0, 255)
                                crop_rot = cv2.cvtColor(src_hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
                    except Exception:
                        pass

                    # perform seamless cloning if available
                    try:
                        center = (x + nw // 2, y + nh // 2)
                        output = cv2.seamlessClone(crop_rot, base, mask, center, cv2.NORMAL_CLONE)
                    except Exception:
                        # fallback to alpha blending using mask
                        try:
                            alpha = (mask.astype(np.float32) / 255.0)[:, :, None]
                            inv = 1.0 - alpha
                            dst_roi = base[y:y+nh, x:x+nw].astype(np.float32)
                            src_roi = crop_rot.astype(np.float32)
                            blended = (alpha * src_roi + inv * dst_roi).astype(np.uint8)
                            output = base.copy()
                            output[y:y+nh, x:x+nw] = blended
                        except Exception:
                            output = base

                    out_name = f"{Path(img_name).stem}_multiface_{counter}.jpg"
                    out_img_path = os.path.join(dst_images_dir, out_name)
                    cv2.imwrite(out_img_path, output, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

                    # write label: add new face bbox in yolo format
                    boxes_existing = boxes.copy()
                    cls_new = 0
                    xc = (x + nw / 2.0) / w
                    yc = (y + nh / 2.0) / h
                    boxes_existing.append((cls_new, xc, yc, float(nw) / w, float(nh) / h))
                    write_yolo_labels(os.path.join(dst_labels_dir, Path(out_name).stem + '.txt'), boxes_existing)
                    counter += 1
            except Exception:
                pass

    return counter


def prepare_augmented_dataset(src_root, out_root, aug_per_image=2, multi_face=False):
    # src_root expected to have images/train, images/val and labels/train, labels/val
    src_images_train = os.path.join(src_root, 'images', 'train')
    src_images_val = os.path.join(src_root, 'images', 'val')
    src_labels_train = os.path.join(src_root, 'labels', 'train')
    src_labels_val = os.path.join(src_root, 'labels', 'val')

    dst_images_train = os.path.join(out_root, 'images', 'train')
    dst_images_val = os.path.join(out_root, 'images', 'val')
    dst_labels_train = os.path.join(out_root, 'labels', 'train')
    dst_labels_val = os.path.join(out_root, 'labels', 'val')

    # clean output
    if os.path.exists(out_root):
        shutil.rmtree(out_root)
    os.makedirs(out_root, exist_ok=True)

    print('Augmenting training split...')
    n1 = augment_split(src_images_train, src_labels_train, dst_images_train, dst_labels_train, aug_per_image=aug_per_image, multi_face=multi_face)
    print('Augmenting validation split...')
    n2 = augment_split(src_images_val, src_labels_val, dst_images_val, dst_labels_val, aug_per_image=max(1, int(aug_per_image/2)), multi_face=False)

    print(f'Augmented dataset created: {n1 + n2} images')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--src', type=str, default=os.path.join(os.path.dirname(__file__), 'dataset'), help='Source dataset root')
    parser.add_argument('--out', type=str, default=os.path.join(os.path.dirname(__file__), 'dataset_aug'), help='Output augmented dataset root')
    parser.add_argument('--aug-per-image', type=int, default=2, help='Augmentations per image')
    parser.add_argument('--multi-face', action='store_true', help='Enable simple multi-face compositing')
    args = parser.parse_args()
    prepare_augmented_dataset(args.src, args.out, aug_per_image=args.aug_per_image, multi_face=args.multi_face)
