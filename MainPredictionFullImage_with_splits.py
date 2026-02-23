# -*- coding: utf-8 -*-
"""
MainPredictionFullImage.py
--------------------------

این اسکریپت همان پایپ‌لاین نوت‌بوک Prediction_Full_Image.ipynb را به صورت یک فایل .py اجرا می‌کند
و در نهایت خروجی زیر را چاپ می‌کند:

Most frequent prediction: <XYZ> (freq=<n>)
Number of tiles: [ ... ]   # شماره‌ tile ها (1..9)

✅ تنها ورودی‌های الزامی طبق درخواست شما:
1) INPUT_PATH  (مسیر تصویر کامل کپچا)
2) model = load_model("captcha_model_segmented.h5")

پیش‌نیازها:
- opencv-python
- numpy
- tensorflow (برای load_model)

نکته:
- خروجی‌ها داخل پوشه‌ای کنار تصویر ورودی ساخته می‌شوند (prediction_test_run).
"""

from __future__ import annotations

import os
from pathlib import Path
from collections import Counter, defaultdict

import cv2
import numpy as np

from tensorflow.keras.models import load_model


# =========================
# ✅ فقط این‌ها را تنظیم کنید
# =========================
model = load_model("captcha_model_scale_resize55.h5")

INPUT_PATH = r"E:\Benyamin\job\freelanser\captcha6_3\Test_Folder\test1.jpg"



# =========================
# تنظیمات داخلی (اختیاری)
# =========================
ROI_HEIGHT = 680          # فقط قسمت بالایی تصویر برای پیدا کردن 9 مربع
AREA_THRESHOLD = 15000    # فیلتر حذف نویز در پیدا کردن 9 مربع
TILE_PAD = 2              # پد برای بریدن tile

BORDER_PX = 8             # keep_only_inside_of_frame
TRAIN_W, TRAIN_H = 150, 80
MASK_PAD = 2              # crop_center_resize
SLICE_OVERLAP = 5         # split_into_3_vertical_slices

MODEL_IN_H, MODEL_IN_W = 80, 55  # preprocess_image

# خروجی‌ها
OUTPUT_ROOT = Path(INPUT_PATH).resolve().parent / "prediction_test_run"
TILES_DIR = OUTPUT_ROOT / "tiles_9"
CONVERTED_DIR = OUTPUT_ROOT / "Converted_to_train_image"
MASK_DIR = OUTPUT_ROOT / "Mask_Moline_Centered"

# ✅ خروجی جدید برای ذخیره‌ی split ها
SPLITS_DIR = OUTPUT_ROOT / "splits_3"          # سه برش برای هر tile
PREPROCESSED_SPLITS_DIR = OUTPUT_ROOT / "splits_3_preprocessed"  # (اختیاری) ورودی دقیق مدل 60x80

# کنترل ذخیره‌سازی (اختیاری)
SAVE_SPLITS = True
SAVE_PREPROCESSED_SPLITS = False  # اگر True شود، اسلایس‌های resize شده (60x80) هم ذخیره می‌شوند


def extract_9_tiles_full_image(
    input_path: str | os.PathLike,
    out_dir: Path,
    roi_height: int = ROI_HEIGHT,
    area_threshold: int = AREA_THRESHOLD,
    pad: int = TILE_PAD,
) -> None:
    """مرحله 1: از تصویر کامل، 9 tile را جدا و ذخیره می‌کند."""
    out_dir.mkdir(parents=True, exist_ok=True)

    img = cv2.imread(str(input_path))
    if img is None:
        raise FileNotFoundError(f"Could not read: {input_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # فقط قسمت بالایی تصویر
    roi = gray[:roi_height, :]

    blur = cv2.GaussianBlur(roi, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dil = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes: list[tuple[int, int, int, int]] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h > area_threshold:
            boxes.append((x, y, w, h))

    boxes = sorted(boxes, key=lambda b: (b[1], b[0]))

    if len(boxes) != 9:
        raise RuntimeError(
            f"Expected 9 boxes, but found {len(boxes)}.\n"
            f"Try adjusting ROI_HEIGHT={roi_height} or AREA_THRESHOLD={area_threshold}."
        )

    # مرتب‌سازی دقیق‌تر: 3تایی‌های هر ردیف را بر اساس x مرتب می‌کنیم
    rows = [boxes[i:i + 3] for i in range(0, 9, 3)]
    rows = [sorted(r, key=lambda b: b[0]) for r in rows]
    boxes = [b for r in rows for b in r]

    H, W = img.shape[:2]
    for i, (x, y, w, h) in enumerate(boxes, start=1):
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(W, x + w + pad)
        y2 = min(H, y + h + pad)

        tile = img[y1:y2, x1:x2]
        out_path = out_dir / f"tile_{i:02d}.png"
        # cv2.imwrite(str(out_path), tile)  # ✅ COMMENTED (save)


def keep_only_inside_of_frame(img_bgr: np.ndarray, border_px: int = BORDER_PX) -> np.ndarray:
    """مرحله 2: فقط داخل قاب (frame) را نگه می‌دارد و بیرون را صفر/شفاف می‌کند (BGRA)."""
    h, w = img_bgr.shape[:2]

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    edges = cv2.Canny(gray, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise RuntimeError("هیچ کانتوری پیدا نشد. آستانه‌های Canny را باید تغییر بدیم.")

    c = max(contours, key=cv2.contourArea)

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(mask, [c], -1, 255, thickness=-1)

    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    inner = (dist > border_px).astype(np.uint8) * 255

    out = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2BGRA)
    out[..., 3] = inner          # alpha
    out[inner == 0, 0:3] = 0     # بیرون ماسک
    return out


def crop_to_alpha(bgra: np.ndarray, pad: int = 0) -> np.ndarray:
    """مرحله 2 (ادامه): بر اساس کانال آلفا کراپ می‌کند."""
    a = bgra[..., 3]
    ys, xs = np.where(a > 0)
    if len(xs) == 0 or len(ys) == 0:
        raise RuntimeError("آلفا کاملاً صفر شد. border_px احتمالاً زیادی بزرگه.")

    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()

    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(bgra.shape[1] - 1, x1 + pad)
    y1 = min(bgra.shape[0] - 1, y1 + pad)

    return bgra[y0:y1 + 1, x0:x1 + 1]


def convert_tiles_to_train_size(
    tiles_dir: Path,
    out_dir: Path,
    out_w: int = TRAIN_W,
    out_h: int = TRAIN_H,
    border_px: int = BORDER_PX,
    pad: int = 0,
) -> None:
    """مرحله 3: هر tile را به سایز آموزش (150x80) تبدیل می‌کند."""
    out_dir.mkdir(parents=True, exist_ok=True)
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

    tile_paths = sorted([p for p in tiles_dir.iterdir() if p.is_file() and p.suffix.lower() in exts])
    if not tile_paths:
        raise RuntimeError(f"No tile images found in: {tiles_dir}")

    for in_path in tile_paths:
        out_path = out_dir / f"{in_path.stem}_{out_w}x{out_h}.png"

        img = cv2.imread(str(in_path), cv2.IMREAD_COLOR)
        if img is None:
            # print("❌ تصویر خوانده نشد، رد شد:", in_path)  # ✅ COMMENTED (print)
            continue

        bgra = keep_only_inside_of_frame(img, border_px=border_px)
        cropped = crop_to_alpha(bgra, pad=pad)

        cropped_bgr = cropped[..., :3]
        resized = cv2.resize(cropped_bgr, (out_w, out_h), interpolation=cv2.INTER_AREA)

        # ok = cv2.imwrite(str(out_path), resized)  # ✅ COMMENTED (save)
        ok = True  # (برای جلوگیری از ارور Save failed در صورت استفاده از ok)
        if not ok:
            raise RuntimeError(f"Save failed: {out_path}")


def load_images_and_labels_from_folder(root_dir: Path) -> tuple[list[np.ndarray], list[str]]:
    """مرحله 4: تصاویر را لود می‌کند و label_str = آخرین 3 کاراکتر اسم فایل (برای نام‌گذاری ماسک‌ها)."""
    images: list[np.ndarray] = []
    labels: list[str] = []

    for current_dir, _, files in os.walk(str(root_dir)):
        for filename in sorted(files):
            if not filename.lower().endswith(".png"):
                continue

            name_without_ext = os.path.splitext(filename)[0]
            label_str = name_without_ext[-3:]  # در نوت‌بوک: معمولاً "x80"

            path = os.path.join(current_dir, filename)
            img = cv2.imread(path)
            if img is not None:
                images.append(img)
                labels.append(label_str)

    return images, labels


def remove_horizontal_lines(bin_img: np.ndarray, line_frac: float = 0.35) -> tuple[np.ndarray, np.ndarray]:
    """مرحله 5 (بخش 1): حذف خط‌های افقی (مثل underline)."""
    h, w = bin_img.shape
    k = max(10, int(w * line_frac))
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))
    lines = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, horiz_kernel, iterations=1)
    cleaned = cv2.subtract(bin_img, lines)
    return cleaned, lines


def segment_digits_kmeans(img_bgr: np.ndarray, K: int = 2, median_ksize: int = 3) -> np.ndarray:
    """مرحله 5 (بخش 2): سگمنت کردن رقم‌ها با KMeans روی رنگ‌ها و خروجی ماسک باینری."""
    img_denoised = cv2.medianBlur(img_bgr, median_ksize)
    img_rgb = cv2.cvtColor(img_denoised, cv2.COLOR_BGR2RGB)

    X = img_rgb.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1.0)
    _, labels_k, _ = cv2.kmeans(X, K, None, criteria, 10, cv2.KMEANS_PP_CENTERS)
    labels_k = labels_k.flatten()

    counts = np.bincount(labels_k, minlength=K)
    digit_cluster = int(np.argmin(counts))

    mask = (labels_k == digit_cluster).astype(np.uint8).reshape(img_rgb.shape[:2]) * 255
    return mask


def crop_center_resize(bin_img: np.ndarray, out_w: int = TRAIN_W, out_h: int = TRAIN_H, pad: int = MASK_PAD) -> np.ndarray:
    """مرحله 5 (بخش 3): کراپ روی پیکسل‌های سفید، resize با حفظ نسبت، و قرار دادن در مرکز canvas."""
    ys, xs = np.where(bin_img > 0)
    canvas = np.zeros((out_h, out_w), dtype=np.uint8)

    if len(xs) == 0 or len(ys) == 0:
        return canvas

    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()

    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(bin_img.shape[1] - 1, x1 + pad)
    y1 = min(bin_img.shape[0] - 1, y1 + pad)

    crop = bin_img[y0:y1 + 1, x0:x1 + 1]
    ch, cw = crop.shape[:2]

    scale = min(out_w / cw, out_h / ch)
    new_w = max(1, int(round(cw * scale)))
    new_h = max(1, int(round(ch * scale)))

    resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

    x_off = (out_w - new_w) // 2
    y_off = (out_h - new_h) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    return canvas


def build_centered_masks(images: list[np.ndarray], labels: list[str], out_dir: Path) -> None:
    """مرحله 5: تولید ماسک‌های نهایی و ذخیره با نام idx_<label>.png (مثل 0_x80.png)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    for idx, (img, label) in enumerate(zip(images, labels)):
        mask = segment_digits_kmeans(img, K=2, median_ksize=3)
        mask_noline, _ = remove_horizontal_lines(mask, line_frac=0.35)
        final_mask = crop_center_resize(mask_noline, out_w=TRAIN_W, out_h=TRAIN_H, pad=MASK_PAD)

        label_str = "".join(str(d) for d in label)  # در نوت‌بوک همین بود
        save_path = out_dir / f"{idx}_{label_str}.png"
        # cv2.imwrite(str(save_path), final_mask)  # ✅ COMMENTED (save)


def split_into_3_vertical_slices(img: np.ndarray, overlap: int = SLICE_OVERLAP):
    """مرحله 7: تقسیم تصویر به 3 برش عمودی (با همپوشانی)."""
    if img is None:
        raise ValueError("img is None")

    H, W = img.shape[:2]
    cut1 = W // 3
    cut2 = 2 * W // 3

    x1a = max(0, cut1 - overlap)
    x1b = min(W, cut1 + overlap)

    x2a = max(0, cut2 - overlap)
    x2b = min(W, cut2 + overlap)

    if img.ndim == 2:
        s1 = img[:, :x1b]
        s2 = img[:, x1a:x2b]
        s3 = img[:, x2a:]
    elif img.ndim == 3:
        s1 = img[:, :x1b, :]
        s2 = img[:, x1a:x2b, :]
        s3 = img[:, x2a:, :]
    else:
        raise ValueError(f"Expected (H,W) or (H,W,C), got {img.shape}")

    return s1, s2, s3


def preprocess_image(img: np.ndarray) -> np.ndarray:
    """مرحله 6/7: آماده‌سازی ورودی برای مدل (1,80,60,1)."""
    img = cv2.resize(img, (MODEL_IN_W, MODEL_IN_H))

    if img.ndim == 3 and img.shape[-1] == 3:
        img = img.mean(axis=2)

    if img.ndim == 2:
        img = img[..., None]

    img = img.astype(np.float32)
    img = np.expand_dims(img, 0)
    return img


def preprocess_to_model_image(img: np.ndarray) -> np.ndarray:
    """
    ✅ فقط برای ذخیره‌ی ورودی مدل (نمایش/دیباگ):
    خروجی uint8 تک‌کاناله با سایز (80,60) که دقیقاً همان چیزی است که مدل می‌بیند.
    """
    im = cv2.resize(img, (MODEL_IN_W, MODEL_IN_H))
    if im.ndim == 3 and im.shape[-1] == 3:
        im = im.mean(axis=2)
    im = np.clip(im, 0, 255).astype(np.uint8)
    return im


def predict_digit(img_slice: np.ndarray) -> str:
    """مرحله 8: پیش‌بینی یک رقم از یک اسلایس."""
    x = preprocess_image(img_slice)
    pred = model.predict(x, verbose=0)
    digit = int(np.argmax(pred, axis=-1).ravel()[0])
    return str(digit)


def find_mask_path_for_idx(mask_dir: Path, idx: int) -> Path | None:
    """اگر اسم دقیق فایل را ندانیم، اولین فایل idx_*.png را پیدا می‌کنیم."""
    candidates = sorted(mask_dir.glob(f"{idx}_*.png"))
    return candidates[0] if candidates else None


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ensure_dir(OUTPUT_ROOT)

    # print("========== Step 1/8: Extract 9 tiles ==========")  # ✅ COMMENTED (print)
    extract_9_tiles_full_image(INPUT_PATH, TILES_DIR)

    # print("========== Step 2-3/8: Convert tiles to train size ==========")  # ✅ COMMENTED (print)
    convert_tiles_to_train_size(TILES_DIR, CONVERTED_DIR)

    # print("========== Step 4/8: Load converted images ==========")  # ✅ COMMENTED (print)
    images, labels = load_images_and_labels_from_folder(CONVERTED_DIR)
    if len(images) == 0:
        raise RuntimeError("No converted images loaded. Check previous steps.")
    # print("Loaded images:", len(images))  # ✅ COMMENTED (print)

    # print("========== Step 5/8: Build centered masks ==========")  # ✅ COMMENTED (print)
    build_centered_masks(images, labels, MASK_DIR)

    # ✅ فولدرهای ذخیره split ها
    if SAVE_SPLITS:
        ensure_dir(SPLITS_DIR)
    if SAVE_PREPROCESSED_SPLITS:
        ensure_dir(PREPROCESSED_SPLITS_DIR)

    # print("========== Step 6-8/8: Predict & choose tiles ==========")  # ✅ COMMENTED (print)
    pred_strings: dict[int, str] = {}

    for idx in range(9):
        p = find_mask_path_for_idx(MASK_DIR, idx)
        if p is None:
            # print(f"[WARN] Missing mask for idx={idx}")  # ✅ COMMENTED (print)
            continue

        # پیشنهاد: برای ماسک‌ها بهتره grayscale بخونیم (اختیاری)
        img_raw = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img_raw is None:
            # print(f"[WARN] Could not read: {p}")  # ✅ COMMENTED (print)
            continue

        s1, s2, s3 = split_into_3_vertical_slices(img_raw, overlap=SLICE_OVERLAP)

        # ✅ ذخیره‌ی split ها (خام)
        if SAVE_SPLITS:
            tile_dir = SPLITS_DIR / f"tile_{idx+1:02d}"
            ensure_dir(tile_dir)
            # cv2.imwrite(str(tile_dir / "slice_1.png"), s1)  # ✅ COMMENTED (save)
            # cv2.imwrite(str(tile_dir / "slice_2.png"), s2)  # ✅ COMMENTED (save)
            # cv2.imwrite(str(tile_dir / "slice_3.png"), s3)  # ✅ COMMENTED (save)

        # ✅ (اختیاری) ذخیره‌ی ورودی دقیق مدل (60x80)
        if SAVE_PREPROCESSED_SPLITS:
            tile_dir = PREPROCESSED_SPLITS_DIR / f"tile_{idx+1:02d}"
            ensure_dir(tile_dir)
            # cv2.imwrite(str(tile_dir / "slice_1_60x80.png"), preprocess_to_model_image(s1))  # ✅ COMMENTED (save)
            # cv2.imwrite(str(tile_dir / "slice_2_60x80.png"), preprocess_to_model_image(s2))  # ✅ COMMENTED (save)
            # cv2.imwrite(str(tile_dir / "slice_3_60x80.png"), preprocess_to_model_image(s3))  # ✅ COMMENTED (save)

        try:
            d1 = predict_digit(s1)
            d2 = predict_digit(s2)
            d3 = predict_digit(s3)
        except Exception as e:
            # print(f"[WARN] Prediction failed for idx={idx}: {e}")  # ✅ COMMENTED (print)
            continue

        pred_strings[idx] = f"{d1}{d2}{d3}"
        # print(pred_strings[idx])  # ✅ COMMENTED (print)

    if not pred_strings:
        raise RuntimeError("No valid predictions produced.")

    freq = Counter(pred_strings.values())
    max_freq = max(freq.values())
    most_common_results = [res for res, c in freq.items() if c == max_freq]

    result_to_indices = defaultdict(list)
    for idx, res in pred_strings.items():
        if res in most_common_results:
            result_to_indices[res].append(idx)

    for res in most_common_results:
        indices = result_to_indices[res]
        indices_plus_1 = [i + 1 for i in indices]
        # print(f"Most frequent prediction: {res} (freq={max_freq})")  # ✅ COMMENTED (print)
        print("Number of tiles:", indices_plus_1)  # ✅ ONLY PRINT KEPT

    # print("\nOutputs saved in:", OUTPUT_ROOT)  # ✅ COMMENTED (print)
    if SAVE_SPLITS:
        # print("Split tiles saved in:", SPLITS_DIR)  # ✅ COMMENTED (print)
        pass
    if SAVE_PREPROCESSED_SPLITS:
        # print("Preprocessed splits saved in:", PREPROCESSED_SPLITS_DIR)  # ✅ COMMENTED (print)
        pass


if __name__ == "__main__":
    main()