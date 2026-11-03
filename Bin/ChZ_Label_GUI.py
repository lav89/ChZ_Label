#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChZ konvert etikaletok - graficheskaya obolochka.

Vyberite PDF vygruzki CHZ, razmer nositelya i razreshenie printera; knopka
"Konvertirovat'" sdelaet kazhdyi kod na otdelnom liste i proveryt chtenie.
Raschetnaya logika - v ChZ_Label_Convert.py ryadom (togda zhe engine).
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import ChZ_Label_Convert as engine  # noqa: E402


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Конвертор этикеток ЧЗ")
        self.geometry("720x560")
        self.minsize(620, 480)
        self.files = []
        self.q = queue.Queue()
        self._busy = False

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Файлы выгрузки ЧЗ (PDF):").pack(anchor="w")

        row = ttk.Frame(top)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Добавить файлы…", command=self.add_files).pack(side="left")
        ttk.Button(row, text="Добавить папку…", command=self.add_folder).pack(side="left", padx=6)
        ttk.Button(row, text="Удалить выбранное", command=self.remove_sel).pack(side="left")
        ttk.Button(row, text="Очистить", command=self.clear).pack(side="left", padx=6)

        self.listbox = tk.Listbox(self, height=7, selectmode=tk.EXTENDED)
        self.listbox.pack(fill="x", padx=10)

        prm = ttk.LabelFrame(self, text="Параметры", padding=10)
        prm.pack(fill="x", padx=10, pady=8)

        g = ttk.Frame(prm)
        g.pack(fill="x")
        ttk.Label(g, text="Ширина листа, мм:").grid(row=0, column=0, sticky="w")
        self.e_w = ttk.Entry(g, width=8)
        self.e_w.insert(0, "20")
        self.e_w.grid(row=0, column=1, padx=(4, 18), sticky="w")
        ttk.Label(g, text="Высота листа, мм:").grid(row=0, column=2, sticky="w")
        self.e_h = ttk.Entry(g, width=8)
        self.e_h.insert(0, "29")
        self.e_h.grid(row=0, column=3, padx=(4, 18), sticky="w")
        ttk.Label(g, text="Разрешение принтера:").grid(row=0, column=4, sticky="w")
        self.cb_dpi = ttk.Combobox(g, values=["300", "203", "600"], width=6, state="readonly")
        self.cb_dpi.set("300")
        self.cb_dpi.grid(row=0, column=5, padx=(4, 0), sticky="w")

        self.crop = tk.StringVar(value="tight")
        ttk.Radiobutton(prm, text="Только код с подписями и полем 2 мм (максимальный размер кода)",
                        variable=self.crop, value="tight").pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(prm, text="Вся ячейка целиком (без увеличения кода)",
                        variable=self.crop, value="cell").pack(anchor="w")

        self.zip_it = tk.BooleanVar(value=True)
        ttk.Checkbutton(prm, text="По итогу собрать один ZIP с результатами",
                        variable=self.zip_it).pack(anchor="w", pady=(6, 0))

        act = ttk.Frame(self, padding=(10, 0))
        act.pack(fill="x")
        self.btn = ttk.Button(act, text="Конвертировать", command=self.start)
        self.btn.pack(side="left")
        self.btn_open = ttk.Button(act, text="Открыть папку результата", command=self.open_out, state="disabled")
        self.btn_open.pack(side="left", padx=8)
        self.pb = ttk.Progressbar(act, mode="indeterminate", length=200)
        self.pb.pack(side="right")

        self.log = tk.Text(self, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=10, pady=(8, 10))

        self.out_dir = None
        self.after(80, self.poll)

    # ---------------- spiski faylov ----------------
    def add_files(self):
        fs = filedialog.askopenfilenames(title="Выберите PDF выгрузки", filetypes=[("PDF", "*.pdf")])
        self._extend(fs)

    def add_folder(self):
        d = filedialog.askdirectory(title="Выберите папку с PDF")
        if d:
            import glob
            self._extend(sorted(glob.glob(os.path.join(d, "*.pdf"))))

    def _extend(self, fs):
        for f in fs:
            f = os.path.abspath(f)
            if f not in self.files and os.path.basename(f).lower().startswith("order_") or f not in self.files:
                if f not in self.files:
                    self.files.append(f)
                    self.listbox.insert("end", f)

    def remove_sel(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)
            del self.files[i]

    def clear(self):
        self.listbox.delete(0, "end")
        self.files = []

    # ---------------- zapusk ----------------
    def start(self):
        if self._busy:
            return
        if not self.files:
            messagebox.showwarning("Нет файлов", "Добавьте PDF-файлы выгрузки ЧЗ.")
            return
        try:
            w = float(self.e_w.get().replace(",", "."))
            h = float(self.e_h.get().replace(",", "."))
            if not (5 <= w <= 300 and 5 <= h <= 300):
                raise ValueError
        except ValueError:
            messagebox.showerror("Параметры", "Размеры листа — числа от 5 до 300 мм.")
            return
        dpi = int(self.cb_dpi.get())
        crop = self.crop.get()
        self._busy = True
        self.btn.config(state="disabled")
        self.btn_open.config(state="disabled")
        self.pb.start(12)
        threading.Thread(target=self.worker, args=(list(self.files), w, h, dpi, crop),
                         daemon=True).start()

    def worker(self, files, w, h, dpi, crop):
        q = self.q
        try:
            out_dir = os.path.join(os.path.dirname(files[0]), "etiketki_%dx%d" % (int(w), int(h)))
            q.put(("log", "Файлов: %d. Лист %g×%g мм, проверка %d dpi." % (len(files), w, h, dpi)))
            q.put(("log", "Результат: %s\n" % out_dir))
            r = engine.convert(files, w * 72 / 25.4, h * 72 / 25.4, crop, out_dir)
            total = 0
            bad = False
            for name, pages, cells, src_pages in r:
                total += pages
                exp = src_pages * cells
                ok = pages == exp
                bad = bad or not ok
                q.put(("log", "%s: %d листов (%d стр × %d кода) %s" % (
                    os.path.basename(name), pages, src_pages, cells,
                    "— ок" if ok else "— ОШИБКА, ожидалось %d" % exp)))
            q.put(("log", "Итого листов: %d\nПроверка чтения кодов при %d dpi…" % (total, dpi)))
            import glob
            probs, uniq = engine.verify(sorted(glob.glob(os.path.join(out_dir, "*.pdf"))), dpi)
            for p in probs:
                q.put(("log", "  ! " + p))
            if not probs:
                q.put(("log", "Проверено %d кодов, замечаний нет." % uniq))
            zip_path = None
            if self.zip_it.get():
                import zipfile
                zip_path = os.path.join(os.path.dirname(out_dir),
                                        "etiketki_%dx%d.zip" % (int(w), int(h)))
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in sorted(glob.glob(os.path.join(out_dir, "*.pdf"))):
                        z.write(f, os.path.basename(f))
                q.put(("log", "ZIP: %s (%.1f МБ)" % (zip_path, os.path.getsize(zip_path) / 1e6)))
            if bad or probs:
                q.put(("done", "Есть замечания — проверьте файлы перед печатью."
                         if not bad else "Число листов не совпало — файлы забракуйте."))
            else:
                q.put(("done", "Готово: %d листов. Файлы пригодны к печати; "
                         "масштаб в диалоге печати — 100%%." % total))
            q.put(("out", out_dir))
        except Exception as e:
            q.put(("error", "%s: %s" % (type(e).__name__, e)))

    def poll(self):
        try:
            while True:
                kind, msg = self.q.get_nowait()
                if kind == "log":
                    self._log(msg)
                elif kind == "out":
                    self.out_dir = msg
                    self.btn_open.config(state="normal")
                elif kind in ("done", "error"):
                    self._busy = False
                    self.btn.config(state="normal")
                    self.pb.stop()
                    if kind == "error":
                        self._log("ОШИБКА: " + msg)
                        messagebox.showerror("Ошибка", msg)
                    else:
                        messagebox.showinfo("Готово", msg)
        except queue.Empty:
            pass
        self.after(80, self.poll)

    def _log(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def open_out(self):
        if self.out_dir and os.path.isdir(self.out_dir):
            try:
                os.startfile(self.out_dir)  # noqa: S606 - Windows
            except AttributeError:
                subprocess.Popen(["xdg-open", self.out_dir])


if __name__ == "__main__":
    App().mainloop()
