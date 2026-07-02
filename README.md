# Elite Crop ✂️

Outil qui **enlève un watermark en bas à droite** de photos et vidéos,
**en masse**.

## 🌐 Utiliser en ligne (recommandé)

**https://elite-crop-production.up.railway.app**

Rien à installer : glisse tes fichiers, règle la zone rouge, clique
« ⚡ Tout traiter ». Les photos sont traitées instantanément dans le
navigateur ; les vidéos passent par le serveur (Railway).

## ⬇️ Ou télécharger l'application Windows

**[Télécharger Elite Crop (zip)](https://github.com/Vanillia75/elite-crop/releases/latest/download/Elite-Crop.zip)**

1. Dézippe le fichier où tu veux.
2. Double-clique sur `Elite-Crop.exe`.
3. Si Windows affiche « Windows a protégé votre ordinateur » : clique
   « Informations complémentaires » puis « Exécuter quand même » (normal pour
   un programme maison, non signé).

## 🚀 Utilisation

1. **Ajouter des fichiers** (ou un dossier entier) — photos JPG, PNG, WebP,
   BMP, TIFF et vidéos MP4, MOV, MKV, AVI, WebM…
2. Monte les curseurs **« Couper en bas »** et **« Couper à droite »** jusqu'à
   ce que le watermark soit dans la zone rouge de l'aperçu. Les réglages sont
   en %, donc ils s'adaptent aux fichiers de tailles différentes.
3. **⚡ Tout traiter** : les fichiers nettoyés arrivent dans un sous-dossier
   `Sans-watermark` à côté des originaux (jamais modifiés).

## ⚙️ Sous le capot

- Interface : Python + Tkinter (`elite_crop.py`).
- Vidéos : ffmpeg embarqué, avec encodage matériel automatique
  (NVIDIA NVENC → Intel QSV → AMD AMF → processeur).
- Exe autonome construit avec PyInstaller.
