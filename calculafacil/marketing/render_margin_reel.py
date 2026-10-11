"""Create one original 12-second 9:16 MP4 educational Reel for CalculaFácil.

Uses Pillow and ffmpeg only; no paid service, soundtrack, licensed media or AI claims.
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WIDTH,HEIGHT=720,1280
FONT="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
WHITE=(242,251,250)
MUTED=(177,204,215)
AQUA=(100,237,211)
GREEN=(192,252,139)
ORANGE=(255,194,126)

def f(size,bold=False):
    return ImageFont.truetype(BOLD if bold else FONT,size)

def centered(draw,text,y,size,bold=True,color=WHITE,max_width=620):
    font=f(size,bold)
    while draw.textbbox((0,0),text,font=font)[2]>max_width and size>15:
        size-=1
        font=f(size,bold)
    w=draw.textbbox((0,0),text,font=font)[2]
    draw.text(((WIDTH-w)//2,y),text,font=font,fill=color)
    return size

def slide(idx):
    image=Image.new("RGB",(WIDTH,HEIGHT))
    d=ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t=y/HEIGHT
        d.line((0,y,WIDTH,y),fill=(int(7+5*t),int(13+14*t),int(29+20*t)))
    for x in range(50,WIDTH,54):
        d.line((x,50,x,1200),fill=(17,42,54),width=1)
    d.rounded_rectangle((38,40,682,1237),radius=38,fill=(12,29,42),outline=(53,99,106),width=3)
    d.rounded_rectangle((62,67,658,152),radius=22,fill=(20,64,66))
    centered(d,"CALCULAFÁCIL  |  LUMEN",90,29,color=AQUA)
    d.rounded_rectangle((70,189,650,1040),radius=28,fill=(15,38,51),outline=(36,88,91),width=2)
    if idx==0:
        centered(d,"¿VENDÉS BIEN?",245,56,color=WHITE)
        centered(d,"COMPRÁS A",365,37,color=MUTED)
        centered(d,"$10.000",422,81,color=AQUA)
        centered(d,"VENDÉS A",584,37,color=MUTED)
        centered(d,"$13.000",645,83,color=WHITE)
        centered(d,"¿GANASTE 30%?",828,42,color=ORANGE)
    elif idx==1:
        centered(d,"30% ES RECARGO",299,52,color=ORANGE)
        centered(d,"NO ES MARGEN",415,60,color=WHITE)
        centered(d,"Recargo: ganancia / costo",567,29,color=MUTED)
        centered(d,"Margen: ganancia / venta",640,29,color=AQUA)
        centered(d,"SON DISTINTOS",797,46,color=WHITE)
    elif idx==2:
        centered(d,"TU MARGEN REAL",259,50,color=WHITE)
        centered(d,"EN ESTE EJEMPLO",330,29,color=MUTED)
        centered(d,"23,08%",476,102,color=AQUA)
        centered(d,"$3.000 ÷ $13.000",674,43,color=WHITE)
        centered(d,"Antes de comisiones",847,27,color=MUTED)
        centered(d,"e impuestos.",884,27,color=MUTED)
    else:
        centered(d,"CALCULÁ GRATIS",261,54,color=AQUA)
        centered(d,"TUS PRECIOS",335,53,color=WHITE)
        centered(d,"Kit Excel PRO",512,57,color=WHITE)
        centered(d,"AR$ 9.900",596,71,color=GREEN)
        centered(d,"7 hojas editables",702,34,color=MUTED)
        centered(d,"Link de compra en el perfil",867,28,color=WHITE)
    for i in range(4):
        x=75+i*149
        d.rounded_rectangle((x,1097,x+128,1109),radius=6,fill=AQUA if i==idx else (55,86,93))
    centered(d,"calculafacil.lumen-b2b.workers.dev",1151,22,color=MUTED)
    return image

def run(dest):
    dest=Path(dest)
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reel-pricing-") as temp:
        frames=[]
        for i in range(4):
            name=Path(temp)/f"frame{i}.png"
            slide(i).save(name)
            frames.append(name)
        cmd=["ffmpeg","-hide_banner","-loglevel","error","-y"]
        for p in frames:
            cmd.extend(["-loop","1","-framerate","24","-t","3.2","-i",str(p)])
        cmd.extend(["-filter_complex","[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0,format=yuv420p[out]",
                    "-map","[out]","-an","-c:v","libx264","-profile:v","high","-preset","veryfast",
                    "-crf","25","-r","24","-movflags","+faststart",str(dest)])
        subprocess.run(cmd,check=True,timeout=180)
    details=subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
        "-show_entries","stream=codec_name,width,height:format=duration",
        "-of","json",str(dest)],text=True,capture_output=True,check=True,timeout=15)
    info=json.loads(details.stdout)
    stream=info["streams"][0]
    duration=float(info["format"]["duration"])
    assert stream["codec_name"]=="h264" and (stream["width"],stream["height"])==(WIDTH,HEIGHT)
    assert 12<=duration<=13 and 25000<dest.stat().st_size<10000000
    print("EDUCATIONAL_REEL_MP4_READY_720x1280_DURATION_12_8S")
    print("EDUCATIONAL_REEL_BYTES="+str(dest.stat().st_size))
    print("EDUCATIONAL_REEL_NO_PAID_MEDIA")

if __name__=="__main__":
    run(sys.argv[1] if len(sys.argv)>1 else "calculafacil/dist/reels/precios-margen-2026.mp4")
