"""Genere une nouvelle icone Klip : ciseaux blancs sur fond orange degrade.

Style macOS Sequoia : rounded square avec coins arrondis ~22.5% du cote,
gradient diagonal, highlight subtil en haut, ciseaux blancs geometriques
avec ombre portee.

Produit /tmp/klip_icon_1024.png puis un iconset complet via iconutil.
"""
import math
import os
from PIL import Image, ImageDraw, ImageFilter

S = 1024
RADIUS = int(S * 0.225)  # macOS Big Sur+ rounded square

# Couleurs orange (palette Klip + variations)
COL_TOP    = (255, 174, 66)     # orange clair
COL_MID    = (245, 158, 11)     # orange Klip #f59e0b
COL_BOT    = (217, 119, 6)      # orange fonce #d97706
WHITE      = (255, 255, 255, 255)


def make_gradient(size, top, mid, bot):
    """Gradient vertical 3-stops top -> mid (50%) -> bot."""
    img = Image.new("RGB", (size, size), top)
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        if t < 0.5:
            tt = t / 0.5
            r = int(top[0] + (mid[0] - top[0]) * tt)
            g = int(top[1] + (mid[1] - top[1]) * tt)
            b = int(top[2] + (mid[2] - top[2]) * tt)
        else:
            tt = (t - 0.5) / 0.5
            r = int(mid[0] + (bot[0] - mid[0]) * tt)
            g = int(mid[1] + (bot[1] - mid[1]) * tt)
            b = int(mid[2] + (bot[2] - mid[2]) * tt)
        d.line([(0, y), (size, y)], fill=(r, g, b))
    return img


# 1. Gradient orange
bg = make_gradient(S, COL_TOP, COL_MID, COL_BOT).convert("RGBA")

# 2. Highlight subtil en haut (reflet doux)
hi = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d_hi = ImageDraw.Draw(hi)
for y in range(int(S * 0.45)):
    t = y / (S * 0.45)
    alpha = int(70 * (1 - t) ** 2)
    if alpha > 0:
        d_hi.line([(0, y), (S, y)], fill=(255, 255, 255, alpha))
bg = Image.alpha_composite(bg, hi)

# 3. Inner shadow en bas (profondeur subtile)
shd = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d_shd = ImageDraw.Draw(shd)
for y in range(int(S * 0.55), S):
    t = (y - S * 0.55) / (S * 0.45)
    alpha = int(35 * t ** 2)
    if alpha > 0:
        d_shd.line([(0, y), (S, y)], fill=(0, 0, 0, alpha))
bg = Image.alpha_composite(bg, shd)

# 4. Masque rounded square (coupe les coins)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle(
    (0, 0, S, S), radius=RADIUS, fill=255
)
bg.putalpha(mask)

# 5. Ciseaux geometrique blancs --------------------------------------------
# Centre du pivot (croisement des lames)
PIVOT = (S / 2, S * 0.46)
# Angle d'ouverture des lames (depuis vertical)
ANGLE = math.radians(20)

# Anneaux (handles) en bas, ecartes
ring_offset_y = S * 0.30
ring_offset_x = S * 0.13
ring_outer_r = S * 0.10
ring_stroke = max(2, int(S * 0.028))

# Anneau gauche
lr_cx = PIVOT[0] - ring_offset_x
lr_cy = PIVOT[1] + ring_offset_y
# Anneau droit
rr_cx = PIVOT[0] + ring_offset_x
rr_cy = PIVOT[1] + ring_offset_y

# Lames : du anneau vers le tip de l'autre cote (en haut)
blade_length = S * 0.40
blade_width = max(2, int(S * 0.060))
# Tip lame gauche (en haut a droite)
lt_x = PIVOT[0] + blade_length * math.sin(ANGLE)
lt_y = PIVOT[1] - blade_length * math.cos(ANGLE)
# Tip lame droite (en haut a gauche)
rt_x = PIVOT[0] - blade_length * math.sin(ANGLE)
rt_y = PIVOT[1] - blade_length * math.cos(ANGLE)

# Layer des ciseaux pour pouvoir lui appliquer une ombre
scissors = Image.new("RGBA", (S, S), (0, 0, 0, 0))
sd = ImageDraw.Draw(scissors)

# Lames : on les dessine comme polygones effilés pour avoir des pointes propres
def blade_polygon(start, tip, width):
    """Polygone trapezoidal : large au depart (start), pointu au tip."""
    sx, sy = start
    tx, ty = tip
    # Vecteur unitaire de start vers tip
    dx, dy = tx - sx, ty - sy
    L = math.hypot(dx, dy)
    if L == 0:
        return []
    ux, uy = dx / L, dy / L
    # Perpendiculaire
    px, py = -uy, ux
    # Larger au depart (handle), 0 au tip
    half_w_start = width * 0.55
    half_w_tip = max(1, width * 0.08)
    return [
        (sx + px * half_w_start, sy + py * half_w_start),
        (sx - px * half_w_start, sy - py * half_w_start),
        (tx - px * half_w_tip, ty - py * half_w_tip),
        (tx + px * half_w_tip, ty + py * half_w_tip),
    ]


# Lame gauche : (lr_cx, lr_cy) -> tip a droite-haut (lt_x, lt_y) en passant par pivot
sd.polygon(blade_polygon((lr_cx, lr_cy), (lt_x, lt_y), blade_width), fill=WHITE)
# Lame droite
sd.polygon(blade_polygon((rr_cx, rr_cy), (rt_x, rt_y), blade_width), fill=WHITE)

# Anneaux : on perce au milieu pour donner l'effet "handle"
# Anneau exterieur blanc
sd.ellipse([lr_cx - ring_outer_r, lr_cy - ring_outer_r,
            lr_cx + ring_outer_r, lr_cy + ring_outer_r], fill=WHITE)
sd.ellipse([rr_cx - ring_outer_r, rr_cy - ring_outer_r,
            rr_cx + ring_outer_r, rr_cy + ring_outer_r], fill=WHITE)
# Trou interieur (transparent)
ring_inner_r = ring_outer_r - ring_stroke * 1.5
sd.ellipse([lr_cx - ring_inner_r, lr_cy - ring_inner_r,
            lr_cx + ring_inner_r, lr_cy + ring_inner_r],
           fill=(0, 0, 0, 0))
sd.ellipse([rr_cx - ring_inner_r, rr_cy - ring_inner_r,
            rr_cx + ring_inner_r, rr_cy + ring_inner_r],
           fill=(0, 0, 0, 0))

# Point central de croisement (rivet) : petit cercle blanc plein pour solidifier
rivet_r = max(2, int(S * 0.018))
sd.ellipse([PIVOT[0] - rivet_r, PIVOT[1] - rivet_r,
            PIVOT[0] + rivet_r, PIVOT[1] + rivet_r], fill=WHITE)

# 6. Ombre portee des ciseaux (offset vers le bas, blur)
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
shadow_src = scissors.split()[-1]  # canal alpha
shadow_color = Image.new("RGBA", (S, S), (0, 0, 0, 80))
shadow_color.putalpha(shadow_src)
shadow_color = shadow_color.filter(ImageFilter.GaussianBlur(radius=14))
shadow_offset = Image.new("RGBA", (S, S), (0, 0, 0, 0))
shadow_offset.paste(shadow_color, (0, int(S * 0.015)), shadow_color)

# 7. Composition finale
out = bg.copy()
out = Image.alpha_composite(out, shadow_offset)
out = Image.alpha_composite(out, scissors)

# Re-applique le masque arrondi pour proprete (au cas ou les ciseaux depasseraient)
final = Image.new("RGBA", (S, S), (0, 0, 0, 0))
final.paste(out, (0, 0), mask)

out_path = "/tmp/klip_icon_1024.png"
final.save(out_path)
print(f"OK -> {out_path}")
