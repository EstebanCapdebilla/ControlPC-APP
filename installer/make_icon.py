"""Genera icon.ico (mismo dibujo que web/icon.svg). Solo hace falta Pillow en el PC que compila."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

S = 4  # dibujar a 4x y reducir = bordes suaves
W = 512 * S
img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
blue = (79, 157, 255, 255)
d.rounded_rectangle((0, 0, W - 1, W - 1), radius=112 * S, fill=(15, 17, 21, 255))
d.rounded_rectangle((196 * S, 140 * S, 316 * S, 310 * S), radius=16 * S, fill=(31, 52, 80, 255))  # azul al 25 % sobre el fondo
h = 13 * S  # mitad del grosor del borde (26)
d.rounded_rectangle((166 * S - h, 96 * S - h, 346 * S + h, 416 * S + h), radius=34 * S + h, outline=blue, width=26 * S)
d.ellipse(((256 - 18) * S, (362 - 18) * S, (256 + 18) * S, (362 + 18) * S), fill=blue)
pts = [(236, 200), (282, 226), (262, 232), (274, 256), (262, 262), (250, 238), (236, 252)]
d.polygon([(x * S, y * S) for x, y in pts], fill=(232, 234, 240, 255))
img = img.resize((256, 256), Image.LANCZOS)

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "icon.ico")
img.save(out, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Ícono:", out)
