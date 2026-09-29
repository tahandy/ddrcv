"""Native picker runs on its own main thread without blocking playback."""
import json
import sys
import tkinter as tk
from tkinter import filedialog

if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        path = filedialog.askdirectory(parent=root) if '--directory' in sys.argv else filedialog.askopenfilename(
            parent=root, filetypes=[('DDRCV catalogs', '*.ddrcatalog')] if '--catalog' in sys.argv else [('Video and images', '*.mp4 *.mkv *.avi *.mov *.png *.jpg *.jpeg *.bmp'), ('All files', '*.*')])
        print(json.dumps(path))
    finally:
        root.destroy()
