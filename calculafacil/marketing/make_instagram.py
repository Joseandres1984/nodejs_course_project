"""Create original CalculaFácil PRO Instagram asset from verified product facts.

Generated locally at build time from Pillow; no paid design API, real buyer data,
API secrets or new tracking pixels. Output: 1080x1350 RGB JPG for Instagram.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
import math
import sys

W, H = 1080, 1350
out = Path(sys.argv[1] if len(sys.argv) > 1 else "calculafacil/dist/instagram-pro-launch.jpg")
out.parent.mkdir(parents=True, exist_ok=True)

img = Image.new("RGB", (W, H))
pix = img.load()
for y in range(H):
    for x in range(W):
        t = y / H
        vignette = max(0, 1-math.hypot((x-W*.85)/(W*1.12), (y-H*.12)/(H*.9)))
        pix[x,y] = (int(6+6*t+2*vignette), int(12+13*t+12*vignette), int(27+21*t+15*vignette))

overlay=Image.new("RGBA",(W,H),(0,0,0,0))
d=ImageDraw.Draw(overlay)
for x in range(32,W,64):
    d.line([(x,0),(x,H)],fill=(83,169,181,13),width=1)
for y in range(24,H,64):
    d.line([(0,y),(W,y)],fill=(83,169,181,12),width=1)

glow=Image.new("RGBA",(W,H),(0,0,0,0))
g=ImageDraw.Draw(glow)
g.ellipse((530,-245,1350,595),fill=(43,205,183,44))
g.ellipse((-330,670,470,1550),fill=(49,132,230,23))
img=Image.alpha_composite(img.convert("RGBA"),glow.filter(ImageFilter.GaussianBlur(115)))
img=Image.alpha_composite(img,overlay)
d=ImageDraw.Draw(img)

FONT="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
def font(size,bold=False):
    return ImageFont.truetype(BOLD if bold else FONT,size)

AQUA=(83,238,208,255)
WHITE=(240,252,255,255)
GRAY=(159,190,204,255)

d.rounded_rectangle((70,72,128,130),radius=17,fill=(73,231,203,255))
d.line([(84,110),(104,86),(98,104),(117,104),(98,121)],
       fill=(4,42,52,255),width=6,joint="curve")
d.text((148,77),"calcula",font=font(39,True),fill=WHITE)
d.text((325,77),"fácil",font=font(39,True),fill=AQUA)
d.rounded_rectangle((459,78,557,125),radius=21,outline=AQUA,width=2,fill=(12,57,68,255))
d.text((480,86),"PRO",font=font(26,True),fill=AQUA)
d.text((742,90),"KIT EXCEL",font=font(23,True),fill=GRAY)
d.line((68,164,1012,164),fill=(58,109,130,115),width=2)

d.text((73,208),"PARA EMPRENDEDORES",font=font(27,True),fill=AQUA)
d.text((69,259),"¿TU NEGOCIO",font=font(78,True),fill=WHITE)
d.text((69,364),"ES RENTABLE?",font=font(83,True),fill=WHITE)
d.text((73,485),"Dejá de adivinar tus números.",font=font(30),fill=GRAY)
d.text((73,529),"Tomá decisiones con datos.",font=font(30),fill=GRAY)

d.rounded_rectangle((61,605,1017,1057),radius=29,fill=(16,34,55,252),
                    outline=(61,128,143,230),width=3)
d.text((98,643),"Todo en un Excel editable",font=font(37,True),fill=WHITE)
d.line((96,710,976,710),fill=(44,94,111,255),width=2)
rows=[
    ("01","PRECIOS Y MÁRGENES","Conocé cuánto ganás de verdad"),
    ("02","PUNTO DE EQUILIBRIO","Calculá cuánto necesitás vender"),
    ("03","PROYECCIONES Y PROMOS","Simulá escenarios antes de decidir"),
]
for i,(num,title,desc) in enumerate(rows):
    y=746+i*95
    d.rounded_rectangle((96,y+2,160,y+61),radius=12,fill=(18,63,71,255),
                        outline=(58,169,159,180),width=2)
    d.text((105,y+14),num,font=font(25,True),fill=AQUA)
    d.text((184,y),title,font=font(28,True),fill=WHITE)
    d.text((184,y+37),desc,font=font(21),fill=GRAY)

d.rounded_rectangle((61,1092,1017,1216),radius=21,fill=(61,226,194,255))
d.text((98,1117),"AR$ 9.900",font=font(57,True),fill=(6,30,41,255))
d.line((545,1114,545,1194),fill=(9,85,86,100),width=2)
d.text((575,1123),"PAGO ÚNICO",font=font(27,True),fill=(5,50,57,255))
d.text((575,1164),"Sin suscripción",font=font(22),fill=(17,78,80,255))
footer="calculafacil.lumen-b2b.workers.dev/pro.html"
d.text((73,1254),"CONOCÉ EL KIT:",font=font(19,True),fill=AQUA)
size=25
while d.textbbox((0,0),footer,font=font(size,True))[2]>625:
    size-=1
d.text((315,1248),footer,font=font(size,True),fill=WHITE)

img.convert("RGB").save(out,format="JPEG",quality=92,optimize=True,subsampling=0)
assert out.stat().st_size>40000
print(f"INSTAGRAM_PRO_LAUNCH_JPEG_READY bytes={out.stat().st_size} size={W}x{H}")
