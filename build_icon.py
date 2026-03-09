"""
Run once locally to generate assets/icon.ico, then commit the .ico file.
Usage: python build_icon.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

SIZES = [256, 128, 64, 48, 32, 16]


def make_frame(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = max(1, size // 16)
    # Outer circle — cyan
    draw.ellipse([m, m, size - m, size - m], fill=(0, 200, 255, 255))
    # Inner circle — darker blue
    q = size // 4
    draw.ellipse([q, q, size - q, size - q], fill=(0, 100, 160, 255))
    return img


def main():
    assets = Path(__file__).parent / "assets"
    assets.mkdir(exist_ok=True)
    frames = [make_frame(s) for s in SIZES]
    out = assets / "icon.ico"
    frames[0].save(
        out,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    print(f"Written: {out}")


if __name__ == "__main__":
    main()
