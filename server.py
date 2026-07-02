# -*- coding: utf-8 -*-
"""
Elite Crop — serveur web (FastAPI, hébergé sur Railway).

Sert la page web (static/index.html) et traite les vidéos avec suivi
de progression :
  POST /api/process            → lance le traitement, renvoie {"job": id}
  GET  /api/progress/{job_id}  → {"status", "progress"} (0 à 100)
  GET  /api/result/{job_id}    → la vidéo recadrée
Les photos, elles, sont recadrées directement dans le navigateur.
"""

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ffmpeg : celui du système (Railway/Docker), sinon celui du dossier bin (PC local)
FFMPEG = shutil.which("ffmpeg") or os.path.join(BASE_DIR, "bin", "ffmpeg.exe")

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg", ".wmv"}

app = FastAPI(title="Elite Crop")

# Travaux en cours : id -> {status, progress, dest, workdir, filename, error, ts}
JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_MAX_AGE = 3600  # secondes


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


def video_duration(path):
    """Durée en secondes (lue dans la sortie de ffmpeg -i)."""
    _, out = run_ffmpeg(["-i", path])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def purge_old_jobs():
    """Supprime les travaux abandonnés (résultat jamais téléchargé)."""
    now = time.time()
    with JOBS_LOCK:
        stale = [jid for jid, j in JOBS.items() if now - j["ts"] > JOB_MAX_AGE]
        for jid in stale:
            shutil.rmtree(JOBS[jid]["workdir"], ignore_errors=True)
            del JOBS[jid]


def encode_worker(job_id, src, dest, vf, duration):
    """Encode la vidéo en mettant à jour la progression du travail."""
    job = JOBS[job_id]
    last_lines = []
    for audio in (["-c:a", "copy"], ["-c:a", "aac", "-b:a", "192k"]):
        job["progress"] = 0.0
        cmd = [FFMPEG, "-y", "-i", src, "-vf", vf,
               "-c:v", "libx264", "-preset", "superfast", "-crf", "21",
               *audio, "-movflags", "+faststart",
               "-progress", "pipe:1", "-nostats", dest]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        for line in proc.stdout:
            line = line.strip()
            last_lines.append(line)
            if len(last_lines) > 40:
                last_lines.pop(0)
            if duration > 0 and line.startswith("out_time_ms="):
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000.0  # microsecondes
                    job["progress"] = max(job["progress"],
                                          min(99.0, done / duration * 100.0))
                except ValueError:
                    pass
        proc.wait()
        if proc.returncode == 0:
            job["progress"] = 100.0
            job["status"] = "done"
            return
    job["status"] = "error"
    job["error"] = "Échec du traitement vidéo : " + " | ".join(last_lines[-5:])[-400:]
    shutil.rmtree(job["workdir"], ignore_errors=True)


@app.post("/api/process")
async def process(file: UploadFile = File(...),
                  bottom: float = Form(...),
                  right: float = Form(...)):
    purge_old_jobs()

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

    try:
        w, h = video_size(src)
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    crop_w = even(max(16, w - round(w * right / 100.0)))
    crop_h = even(max(16, h - round(h * bottom / 100.0)))
    duration = video_duration(src)

    out_ext = ext if ext in (".mp4", ".mov", ".m4v", ".mkv") else ".mp4"
    dest = os.path.join(workdir, "out" + out_ext)
    base = os.path.splitext(os.path.basename(file.filename or "video"))[0]

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "encours", "progress": 0.0, "error": "",
            "dest": dest, "workdir": workdir,
            "filename": base + out_ext, "ts": time.time(),
        }
    vf = "crop={}:{}:0:0".format(crop_w, crop_h)
    threading.Thread(target=encode_worker,
                     args=(job_id, src, dest, vf, duration), daemon=True).start()
    return {"job": job_id}


@app.get("/api/progress/{job_id}")
def progress(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Travail inconnu (ou expiré).")
    return {"status": job["status"], "progress": round(job["progress"], 1),
            "error": job["error"]}


@app.get("/api/result/{job_id}")
def result(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Travail inconnu (ou expiré).")
    if job["status"] != "done":
        raise HTTPException(409, "Le traitement n'est pas terminé.")

    def cleanup():
        shutil.rmtree(job["workdir"], ignore_errors=True)
        with JOBS_LOCK:
            JOBS.pop(job_id, None)

    return FileResponse(job["dest"], filename=job["filename"],
                        media_type="application/octet-stream",
                        background=BackgroundTask(cleanup))


@app.get("/api/health")
def health():
    return {"ok": True, "ffmpeg": os.path.basename(FFMPEG)}


# La page web (déclaré en dernier pour ne pas masquer /api/*)
app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "static"), html=True),
          name="static")
