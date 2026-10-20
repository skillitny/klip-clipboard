# dmgbuild settings for Klip
import os.path

application = defines.get("app", "dist/Klip.app")
appname = os.path.basename(application)

format = "UDZO"
compression_level = 9
volume_name = "Klip"

# Icone du FICHIER .dmg lui-meme (visible dans Finder)
icon = "icon.icns"
# Icone du VOLUME une fois monte (Bureau / barre laterale)
badge_icon = "icon.icns"

window_rect = ((200, 120), (700, 640))
background = "dmg_background.png"

icon_size = 96
text_size = 12

files = [application]
symlinks = {"Applications": "/Applications"}

icon_locations = {
    appname:        (175, 240),
    "Applications": (525, 240),
}

default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_pathbar = False
show_sidebar = False
sidebar_width = 0

hide_extension = [appname]
