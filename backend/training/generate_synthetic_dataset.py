"""Generate a tiny synthetic YOLO-format dataset for 'face' and 'cellphone'.

Creates a small train/val split under backend/training/dataset/ for quick experiments.
"""
import os
import random
from PIL import Image, ImageDraw

ROOT = os.path.dirname(__file__)
OUT = os.path.join(ROOT, 'dataset')
IMG_DIR = os.path.join(OUT, 'images')
LBL_DIR = os.path.join(OUT, 'labels')

os.makedirs(os.path.join(IMG_DIR, 'train'), exist_ok=True)
os.makedirs(os.path.join(IMG_DIR, 'val'), exist_ok=True)
os.makedirs(os.path.join(LBL_DIR, 'train'), exist_ok=True)
os.makedirs(os.path.join(LBL_DIR, 'val'), exist_ok=True)

W, H = 640, 480

def write_yolo_label(path, boxes):
    # boxes: list of (class_id, x_center, y_center, w, h) normalized
    with open(path, 'w') as f:
        for c, xc, yc, w, h in boxes:
            f.write(f"{c} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n")

def make_image(outfile, labels_out, n_faces=1, n_phones=0):
    img = Image.new('RGB', (W, H), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    boxes = []

    # Faces: draw circles/ovals
    for i in range(n_faces):
        fw = random.randint(60, 160)
        fh = int(fw * 1.2)
        x = random.randint(20, W - fw - 20)
        y = random.randint(20, H - fh - 20)
        draw.ellipse([x, y, x + fw, y + fh], outline=(200, 180, 160), width=4)
        xc = (x + fw / 2) / W
        yc = (y + fh / 2) / H
        boxes.append((0, xc, yc, fw / W, fh / H))

    # Phones: draw rectangles
    for j in range(n_phones):
        pw = random.randint(50, 120)
        ph = int(pw * 2.0)
        x = random.randint(10, W - pw - 10)
        y = random.randint(10, H - ph - 10)
        draw.rectangle([x, y, x + pw, y + ph], outline=(80, 200, 220), width=4)
        xc = (x + pw / 2) / W
        yc = (y + ph / 2) / H
        boxes.append((1, xc, yc, pw / W, ph / H))

    img.save(outfile, quality=85)
    write_yolo_label(labels_out, boxes)

def generate(n_train=40, n_val=10):
    random.seed(42)
    for i in range(n_train):
        # mix number of faces and phones
        nf = random.choices([0,1,2], weights=[0.1,0.8,0.1])[0]
        npd = random.choices([0,1], weights=[0.6,0.4])[0]
        imgf = os.path.join(IMG_DIR, 'train', f'train_{i:04d}.jpg')
        labf = os.path.join(LBL_DIR, 'train', f'train_{i:04d}.txt')
        make_image(imgf, labf, n_faces=nf, n_phones=npd)

    for i in range(n_val):
        nf = random.choices([0,1,2], weights=[0.1,0.8,0.1])[0]
        npd = random.choices([0,1], weights=[0.6,0.4])[0]
        imgf = os.path.join(IMG_DIR, 'val', f'val_{i:03d}.jpg')
        labf = os.path.join(LBL_DIR, 'val', f'val_{i:03d}.txt')
        make_image(imgf, labf, n_faces=nf, n_phones=npd)

    print('Synthetic dataset generated:')
    print(' images/train:', len(os.listdir(os.path.join(IMG_DIR, 'train'))))
    print(' images/val:  ', len(os.listdir(os.path.join(IMG_DIR, 'val'))))


if __name__ == '__main__':
    generate(n_train=60, n_val=15)
