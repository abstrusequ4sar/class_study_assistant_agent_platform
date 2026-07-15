"""将 PowerPoint 导出的逐页 PNG 组成联系表，用于快速检查排版。"""
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
PREVIEW = ROOT / "preview"
files = sorted(PREVIEW.glob("*.PNG"), key=lambda path: int(re.search(r"(\d+)", path.stem).group(1)))
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)

for sheet_index, start in enumerate(range(0, len(files), 4), 1):
    group = files[start : start + 4]
    sheet = Image.new("RGB", (1600, 960), "#d9dde3")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(group):
        image = Image.open(path).convert("RGB")
        image.thumbnail((760, 427))
        col = index % 2
        row = index // 2
        x = 20 + col * 790
        y = 34 + row * 450
        sheet.paste(image, (x, y))
        draw.rectangle((x, y, x + image.width, y + image.height), outline="#7f8c8d", width=2)
        slide_number = start + index + 1
        draw.rectangle((x, y, x + 54, y + 30), fill="#1f4e79")
        draw.text((x + 9, y + 3), str(slide_number), fill="white", font=font)
    sheet.save(ROOT / f"contact_sheet_{sheet_index}.png")

print(f"slides={len(files)} sheets={(len(files) + 3) // 4}")
