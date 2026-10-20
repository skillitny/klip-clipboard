from PIL import Image, ImageDraw, ImageFont
import os

W, H = 700, 620   # plus haut pour que tout soit visible (la status bar Finder mange ~30-50px)

BG       = (24, 24, 28, 255)
PANEL    = (32, 32, 38, 255)
TEXT     = (235, 235, 240, 255)
TEXT_DIM = (160, 160, 170, 255)
ACCENT   = (245, 158, 11, 255)
SEP      = (60, 60, 70, 255)

img = Image.new("RGBA", (W, H), BG)
d = ImageDraw.Draw(img)


def font(size):
    for p in ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/HelveticaNeue.ttc",
              "/Library/Fonts/Arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


f_title    = font(34)
f_sub      = font(14)
f_step_lbl = font(14)
f_step     = font(13)
f_warn     = font(14)
f_footer   = font(11)

# Titre et slogan
d.text((W//2, 42), "Klip", fill=TEXT, font=f_title, anchor="mm")
d.text((W//2, 70), "Glissez l'icone Klip vers le dossier Applications",
       fill=TEXT_DIM, font=f_sub, anchor="mm")

# Fleche entre les icones (y=240, alignee avec icon_locations)
arrow_y = 250
d.line([(265, arrow_y), (435, arrow_y)], fill=ACCENT, width=3)
d.polygon([(435, arrow_y - 9), (455, arrow_y), (435, arrow_y + 9)], fill=ACCENT)

# Panel instructions (remonte plus haut + grandi)
panel_x0, panel_y0 = 30, 380
panel_x1, panel_y1 = W - 30, 585
d.rounded_rectangle(
    [panel_x0, panel_y0, panel_x1, panel_y1],
    radius=14, fill=PANEL, outline=SEP, width=1,
)

# Header panel
d.ellipse([panel_x0 + 18, panel_y0 + 17, panel_x0 + 40, panel_y0 + 39], fill=ACCENT)
d.text((panel_x0 + 29, panel_y0 + 28), "!", fill=(24, 24, 28, 255),
       font=f_warn, anchor="mm")
d.text((panel_x0 + 52, panel_y0 + 28),
       "Au PREMIER lancement seulement",
       fill=TEXT, font=f_warn, anchor="lm")

steps = [
    ("1.", "Double-clic sur Klip dans Applications -> popup d'avertissement -> cliquez OK"),
    ("2.", "Reglages Systeme -> Confidentialite et securite -> bas de page : \"Klip a ete bloque\" -> Ouvrir quand meme"),
    ("3.", "Re-double-clic sur Klip -> Ouvrir dans la popup. C'est fait, l'app est autorisee pour de bon."),
]

y = panel_y0 + 64
for num, txt in steps:
    d.text((panel_x0 + 24, y), num, fill=ACCENT, font=f_step_lbl, anchor="lt")
    words = txt.split(" ")
    line = ""
    yy = y
    max_w = panel_x1 - (panel_x0 + 52) - 14
    for word in words:
        trial = (line + " " + word).strip()
        bbox = d.textbbox((0, 0), trial, font=f_step)
        if (bbox[2] - bbox[0]) > max_w and line:
            d.text((panel_x0 + 52, yy), line, fill=TEXT, font=f_step, anchor="lt")
            yy += 18
            line = word
        else:
            line = trial
    if line:
        d.text((panel_x0 + 52, yy), line, fill=TEXT, font=f_step, anchor="lt")
    y = yy + 26

# Footer
d.text((W//2, H - 14),
       "Klip est une app non signee Apple. Cette autorisation n'est demandee qu'une seule fois.",
       fill=TEXT_DIM, font=f_footer, anchor="mm")

img.save("dmg_background.png")
img.resize((W * 2, H * 2), Image.LANCZOS).save("dmg_background@2x.png")
print(f"OK ({W}x{H})")
