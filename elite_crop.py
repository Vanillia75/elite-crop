# -*- coding: utf-8 -*-
"""
Elite Crop — supprime un watermark en bas à droite en recadrant
photos et vidéos en masse.

Utilisation : double-cliquer sur Elite-Crop.exe (ou : pythonw elite_crop.py)
"""

import os
import sys
import subprocess
import threading
import tempfile
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk, ImageOps

# Support HEIC (photos iPhone) si le module est présent — sinon on ignore.
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_OK = True
except ImportError:
    HEIC_OK = False

# ---------------------------------------------------------------- constantes

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FFMPEG = os.path.join(BASE_DIR, "bin", "ffmpeg.exe")

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
if HEIC_OK:
    PHOTO_EXTS |= {".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg", ".wmv"}

OUT_DIRNAME = "Sans-watermark"

# Charte H€CTOR
INK = "#0A2540"
ACCENT = "#378ADD"
GREEN = "#5DCAA5"
NIGHT = "#07192E"
RED = "#E5484D"

CANVAS_W, CANVAS_H = 640, 420

# Empêche l'ouverture de fenêtres console noires à chaque appel ffmpeg.
NOWINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def run_cmd(args):
    """Lance un programme externe sans fenêtre console, renvoie (code, sortie)."""
    proc = subprocess.run(
        args, capture_output=True, text=True,
        encoding="utf-8", errors="replace", creationflags=NOWINDOW,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def is_photo(path):
    return os.path.splitext(path)[1].lower() in PHOTO_EXTS


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def even(n):
    """Les encodeurs vidéo exigent des dimensions paires."""
    return n if n % 2 == 0 else n - 1


# ---------------------------------------------------------------- traitement


def video_first_frame(path):
    """Extrait la première image d'une vidéo (pour l'aperçu). Renvoie un PIL.Image."""
    tmp = os.path.join(tempfile.gettempdir(), "elitecrop_preview.jpg")
    for seek in (["-ss", "1"], []):
        code, _ = run_cmd([FFMPEG, "-y", *seek, "-i", path,
                           "-frames:v", "1", "-q:v", "2", tmp])
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            img = Image.open(tmp)
            img.load()
            return img
    raise RuntimeError("Impossible de lire la vidéo : " + os.path.basename(path))


def load_preview(path):
    """Renvoie un PIL.Image de l'aperçu, photo ou vidéo (orientation corrigée)."""
    if is_photo(path):
        img = Image.open(path)
        return ImageOps.exif_transpose(img)
    return video_first_frame(path)


def out_path_for(src):
    """Chemin de sortie : sous-dossier 'Sans-watermark' à côté du fichier."""
    folder = os.path.join(os.path.dirname(src), OUT_DIRNAME)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, os.path.basename(src))


def process_photo(src, pct_bottom, pct_right):
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    w, h = img.size
    new_w = max(16, w - round(w * pct_right / 100.0))
    new_h = max(16, h - round(h * pct_bottom / 100.0))
    cropped = img.crop((0, 0, new_w, new_h))

    dest = out_path_for(src)
    ext = os.path.splitext(src)[1].lower()
    save_kwargs = {}
    if ext in (".jpg", ".jpeg"):
        if cropped.mode not in ("RGB", "L"):
            cropped = cropped.convert("RGB")
        save_kwargs = {"quality": 95, "subsampling": 0}
    elif ext == ".webp":
        save_kwargs = {"quality": 95}
    elif ext in (".heic", ".heif"):
        # On ressort en JPG : lisible partout.
        dest = os.path.splitext(dest)[0] + ".jpg"
        cropped = cropped.convert("RGB")
        save_kwargs = {"quality": 95, "subsampling": 0}
    exif = img.info.get("exif")
    if exif and ext in (".jpg", ".jpeg"):
        save_kwargs["exif"] = exif
    cropped.save(dest, **save_kwargs)
    return dest


# Encodeurs vidéo, du plus rapide au plus lent : cartes graphiques NVIDIA,
# Intel puis AMD, et enfin le processeur (marche partout). Le premier qui
# fonctionne sur la machine est mémorisé et réutilisé pour la suite du lot.
ENCODER_CANDIDATES = [
    ("carte NVIDIA", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22"]),
    ("carte Intel", ["-c:v", "h264_qsv", "-preset", "veryfast",
                     "-global_quality", "22"]),
    ("carte AMD", ["-c:v", "h264_amf", "-quality", "speed"]),
    ("processeur", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]),
]


class VideoEncoder:
    """Choisit l'encodeur le plus rapide qui fonctionne sur cette machine."""

    def __init__(self):
        self.start = 0   # index du premier candidat encore plausible
        self.name = None

    def encode(self, src, dest, crop_w, crop_h):
        vf = "crop={}:{}:0:0".format(crop_w, crop_h)
        last_out = ""
        for i in range(self.start, len(ENCODER_CANDIDATES)):
            name, vargs = ENCODER_CANDIDATES[i]
            for audio in (["-c:a", "copy"], ["-c:a", "aac", "-b:a", "192k"]):
                code, out = run_cmd([
                    FFMPEG, "-y", "-i", src, "-vf", vf, *vargs, *audio,
                    "-movflags", "+faststart", dest,
                ])
                last_out = out
                if code == 0:
                    self.start = i
                    self.name = name
                    return
        raise RuntimeError("ffmpeg a échoué :\n" + last_out[-1500:])


ENCODER = VideoEncoder()


def process_video(src, pct_bottom, pct_right):
    frame = video_first_frame(src)
    w, h = frame.size
    crop_w = even(max(16, w - round(w * pct_right / 100.0)))
    crop_h = even(max(16, h - round(h * pct_bottom / 100.0)))

    dest = out_path_for(src)
    ext = os.path.splitext(src)[1].lower()
    if ext not in (".mp4", ".mov", ".m4v", ".mkv"):
        dest = os.path.splitext(dest)[0] + ".mp4"
    ENCODER.encode(src, dest, crop_w, crop_h)
    return dest


# ---------------------------------------------------------------- interface


class App:
    def __init__(self, root):
        self.root = root
        self.files = []
        self.preview_index = 0
        self.preview_img = None      # PIL image du fichier affiché
        self.preview_photo = None    # version Tkinter (référence obligatoire)
        self.processing = False

        root.title("Elite Crop — enlève le watermark en bas à droite")
        root.configure(bg=NIGHT)
        root.resizable(False, False)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=8)
        style.configure("Horizontal.TProgressbar",
                        troughcolor=INK, background=GREEN)

        # --- barre du haut : gestion des fichiers
        top = tk.Frame(root, bg=NIGHT)
        top.pack(fill="x", padx=14, pady=(12, 6))
        ttk.Button(top, text="➕ Ajouter des fichiers",
                   command=self.add_files).pack(side="left")
        ttk.Button(top, text="📁 Ajouter un dossier",
                   command=self.add_folder).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="🗑 Vider la liste",
                   command=self.clear_files).pack(side="left", padx=(8, 0))
        self.count_label = tk.Label(top, text="0 fichier", bg=NIGHT,
                                    fg=GREEN, font=("Segoe UI", 10, "bold"))
        self.count_label.pack(side="right")

        # --- aperçu
        self.canvas = tk.Canvas(root, width=CANVAS_W, height=CANVAS_H,
                                bg=INK, highlightthickness=0)
        self.canvas.pack(padx=14, pady=6)

        nav = tk.Frame(root, bg=NIGHT)
        nav.pack(fill="x", padx=14)
        ttk.Button(nav, text="◀ Fichier précédent", width=20,
                   command=lambda: self.step_preview(-1)).pack(side="left")
        self.nav_label = tk.Label(nav, text="", bg=NIGHT, fg="white",
                                  font=("Segoe UI", 9))
        self.nav_label.pack(side="left", expand=True)
        ttk.Button(nav, text="Fichier suivant ▶", width=20,
                   command=lambda: self.step_preview(1)).pack(side="right")

        # --- réglages
        sliders = tk.Frame(root, bg=NIGHT)
        sliders.pack(fill="x", padx=14, pady=(10, 0))
        self.pct_bottom = tk.DoubleVar(value=8.0)
        self.pct_right = tk.DoubleVar(value=0.0)
        self._make_slider(sliders, "Couper en bas", self.pct_bottom)
        self._make_slider(sliders, "Couper à droite", self.pct_right)

        # --- action + progression
        bottom = tk.Frame(root, bg=NIGHT)
        bottom.pack(fill="x", padx=14, pady=12)
        self.go_btn = ttk.Button(bottom, text="⚡ Tout traiter",
                                 style="Big.TButton", command=self.start)
        self.go_btn.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, maximum=100)
        self.progress.pack(fill="x", pady=(8, 0))
        self.status = tk.Label(bottom, text="Ajoute des fichiers pour commencer.",
                               bg=NIGHT, fg="white", font=("Segoe UI", 9),
                               anchor="w", justify="left")
        self.status.pack(fill="x", pady=(6, 0))

        self.draw_placeholder()

    # ------------------------------------------------------------- fichiers

    def add_files(self):
        exts = sorted(PHOTO_EXTS | VIDEO_EXTS)
        pattern = " ".join("*" + e for e in exts)
        paths = filedialog.askopenfilenames(
            title="Choisis tes photos et vidéos",
            filetypes=[("Photos et vidéos", pattern), ("Tous les fichiers", "*.*")])
        self._add(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Choisis un dossier")
        if not folder:
            return
        paths = [os.path.join(folder, f) for f in sorted(os.listdir(folder))]
        self._add(paths)

    def _add(self, paths):
        added = 0
        for p in paths:
            if os.path.isfile(p) and (is_photo(p) or is_video(p)) and p not in self.files:
                self.files.append(p)
                added += 1
        if added:
            self.preview_index = len(self.files) - added
            self.refresh_preview()
        self.update_count()

    def clear_files(self):
        self.files = []
        self.preview_index = 0
        self.update_count()
        self.draw_placeholder()
        self.nav_label.config(text="")

    def update_count(self):
        n = len(self.files)
        photos = sum(1 for f in self.files if is_photo(f))
        videos = n - photos
        self.count_label.config(
            text="{} fichier{} ({} photo{}, {} vidéo{})".format(
                n, "s" if n > 1 else "", photos, "s" if photos > 1 else "",
                videos, "s" if videos > 1 else ""))

    # -------------------------------------------------------------- aperçu

    def _make_slider(self, parent, label, var):
        row = tk.Frame(parent, bg=NIGHT)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, width=14, anchor="w", bg=NIGHT, fg="white",
                 font=("Segoe UI", 10)).pack(side="left")
        scale = tk.Scale(row, from_=0, to=40, resolution=0.5, orient="horizontal",
                         variable=var, showvalue=False, length=380,
                         bg=NIGHT, fg="white", troughcolor=INK,
                         highlightthickness=0, activebackground=ACCENT,
                         command=lambda _v: self.draw_overlay())
        scale.pack(side="left", padx=8)
        value = tk.Label(row, bg=NIGHT, fg=GREEN, width=14, anchor="w",
                         font=("Segoe UI", 10, "bold"))
        value.pack(side="left")
        var.trace_add("write", lambda *_: self._update_value_label(var, value))
        self._update_value_label(var, value)

    def _update_value_label(self, var, label):
        txt = "{:.1f} %".format(var.get())
        if self.preview_img is not None:
            w, h = self.preview_img.size
            if var is self.pct_bottom:
                txt += "  ({} px)".format(round(h * var.get() / 100.0))
            else:
                txt += "  ({} px)".format(round(w * var.get() / 100.0))
        label.config(text=txt)

    def draw_placeholder(self):
        self.canvas.delete("all")
        self.canvas.create_text(
            CANVAS_W // 2, CANVAS_H // 2, fill="#5a7a9a", font=("Segoe UI", 12),
            text="Aperçu\n\nAjoute des fichiers : la zone rouge montre\nce qui sera coupé (le watermark doit être dedans).",
            justify="center")

    def step_preview(self, delta):
        if not self.files:
            return
        self.preview_index = (self.preview_index + delta) % len(self.files)
        self.refresh_preview()

    def refresh_preview(self):
        if not self.files:
            self.draw_placeholder()
            return
        path = self.files[self.preview_index]
        self.nav_label.config(text="{} / {} — {}".format(
            self.preview_index + 1, len(self.files), os.path.basename(path)))
        try:
            self.preview_img = load_preview(path)
        except Exception as e:
            self.preview_img = None
            self.canvas.delete("all")
            self.canvas.create_text(CANVAS_W // 2, CANVAS_H // 2, fill=RED,
                                    text="Aperçu impossible :\n" + str(e),
                                    font=("Segoe UI", 10), justify="center")
            return
        self.draw_overlay()

    def draw_overlay(self):
        if self.preview_img is None:
            return
        img = self.preview_img
        w, h = img.size
        scale = min(CANVAS_W / w, CANVAS_H / h)
        dw, dh = int(w * scale), int(h * scale)
        disp = img.resize((dw, dh), Image.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(disp)

        x0 = (CANVAS_W - dw) // 2
        y0 = (CANVAS_H - dh) // 2
        self.canvas.delete("all")
        self.canvas.create_image(x0, y0, anchor="nw", image=self.preview_photo)

        cut_b = dh * self.pct_bottom.get() / 100.0
        cut_r = dw * self.pct_right.get() / 100.0
        if cut_b > 0:
            self.canvas.create_rectangle(x0, y0 + dh - cut_b, x0 + dw, y0 + dh,
                                         fill=RED, stipple="gray50", outline="")
        if cut_r > 0:
            self.canvas.create_rectangle(x0 + dw - cut_r, y0, x0 + dw, y0 + dh,
                                         fill=RED, stipple="gray50", outline="")
        # contour de ce qui est conservé
        self.canvas.create_rectangle(x0, y0, x0 + dw - cut_r, y0 + dh - cut_b,
                                     outline=GREEN, width=2)

    # ---------------------------------------------------------- traitement

    def start(self):
        if self.processing:
            return
        if not self.files:
            messagebox.showinfo("Elite Crop", "Ajoute d'abord des fichiers !")
            return
        if self.pct_bottom.get() == 0 and self.pct_right.get() == 0:
            messagebox.showinfo(
                "Elite Crop",
                "Les deux réglages sont à 0 % : rien ne serait coupé.\n"
                "Monte « Couper en bas » et/ou « Couper à droite » jusqu'à "
                "recouvrir le watermark en rouge.")
            return
        self.processing = True
        self.go_btn.config(state="disabled")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        pct_b = self.pct_bottom.get()
        pct_r = self.pct_right.get()
        total = len(self.files)
        errors = []
        last_dest = None
        for i, path in enumerate(self.files):
            name = os.path.basename(path)
            self._ui(lambda n=name, i=i: self.status.config(
                text="Traitement {}/{} : {}".format(i + 1, total, n)))
            try:
                if is_photo(path):
                    last_dest = process_photo(path, pct_b, pct_r)
                else:
                    last_dest = process_video(path, pct_b, pct_r)
            except Exception as e:
                errors.append("{} — {}".format(name, e))
            self._ui(lambda i=i: self.progress.config(value=(i + 1) * 100 / total))

        def finish():
            self.processing = False
            self.go_btn.config(state="normal")
            self.progress.config(value=0)
            done = total - len(errors)
            if errors:
                self.status.config(text="Terminé : {} réussi(s), {} erreur(s).".format(
                    done, len(errors)))
                messagebox.showwarning(
                    "Elite Crop — erreurs",
                    "Fichiers en erreur :\n\n" + "\n".join(errors[:10]))
            else:
                self.status.config(
                    text="✅ Terminé ! {} fichier(s) dans les dossiers « {} ».".format(
                        done, OUT_DIRNAME))
            if last_dest:
                os.startfile(os.path.dirname(last_dest))

        self._ui(finish)

    def _ui(self, fn):
        self.root.after(0, fn)


# ---------------------------------------------------------------- self-test


def selftest():
    """Vérifie le pipeline sans interface : crée une photo et une vidéo tests,
    les traite, et affiche les dimensions avant/après."""
    tmp = os.path.join(tempfile.gettempdir(), "elitecrop_selftest")
    os.makedirs(tmp, exist_ok=True)

    photo = os.path.join(tmp, "test.jpg")
    Image.new("RGB", (1000, 800), "#378ADD").save(photo)
    dest = process_photo(photo, 10, 5)
    print("photo :", Image.open(photo).size, "->", Image.open(dest).size, dest)

    video = os.path.join(tmp, "test.mp4")
    code, out = run_cmd([FFMPEG, "-y", "-f", "lavfi",
                         "-i", "testsrc=size=1280x720:rate=25:duration=2",
                         "-c:v", "libx264", "-preset", "veryfast", video])
    if code != 0:
        print("ERREUR création vidéo test :", out[-800:])
        return
    dest = process_video(video, 10, 5)
    print("vidéo :", (1280, 720), "->", video_first_frame(dest).size, dest)
    print("encodeur utilisé :", ENCODER.name)
    print("SELFTEST OK")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    if not os.path.exists(FFMPEG):
        messagebox.showerror(
            "Elite Crop",
            "ffmpeg.exe introuvable dans le dossier « bin ».\n"
            "Le dossier Elite Crop doit rester complet (bin + programme).")
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # En cas de plantage inattendu, on écrit l'erreur dans un fichier lisible.
        with open(os.path.join(BASE_DIR, "erreur.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise
