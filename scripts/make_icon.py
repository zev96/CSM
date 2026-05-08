"""Generate CSM app icon: deep-blue rounded square with a document + pen-nib glyph."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "csm_gui" / "assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)
ICO_PATH = OUT_DIR / "csm.ico"
PNG_PATH = OUT_DIR / "csm.png"

BG = (31, 111, 235)        # #1F6FEB
PAPER = (255, 255, 255)
PAPER_SHADOW = (220, 232, 250)
LINE = (180, 205, 240)
NIB_BODY = (255, 255, 255)
NIB_TIP = (255, 200, 80)   # warm gold
NIB_SLIT = (31, 111, 235)


def render(size: int) -> Image.Image:
    # Render at 4x then downsample for crisp anti-aliasing.
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Background: rounded square
    radius = int(s * 0.22)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=radius, fill=BG)

    # Document (slightly tilted look via offset shadow + main paper)
    pad = int(s * 0.20)
    doc_l = pad
    doc_t = int(s * 0.16)
    doc_r = s - pad
    doc_b = s - int(s * 0.18)
    fold = int(s * 0.14)  # folded corner size

    # Drop shadow behind paper
    shadow_off = int(s * 0.018)
    d.rounded_rectangle(
        (doc_l + shadow_off, doc_t + shadow_off, doc_r + shadow_off, doc_b + shadow_off),
        radius=int(s * 0.025),
        fill=(0, 0, 0, 60),
    )

    # Paper body with a folded top-right corner (drawn as polygon)
    paper_poly = [
        (doc_l, doc_t),
        (doc_r - fold, doc_t),
        (doc_r, doc_t + fold),
        (doc_r, doc_b),
        (doc_l, doc_b),
    ]
    d.polygon(paper_poly, fill=PAPER)
    # Folded triangle (lighter)
    d.polygon(
        [(doc_r - fold, doc_t), (doc_r, doc_t + fold), (doc_r - fold, doc_t + fold)],
        fill=PAPER_SHADOW,
    )
    # Crease line
    d.line(
        [(doc_r - fold, doc_t), (doc_r - fold, doc_t + fold), (doc_r, doc_t + fold)],
        fill=LINE,
        width=max(2, s // 256),
    )

    # Text lines on the document
    line_w = max(3, s // 110)
    line_left = doc_l + int(s * 0.07)
    line_right = doc_r - int(s * 0.07)
    line_y0 = doc_t + int(s * 0.18)
    gap = int(s * 0.075)
    for i in range(3):
        y = line_y0 + i * gap
        right = line_right if i != 2 else line_right - int(s * 0.10)
        d.rounded_rectangle((line_left, y, right, y + line_w), radius=line_w // 2, fill=LINE)

    # Pen / nib — diagonal, tip pointing down-right toward bottom-right of doc
    # Define nib axis from (x1,y1) shaft-end to (x2,y2) tip
    cx, cy = int(s * 0.66), int(s * 0.66)
    length = int(s * 0.42)
    width = int(s * 0.16)

    # Shaft (rounded rectangle rotated 45° via two ellipses + rect, drawn on overlay)
    overlay = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    # Build a horizontal nib then rotate
    nib_canvas = Image.new("RGBA", (length, width), (0, 0, 0, 0))
    nd = ImageDraw.Draw(nib_canvas)
    # Shaft: rounded rect on left ~70%
    shaft_end = int(length * 0.62)
    nd.rounded_rectangle((0, 0, shaft_end, width - 1), radius=width // 2, fill=NIB_BODY)
    nd.line((width // 2, width // 2, shaft_end - 4, width // 2),
            fill=(31, 111, 235, 80), width=max(2, width // 18))
    # Nib triangle: from shaft end to tip
    tip_x = length - 1
    nd.polygon(
        [(shaft_end, 0), (shaft_end, width - 1), (tip_x, width // 2)],
        fill=NIB_BODY,
    )
    # Gold tip at the very end
    gold_start = int(length * 0.86)
    nd.polygon(
        [(gold_start, int(width * 0.22)),
         (gold_start, int(width * 0.78)),
         (tip_x, width // 2)],
        fill=NIB_TIP,
    )
    # Center slit
    nd.line(
        (int(length * 0.50), width // 2, tip_x - 2, width // 2),
        fill=NIB_SLIT,
        width=max(2, width // 14),
    )
    # Vent hole
    r = max(3, width // 8)
    hx = int(length * 0.58)
    nd.ellipse((hx - r, width // 2 - r, hx + r, width // 2 + r), fill=NIB_SLIT)

    # Rotate the nib so the tip points down-right (~30° below horizontal)
    rotated = nib_canvas.rotate(-30, resample=Image.BICUBIC, expand=True)
    rw, rh = rotated.size
    # Position so tip lands near bottom-right of the document
    target_tip = (int(s * 0.84), int(s * 0.86))
    # Tip in rotated image is roughly at the rightmost-lowest area; estimate
    paste_x = target_tip[0] - rw + int(rw * 0.08)
    paste_y = target_tip[1] - rh + int(rh * 0.18)
    overlay.alpha_composite(rotated, (paste_x, paste_y))

    img = Image.alpha_composite(img, overlay)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [render(sz) for sz in sizes]
    images[-1].save(PNG_PATH)
    images[-1].save(
        ICO_PATH,
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[:-1],
    )
    print(f"wrote {ICO_PATH}")
    print(f"wrote {PNG_PATH}")


if __name__ == "__main__":
    main()
