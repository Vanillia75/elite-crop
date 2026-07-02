# -*- coding: utf-8 -*-
"""
Elite Crop — serveur web (FastAPI, hébergé sur Railway).

Sert la page web (static/index.html) et traite les vidéos :
POST /api/process  →  vidéo recadrée (le watermark en bas à droite est coupé).
Les photos, elles, sont recadrées directement dans le navigateur.
"""

import os
import shutil
import subprocess
import tempfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ffmpeg : celui du système (Railway/Docker), sinon celui du dossier bin (PC local)
FFMPEG = shutil.which("ffmpeg") or os.path.join(BASE_DIR, "bin", "ffmpeg.exe")

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg", ".wmv"}

app = FastAPI(title="Elite Crop")


def run_ffmpeg(args):
    proc = subprocess.run([FFMPEG, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def even(n):
    return n if n % 2 == 0 else n - 1


def video_size(path):
    """Dimensions de la vidéo (rotation comprise) via sa première image."""
    frame = path + "_frame.png"
    for seek in (["-ss", "1"], []):
        code, _ = run_ffmpeg(["-y", *seek, "-i", path, "-frames:v", "1", frame])
        if code == 0 and os.path.exists(frame) and os.path.getsize(frame) > 0:
            from PIL import Image
            with Image.open(frame) as img:
                size = img.size
            os.remove(frame)
            return size
    raise HTTPException(422, "Vidéo illisible.")


@app.post("/api/process")
async def process(file: UploadFile = File(...),
                  bottom: float = Form(...),
                  right: float = Form(...)):
    ext = os.path.splitext(file.filename or "video.mp4")[1].lower()
    if ext not in VIDEO_EXTS:
        raise HTTPException(422, "Format vidéo non pris en charge : " + ext)
    bottom = max(0.0, min(60.0, bottom))
    right = max(0.0, min(60.0, right))

    workdir = tempfile.mkdtemp(prefix="elitecrop_")
    src = os.path.join(workdir, "in" + ext)
    with open(src, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    w, h = video_size(src)
    crop_w = even(max(16, w - round(w * right / 100.0)))
    crop_h = even(max(16, h - round(h * bottom / 100.0)))

    out_ext = ext if ext in (".mp4", ".mov", ".m4v", ".mkv") else ".mp4"
    dest = os.path.join(workdir, "out" + out_ext)
    vf = "crop={}:{}:0:0".format(crop_w, crop_h)

    last_out = ""
    for audio in (["-c:a", "copy"], ["-c:a", "aac", "-b:a", "192k"]):
        code, out = run_ffmpeg(["-y", "-i", src, "-vf", vf,
                                "-c:v", "libx264", "-preset", "superfast",
                                "-crf", "21", *audio,
                                "-movflags", "+faststart", dest])
        last_out = out
        if code == 0:
            break
    else:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(500, "Échec du traitement vidéo : " + last_out[-500:])

    base = os.path.splitext(os.path.basename(file.filename or "video"))[0]
    return FileResponse(
        dest,
        filename=base + out_ext,
        media_type="application/octet-stream",
        background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
    )


@app.get("/api/health")
def health():
    return {"ok": True, "ffmpeg": os.path.basename(FFMPEG)}


# La page web (déclaré en dernier pour ne pas masquer /api/*)
app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "static"), html=True),
          name="static")
