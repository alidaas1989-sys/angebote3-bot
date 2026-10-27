"""Build the 1280x720 deal image: product on white, red price panel on the right."""
from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

W, H, PANEL_X = 1280, 720, 768
RED, WHITE, PINK = (196, 40, 40), (255, 255, 255), (245, 200, 200)
FONTS = Path(__file__).parent / "fonts"


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def centered(draw: ImageDraw.ImageDraw, y: int, text: str, fnt, fill) -> tuple[int, int, int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    x = PANEL_X + (W - PANEL_X - (box[2] - box[0])) // 2 - box[0]
    draw.text((x, y), text, font=fnt, fill=fill)
    return draw.textbbox((x, y), text, font=fnt)


def build_card(product: Image.Image, price_now: str, price_before: str) -> bytes:
    now, before = Decimal(price_now), Decimal(price_before)
    percent = round((1 - now / before) * 100)
    card = Image.new("RGB", (W, H), WHITE)
    product = product.convert("RGBA")
    product.thumbnail((PANEL_X - 60, H - 80))
    card.paste(product, ((PANEL_X - product.width) // 2, (H - product.height) // 2), product)
    draw = ImageDraw.Draw(card)
    draw.rectangle([PANEL_X, 0, W, H], fill=RED)
    centered(draw, 105, f"-{percent}%", font(118), WHITE)
    centered(draw, 285, f"{now:.2f} €", font(76), WHITE)
    box = centered(draw, 405, f"{before:.2f} €", font(46, bold=False), PINK)
    mid = (box[1] + box[3]) // 2
    draw.line([box[0] - 6, mid, box[2] + 6, mid], fill=PINK, width=4)
    centered(draw, 568, "Tägliche Angebote", font(38), WHITE)
    centered(draw, 628, "t.me/Angebote3", font(28, bold=False), PINK)
    out = io.BytesIO()
    card.save(out, "JPEG", quality=92)
    return out.getvalue()


def card_from_url(image_url: str, price_now: str, price_before: str) -> bytes:
    response = requests.get(image_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return build_card(Image.open(io.BytesIO(response.content)), price_now, price_before)
