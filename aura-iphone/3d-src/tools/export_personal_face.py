"""Offline, one-time AURA face geometry extraction; never runs on the phone.

Usage (after installing mediapipe, pillow, numpy and its optional graphics libs):
  python export_personal_face.py portrait.webp face_landmarker.task \
      face-mesh-triangulation.js ../personal-face-data.mjs

The triangulation input is from the MIT-licensed face-to-blendshape-3d project
by Artur Wyroslak (2026), ultimately based on Google's MediaPipe topology.
The result records ONLY numeric landmarks + connectivity, not third-party code.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import mediapipe as mp
import numpy as np
from PIL import Image
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


def export(image_path: Path, model_path: Path, topology_path: Path, output_path: Path) -> None:
    with vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
        )
    ) as landmarker:
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        result = landmarker.detect(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(image))
        )
    if len(result.face_landmarks) != 1:
        raise ValueError("La foto de AURA debe contener exactamente un rostro")

    landmarks = result.face_landmarks[0]
    if len(landmarks) != 478:
        raise ValueError(f"Esperábamos 478 puntos; hay {len(landmarks)}")

    text = topology_path.read_text(encoding="utf-8")
    match = re.search(r"export const FACEMESH_TESSELATION\s*=\s*\[([^]]+)\]", text)
    if match is None:
        raise ValueError("No se encuentra la triangulación de MediaPipe")
    triangle_indices = [int(n) for n in re.findall(r"\d+", match.group(1))]
    if len(triangle_indices) % 3 or max(triangle_indices) > 467:
        raise ValueError("Triangulación 468 incompatible")

    data = {
        "image": [width, height],
        # The irises (indices 468..477) are omitted from the face surface.
        "landmarks": [
            [round(p.x, 6), round(p.y, 6), round(p.z, 6)]
            for p in landmarks[:468]
        ],
        "triangles": triangle_indices,
    }
    comment = (
        "// AURA: 468 face landmarks measured from our original portrait.\n"
        "// MediaPipe Face Landmarker (Google); triangulation derived from\n"
        "// arturwyroslak/face-to-blendshape-3d (MIT; © Artur Wyroslak 2026).\n"
        "// Generated offline. No image upload, cloud runtime or model download.\n"
    )
    output_path.write_text(
        comment + "export const PERSONAL_FACE_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_path}: {len(data['landmarks'])} landmarks, {len(triangle_indices)//3} triangles")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("Uso: export_personal_face.py foto modelo.task topologia.js salida.mjs")
    export(*(Path(path).resolve() for path in sys.argv[1:]))
