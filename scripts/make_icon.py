"""Draws assets/icon.png and assets/icon.ico (run once; the results are committed).

A CT-blue speech bubble on a slate tile, with "text" bars inside; the last
bar is T gold, the translated line.
"""

from pathlib import Path

from PIL import Image, ImageDraw

SLATE = (32, 36, 44, 255)
BLUE = (110, 143, 208, 255)
INK = (24, 27, 33, 255)
GOLD = (227, 163, 59, 255)

S = 1024  # draw large, downsample for smooth edges


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=SLATE)
    # Bubble
    d.rounded_rectangle((180, 220, 844, 690), radius=120, fill=BLUE)
    d.polygon([(300, 660), (300, 850), (480, 680)], fill=BLUE)
    # Text bars
    d.rounded_rectangle((270, 330, 750, 395), radius=32, fill=INK)
    d.rounded_rectangle((270, 440, 660, 505), radius=32, fill=INK)
    d.rounded_rectangle((270, 550, 590, 615), radius=32, fill=GOLD)
    return img


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "assets"
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(out / "icon.png")
    big.resize((256, 256), Image.LANCZOS).save(
        out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    print("wrote", out / "icon.png", out / "icon.ico")


if __name__ == "__main__":
    main()
