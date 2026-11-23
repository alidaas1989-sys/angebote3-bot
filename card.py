"""Build the 1280x720 deal image: product on white, red price panel on the right."""
from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, PANEL_X = 1280, 720, 768
RED, WHITE, PINK = (196, 40, 40), (255, 255, 255), (245, 200, 200)
# panel themes rotate per deal: navy, red, matte yellow -> (background, main text, secondary text)
THEMES = [
    ((22, 40, 90), WHITE, (190, 205, 235)),
    (RED, WHITE, PINK),
    ((214, 178, 60), (40, 32, 10), (96, 78, 24)),
]
FONTS = Path(__file__).parent / "fonts"
MIN_SIDE = 100  # smaller pictures are Amazon placeholders, not product photos


class NoProductImage(ValueError):
    """The image link did not give a real product photo."""


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def centered(draw: ImageDraw.ImageDraw, y: int, text: str, fnt, fill) -> tuple[int, int, int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    x = PANEL_X + (W - PANEL_X - (box[2] - box[0])) // 2 - box[0]
    draw.text((x, y), text, font=fnt, fill=fill)
    return draw.textbbox((x, y), text, font=fnt)


def build_card(product: Image.Image, price_now: str, price_before: str | None, blur: bool = False, theme: int = 0) -> bytes:
    bg, TXT, SUB = THEMES[theme % len(THEMES)]
    now = Decimal(price_now)
    card = Image.new("RGB", (W, H), (255, 255, 255))
    product = product.convert("RGBA")
    product.thumbnail((PANEL_X - 60, H - 80))
    if blur:  # underwear shown on a model: hide the model, keep only a soft outline
        product = product.filter(ImageFilter.GaussianBlur(max(product.size) // 18))
    card.paste(product, ((PANEL_X - product.width) // 2, (H - product.height) // 2), product)
    draw = ImageDraw.Draw(card)
    draw.rectangle([PANEL_X, 0, W, H], fill=bg)
    before = Decimal(price_before) if price_before else None
    if before is None or (1 - now / before) < Decimal("0.25"):
        # discount under 25% (or none): the image carries no prices, only the channel branding
        centered(draw, 285, "Tägliche Angebote", font(40), TXT)
        centered(draw, 380, "t.me/Angebote3", font(34, bold=False), SUB)
        out = io.BytesIO()
        card.save(out, "JPEG", quality=92)
        return out.getvalue()
    if price_before:
        centered(draw, 105, f"-{round((1 - now / before) * 100)}%", font(118), TXT)
        centered(draw, 285, f"{now:.2f} €", font(76), TXT)
        box = centered(draw, 405, f"{before:.2f} €", font(46, bold=False), SUB)
        mid = (box[1] + box[3]) // 2
        draw.line([box[0] - 6, mid, box[2] + 6, mid], fill=SUB, width=4)
    else:
        centered(draw, 250, f"{now:.2f} €", font(96), TXT)
    centered(draw, 568, "Tägliche Angebote", font(38), TXT)
    centered(draw, 628, "t.me/Angebote3", font(28, bold=False), SUB)
    out = io.BytesIO()
    card.save(out, "JPEG", quality=92)
    return out.getvalue()


def card_from_url(image_url: str, price_now: str, price_before: str | None, blur: bool = False, theme: int = 0) -> bytes:
    response = requests.get(image_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    product = Image.open(io.BytesIO(response.content))
    if min(product.size) < MIN_SIDE:
        # Amazon answers unknown /images/P/ links with a 1x1 placeholder: the card would show no product
        raise NoProductImage(f"صورة فارغة {product.size[0]}x{product.size[1]}")
    return build_card(product, price_now, price_before, blur, theme)
