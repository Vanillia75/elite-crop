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

# ------------------------------------------------------------------ langues
LANG_FILE = os.path.join(os.path.expanduser("~"), ".elite_crop_lang")

I18N = {
    "fr": {
        "title": "Elite Crop — enlève le watermark en bas à droite",
        "addFiles": "➕ Ajouter des fichiers",
        "addFolder": "📁 Ajouter un dossier",
        "clearList": "🗑 Vider la liste",
        "count": "{n} fichiers · {photos} photos · {videos} vidéos",
        "navPrev": "◀ Fichier précédent",
        "navNext": "Fichier suivant ▶",
        "cutBottom": "Couper en bas",
        "cutRight": "Couper à droite",
        "compressLabel": "Compresser",
        "mode_none": "Qualité max",
        "mode_light": "Légère",
        "mode_medium": "Moyenne",
        "mode_strong": "Forte",
        "mode_extreme": "Extrême",
        "go": "⚡ Tout traiter",
        "ready": "Ajoute des fichiers pour commencer.",
        "processing": "Traitement {i}/{total} : {name}",
        "doneOk": "✅ Terminé ! {n} fichier(s) dans les dossiers « {folder} ».",
        "doneErr": "Terminé : {done} réussi(s), {err} erreur(s).",
        "placeholder": ("Aperçu\n\nAjoute des fichiers : la zone rouge montre\n"
                        "ce qui sera coupé (le watermark doit être dedans)."),
        "previewFail": "Aperçu impossible :\n{e}",
        "dlgFilesTitle": "Choisis tes photos et vidéos",
        "dlgFilesType": "Photos et vidéos",
        "dlgAllFiles": "Tous les fichiers",
        "dlgFolderTitle": "Choisis un dossier",
        "noFiles": "Ajoute d'abord des fichiers !",
        "nothing": ("Rien à faire : aucun rognage et aucune compression.\n\n"
                    "Monte « Couper en bas » et/ou « Couper à droite » pour couper "
                    "le watermark, ou choisis un mode de compression pour exporter "
                    "des fichiers plus légers sans rogner."),
        "errorsTitle": "Elite Crop — erreurs",
        "errorsIntro": "Fichiers en erreur :",
        "ffmpegMissing": ("ffmpeg.exe introuvable dans le dossier « bin ».\n"
                          "Le dossier Elite Crop doit rester complet (bin + programme)."),
    },
    "en": {
        "title": "Elite Crop — remove the bottom-right watermark",
        "addFiles": "➕ Add files",
        "addFolder": "📁 Add a folder",
        "clearList": "🗑 Clear list",
        "count": "{n} files · {photos} photos · {videos} videos",
        "navPrev": "◀ Previous file",
        "navNext": "Next file ▶",
        "cutBottom": "Cut bottom",
        "cutRight": "Cut right",
        "compressLabel": "Compress",
        "mode_none": "Max quality",
        "mode_light": "Light",
        "mode_medium": "Medium",
        "mode_strong": "Strong",
        "mode_extreme": "Extreme",
        "go": "⚡ Process all",
        "ready": "Add files to get started.",
        "processing": "Processing {i}/{total}: {name}",
        "doneOk": "✅ Done! {n} file(s) in the “{folder}” folders.",
        "doneErr": "Done: {done} succeeded, {err} error(s).",
        "placeholder": ("Preview\n\nAdd files: the red zone shows\n"
                        "what will be cut (the watermark must be inside it)."),
        "previewFail": "Preview unavailable:\n{e}",
        "dlgFilesTitle": "Choose your photos and videos",
        "dlgFilesType": "Photos and videos",
        "dlgAllFiles": "All files",
        "dlgFolderTitle": "Choose a folder",
        "noFiles": "Add files first!",
        "nothing": ("Nothing to do: no cropping and no compression.\n\n"
                    "Move “Cut bottom” and/or “Cut right” to cut the "
                    "watermark, or pick a compression mode to export lighter files "
                    "without cropping."),
        "errorsTitle": "Elite Crop — errors",
        "errorsIntro": "Files with errors:",
        "ffmpegMissing": ("ffmpeg.exe not found in the “bin” folder.\n"
                          "The Elite Crop folder must stay complete (bin + program)."),
    },
}


def _detect_lang():
    try:
        with open(LANG_FILE, encoding="utf-8") as f:
            v = f.read().strip()
            if v in ("fr", "en"):
                return v
    except OSError:
        pass
    try:
        import locale
        loc = locale.getdefaultlocale()[0] or ""
    except Exception:
        loc = ""
    return "fr" if loc.lower().startswith("fr") else "en"


CUR_LANG = _detect_lang()


def _save_lang(lang):
    try:
        with open(LANG_FILE, "w", encoding="utf-8") as f:
            f.write(lang)
    except OSError:
        pass


def t(key, **params):
    d = I18N.get(CUR_LANG, I18N["fr"])
    s = d.get(key, I18N["fr"].get(key, key))
    for k, v in params.items():
        s = s.replace("{" + k + "}", str(v))
    return s


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


# Niveaux de compression : (crf processeur, qualité carte graphique, plafond du
# plus grand côté en px). Plus le chiffre est haut, plus c'est léger.
QUALITY = {
    "none":    ("20", "22", 0),
    "light":   ("24", "26", 0),
    "medium":  ("26", "28", 1920),
    "strong":  ("30", "32", 1280),
    "extreme": ("34", "36", 960),
}


def scale_dims(w, h, max_long):
    """Nouvelle taille pour que le plus grand côté ne dépasse pas max_long.
    Renvoie None si aucune réduction n'est nécessaire (on n'agrandit jamais)."""
    longest = max(w, h)
    if not max_long or longest <= max_long:
        return None
    r = max_long / longest
    return even(max(2, round(w * r))), even(max(2, round(h * r)))


def encoder_candidates(cq, crf):
    """Encodeurs du plus rapide au plus lent : cartes NVIDIA, Intel, AMD, puis
    le processeur (marche partout). Le premier qui fonctionne est réutilisé."""
    return [
        ("carte NVIDIA", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", cq]),
        ("carte Intel", ["-c:v", "h264_qsv", "-preset", "veryfast",
                         "-global_quality", cq]),
        ("carte AMD", ["-c:v", "h264_amf", "-quality", "speed"]),
        ("processeur", ["-c:v", "libx264", "-preset", "veryfast", "-crf", crf]),
    ]


class VideoEncoder:
    """Choisit l'encodeur le plus rapide qui fonctionne sur cette machine."""

    def __init__(self):
        self.start = 0   # index du premier candidat encore plausible
        self.name = None

    def encode(self, src, dest, crop_w, crop_h, level="none"):
        crf, cq, max_long = QUALITY.get(level, QUALITY["none"])
        vf = "crop={}:{}:0:0".format(crop_w, crop_h)
        sc = scale_dims(crop_w, crop_h, max_long)
        if sc:
            vf += ",scale={}:{}".format(sc[0], sc[1])
        candidates = encoder_candidates(cq, crf)
        last_out = ""
        for i in range(self.start, len(candidates)):
            name, vargs = candidates[i]
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


def process_video(src, pct_bottom, pct_right, level="none"):
    frame = video_first_frame(src)
    w, h = frame.size
    crop_w = even(max(16, w - round(w * pct_right / 100.0)))
    crop_h = even(max(16, h - round(h * pct_bottom / 100.0)))

    dest = out_path_for(src)
    ext = os.path.splitext(src)[1].lower()
    if ext not in (".mp4", ".mov", ".m4v", ".mkv"):
        dest = os.path.splitext(dest)[0] + ".mp4"
    ENCODER.encode(src, dest, crop_w, crop_h, level)
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
        self._i18n = []              # (widget, clé de traduction)

        root.configure(bg=NIGHT)
        root.resizable(False, False)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=8)
        style.configure("Horizontal.TProgressbar",
                        troughcolor=INK, background=GREEN)

        # --- barre du haut : gestion des fichiers + langue
        top = tk.Frame(root, bg=NIGHT)
        top.pack(fill="x", padx=14, pady=(12, 6))
        self._reg(ttk.Button(top, command=self.add_files),
                  "addFiles").pack(side="left")
        self._reg(ttk.Button(top, command=self.add_folder),
                  "addFolder").pack(side="left", padx=(8, 0))
        self._reg(ttk.Button(top, command=self.clear_files),
                  "clearList").pack(side="left", padx=(8, 0))
        self.lang_box = ttk.Combobox(top, state="readonly", width=4,
                                     values=["FR", "EN"], font=("Segoe UI", 9))
        self.lang_box.set(CUR_LANG.upper())
        self.lang_box.bind("<<ComboboxSelected>>", self._on_lang)
        self.lang_box.pack(side="right")
        self.count_label = tk.Label(top, text="", bg=NIGHT,
                                    fg=GREEN, font=("Segoe UI", 10, "bold"))
        self.count_label.pack(side="right", padx=(0, 10))

        # --- aperçu
        self.canvas = tk.Canvas(root, width=CANVAS_W, height=CANVAS_H,
                                bg=INK, highlightthickness=0)
        self.canvas.pack(padx=14, pady=6)

        nav = tk.Frame(root, bg=NIGHT)
        nav.pack(fill="x", padx=14)
        self._reg(ttk.Button(nav, width=20,
                             command=lambda: self.step_preview(-1)),
                  "navPrev").pack(side="left")
        self.nav_label = tk.Label(nav, text="", bg=NIGHT, fg="white",
                                  font=("Segoe UI", 9))
        self.nav_label.pack(side="left", expand=True)
        self._reg(ttk.Button(nav, width=20,
                             command=lambda: self.step_preview(1)),
                  "navNext").pack(side="right")

        # --- réglages
        sliders = tk.Frame(root, bg=NIGHT)
        sliders.pack(fill="x", padx=14, pady=(10, 0))
        self.pct_bottom = tk.DoubleVar(value=8.0)
        self.pct_right = tk.DoubleVar(value=0.0)
        self._make_slider(sliders, "cutBottom", self.pct_bottom)
        self._make_slider(sliders, "cutRight", self.pct_right)

        # --- compression à l'export
        comp = tk.Frame(root, bg=NIGHT)
        comp.pack(fill="x", padx=14, pady=(8, 0))
        self._reg(tk.Label(comp, width=14, anchor="w", bg=NIGHT, fg="white",
                           font=("Segoe UI", 10)), "compressLabel").pack(side="left")
        self.compress = tk.StringVar(value="none")
        for lvl in ("none", "light", "medium", "strong", "extreme"):
            self._reg(tk.Radiobutton(comp, value=lvl, variable=self.compress,
                                     bg=NIGHT, fg="white", selectcolor=INK,
                                     activebackground=NIGHT, activeforeground=GREEN,
                                     highlightthickness=0, font=("Segoe UI", 9)),
                      "mode_" + lvl).pack(side="left", padx=(6, 0))

        # --- action + progression
        bottom = tk.Frame(root, bg=NIGHT)
        bottom.pack(fill="x", padx=14, pady=12)
        self.go_btn = self._reg(ttk.Button(bottom, style="Big.TButton",
                                           command=self.start), "go")
        self.go_btn.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, maximum=100)
        self.progress.pack(fill="x", pady=(8, 0))
        self.status = tk.Label(bottom, text="", bg=NIGHT, fg="white",
                               font=("Segoe UI", 9), anchor="w", justify="left")
        self.status.pack(fill="x", pady=(6, 0))

        self.apply_lang()

    # --------------------------------------------------------------- langue

    def _reg(self, widget, key):
        """Mémorise un widget et sa clé de traduction pour le mettre à jour
        quand on change de langue."""
        self._i18n.append((widget, key))
        return widget

    def _on_lang(self, _event=None):
        self.set_lang(self.lang_box.get().lower())

    def set_lang(self, lang):
        global CUR_LANG
        CUR_LANG = "en" if lang == "en" else "fr"
        _save_lang(CUR_LANG)
        self.apply_lang()

    def apply_lang(self):
        self.root.title(t("title"))
        for widget, key in self._i18n:
            widget.config(text=t(key))
        self.lang_box.set(CUR_LANG.upper())
        self.update_count()
        if not self.processing:
            self.status.config(text=t("ready"))
        if self.files:
            self.refresh_preview()
        else:
            self.draw_placeholder()

    # ------------------------------------------------------------- fichiers

    def add_files(self):
        exts = sorted(PHOTO_EXTS | VIDEO_EXTS)
        pattern = " ".join("*" + e for e in exts)
        paths = filedialog.askopenfilenames(
            title=t("dlgFilesTitle"),
            filetypes=[(t("dlgFilesType"), pattern), (t("dlgAllFiles"), "*.*")])
        self._add(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title=t("dlgFolderTitle"))
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
        self.count_label.config(text=t("count", n=n, photos=photos, videos=videos))

    # -------------------------------------------------------------- aperçu

    def _make_slider(self, parent, key, var):
        row = tk.Frame(parent, bg=NIGHT)
        row.pack(fill="x", pady=3)
        self._reg(tk.Label(row, width=14, anchor="w", bg=NIGHT, fg="white",
                           font=("Segoe UI", 10)), key).pack(side="left")
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
            text=t("placeholder"), justify="center")

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
                                    text=t("previewFail", e=e),
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
            messagebox.showinfo("Elite Crop", t("noFiles"))
            return
        if (self.pct_bottom.get() == 0 and self.pct_right.get() == 0
                and self.compress.get() == "none"):
            messagebox.showinfo("Elite Crop", t("nothing"))
            return
        self.processing = True
        self.go_btn.config(state="disabled")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        pct_b = self.pct_bottom.get()
        pct_r = self.pct_right.get()
        level = self.compress.get()
        total = len(self.files)
        errors = []
        last_dest = None
        for i, path in enumerate(self.files):
            name = os.path.basename(path)
            self._ui(lambda n=name, i=i: self.status.config(
                text=t("processing", i=i + 1, total=total, name=n)))
            try:
                if is_photo(path):
                    last_dest = process_photo(path, pct_b, pct_r)
                else:
                    last_dest = process_video(path, pct_b, pct_r, level)
            except Exception as e:
                errors.append("{} — {}".format(name, e))
            self._ui(lambda i=i: self.progress.config(value=(i + 1) * 100 / total))

        def finish():
            self.processing = False
            self.go_btn.config(state="normal")
            self.progress.config(value=0)
            done = total - len(errors)
            if errors:
                self.status.config(text=t("doneErr", done=done, err=len(errors)))
                messagebox.showwarning(
                    t("errorsTitle"),
                    t("errorsIntro") + "\n\n" + "\n".join(errors[:10]))
            else:
                self.status.config(text=t("doneOk", n=done, folder=OUT_DIRNAME))
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
    for level in ("none", "light", "medium", "strong", "extreme"):
        dest = process_video(video, 10, 5, level)
        size = os.path.getsize(dest)
        print("vidéo [{}] : (1280, 720) -> {}  {} o".format(
            level, video_first_frame(dest).size, size))
    print("encodeur utilisé :", ENCODER.name)
    print("SELFTEST OK")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    if not os.path.exists(FFMPEG):
        messagebox.showerror("Elite Crop", t("ffmpegMissing"))
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
