"""Folder picker dialog native Windows. Panggil via subprocess."""
import tkinter as tk
from tkinter import filedialog
import sys

root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
folder = filedialog.askdirectory(title="Pilih Folder")
root.destroy()
if folder:
    sys.stdout.write(folder)
else:
    sys.stdout.write("")
