"""Generate the sole organic launch creative for LUMEN Instagram from product facts."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import sys

W,H=1080,1350
img=Image.new("RGB",(W,H),(7,12,26))
d=ImageDraw.Draw(img)
for y in range(H):
    t=y/(H-1)
    d.line((0,y,W,y),fill=(int(7+4*t),int(12+10*t),int(26+13*t)))
font_normal="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_bold="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
def font(size,bold=False):return ImageFont.truetype(font_bold if bold else font_normal,size)
aqua=(91,234,210);white=(245,248,253);muted=(172,194,206);gold=(220,249,146)
def txt(x,y,s,size=40,color=white,bold=False):d.text((x,y),s,font=font(size,bold),fill=color)
def line(x1,y1,x2,y2,color=(50,84,100),width=2):d.line((x1,y1,x2,y2),fill=color,width=width)
def box(coords,fill,outline=None,width=1,radius=26):d.rounded_rectangle(coords,radius=radius,fill=fill,outline=outline,width=width)
for x in range(90,W,65):line(x,40,x,H-40,(16,32,46))
for y in range(75,H,65):line(35,y,W-35,y,(16,32,46))
box((68,57,1012,1293),(12,29,43),(54,95,108),3,45)
box((98,87,982,191),(29,59,69),radius=22)
txt(131,110,"CALCULA",50,white,True)
txt(397,110,"FÁCIL",50,aqua,True)
box((746,114,930,169),(63,89,65),radius=16)
txt(774,122,"KIT PRO",29,gold,True)
txt(124,230,"¿VENDÉS PERO",68,white,True)
txt(124,318,"NO SABÉS",73,white,True)
txt(124,404,"CUÁNTO GANÁS?",66,aqua,True)
line(124,524,950,524,(65,120,126),3)
txt(128,559,"Tomá decisiones con tus números",34,muted)
txt(128,618,"en un Excel editable.",38,white,True)
box((122,715,958,913),(17,51,61),(68,135,144),2,28)
txt(153,751,"7 HOJAS",51,aqua,True)
txt(523,751,"PARA TU NEGOCIO",28,gold,True)
txt(153,819,"Precios · Márgenes · Punto de equilibrio",27,white)
txt(153,862,"Proyecciones · Cuotas · Promociones",27,white)
box((122,966,958,1089),(79,227,197),radius=24)
txt(155,982,"AR$ 9.900",70,(11,36,44),True)
txt(629,1002,"PAGO ÚNICO",28,(11,36,44),True)
txt(122,1128,"Comprá online · Recibí tu archivo privado",27,muted)
txt(122,1190,"calculafacil.lumen-b2b.workers.dev/pro.html",24,white)
txt(122,1245,"LUMEN B2B  /  SIN SUSCRIPCIÓN",20,gold,True)
out=Path(sys.argv[1] if len(sys.argv)>1 else "calculafacil/dist/instagram/calculafacil-pro-lanzamiento.jpg")
out.parent.mkdir(parents=True,exist_ok=True)
img.save(out,"JPEG",quality=92,subsampling=0,optimize=True)
assert out.stat().st_size>30000
assert Image.open(out).size==(1080,1350)
print("CALCULAFACIL_INSTAGRAM_CAMPAIGN_ASSET_GENERATED_1080x1350")
