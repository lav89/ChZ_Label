#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChZ konvertetiketok: listy A4 s kodami markirovki -> otdelnaya stranitsa na kazhdyi kod.

Kazhdaia iacheika ishodnogo PDF vyrezetsia na otdelnyi list zadanogo razmera.
Sтриhkod ostaetsia vektorom (bez rasterizatsii) - pechataetsia chetko na lyubom razreshenii.
Posle sborki faily proveryavutsia avtomaticheski: kod obyazan chitatsia pri razreshenii printer.

ZAPUSK na Windows: peretaishchite fail(y) PDF na ChZ_Label_Convert.bat
                   libo:  ChZ_Label_Convert.bat papka_ili_faily [W mm] [H mm] [dpi]
Zpusk iz-pod Python:  python ChZ_Label_Convert.py <faily|papka> [W mm] [H mm] [dpi]

Po umolchaniyu: list 20 x 29 mm, krop "tolko kod s podpisyami + 2 mm", proverka pri 300 dpi.
"""
import glob
import os
import re
import sys

# bootstrap: biblioteki iz papki libs ryadom so skriptom (avtonomnaia sborka)
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "win-embed", "libs")
if not os.path.isdir(_LIB):
    _LIB = os.path.join(_HERE, "..", "win-embed", "libs")
if not os.path.isdir(_LIB):
    _LIB = os.path.join(_HERE, "libs")
if os.path.isdir(_LIB) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)
# vnutrennie biblioteki PDF-dvizka: v papkakh libs/pymupdf i pillow.libs
_CAND = [os.path.join(_LIB, "pymupdf"), _LIB, os.path.join(_HERE, "pillow.libs")]
for _sub in _CAND:
    if os.path.isdir(_sub):
        try:
            os.add_dll_directory(_sub)              # Windows: poisk .dll
        except (AttributeError, OSError):
            pass
        _p = os.environ.get("LD_LIBRARY_PATH", "")
        if _sub not in _p:                           # Linux: poisk .so
            os.environ["LD_LIBRARY_PATH"] = (_sub + os.pathsep + _p).strip(os.pathsep)
        if _sub not in sys.path:
            sys.path.append(_sub)

try:                                                    # Linux: razreshaem .so iz _linux
    import ctypes as _ct
    _L = os.path.join(_LIB, "_linux")
    if os.path.isdir(_L):
        for _f in sorted(os.listdir(_L)):
            if _f.endswith(".so") or ".so." in _f:
                try:
                    _ct.CDLL(os.path.join(_L, _f))
                except OSError:
                    pass
        if _L not in sys.path:                          # kopii modulya s .so ryadom
            sys.path.insert(0, _L)
except Exception:
    pass

if os.name != "nt":                                     # Linux-test: pakety s .so v otdelnuyu papku,
    # chtoby imya paketa pymupdf ne konfliktovalo s sistemnym (circ. import).
    try:
        import ctypes as _ct
        import shutil as _sh
        import tempfile as _tf
        _L = os.path.join(_LIB, "_linux")
        if os.path.isdir(_L):
            _pl = os.path.join(_LIB, "pillow.libs")     # zavisimosti Pillow
            _all = [_L] + ([_pl] if os.path.isdir(_pl) else [])
            for _dir in _all:
                for _f in sorted(os.listdir(_dir)):     # .so dvizhkov - do importa
                    if _f.endswith(".so") or ".so." in _f:
                        try:
                            _ct.CDLL(os.path.join(_dir, _f))
                        except OSError:
                            pass
            _w = os.path.join(_tf.gettempdir(), "chz_linux_libs_%d" % os.getpid())
            for _pkg in ("pymupdf", "PIL", "zxingcpp", "fitz"):
                _srcpkg = os.path.join(_LIB, _pkg)
                if not os.path.isdir(_srcpkg):
                    continue
                _dst = os.path.join(_w, _pkg)
                if not os.path.isdir(_dst):
                    _sh.copytree(_srcpkg, _dst)
                    for _dir in _all:                   # .so vykladivaem v kopii paketov
                        for _f in os.listdir(_dir):
                            if _f.endswith(".so") or ".so." in _f:
                                _n = _f
                                if _pkg == "zxingcpp" and _n.startswith("zxingcpp."):
                                    _n = "zxingcpp.so"  # 3.13 ne beret abi3-so iz paketa
                                try:
                                    _sh.copy2(os.path.join(_dir, _f), os.path.join(_dst, _n))
                                except OSError:
                                    pass
            if _w not in sys.path:
                sys.path.insert(0, _w)
    except Exception:
        pass

try:
    import pymupdf as fitz
except ImportError:
    sys.exit("NE NAIDEN MODUL pymupdf. Raspakuite arhiv TSELIKOM: papka libs dolzhna lezhat ryadom so skriptom.")


def page_geometry(page):
    """Granitsy iacheek po gorizontalnym razdelitelyam i razmer soderzhimogo pervoi iacheiki.

    Moduli koda ishchutya tolko v pervoi iacheike: inache v granitsy popadayut moduli
    sosednikh iacheek, krop razduvaetsya i kod pri umenshenii perestayet chitatsya.
    """
    lines = set()
    for dr in page.get_drawings():
        r = dr["rect"]
        if r.height < 1.5 and r.width > 50:
            lines.add(round((r.y0 + r.y1) / 2, 1))
    ys = sorted(lines)
    cells = []
    for k in range(0, len(ys) - 1, 2):
        top = ys[k]
        bottom = ys[k + 2] if k + 2 < len(ys) else page.rect.height
        cells.append((top, bottom))
    if not cells:
        cells = [(0.0, page.rect.height)]

    c_top, c_bot = cells[0]
    mods = [dr["rect"] for dr in page.get_drawings()
            if 0.5 < dr["rect"].width < 4 and 0.5 < dr["rect"].height < 4
            and c_top <= dr["rect"].y0 < c_bot]
    if not mods:
        raise SystemExit("Ne naideny moduli shtrikhkoda - proveryte razmetku faila.")
    code_box = fitz.Rect(
        min(r.x0 for r in mods), min(r.y0 for r in mods),
        max(r.x1 for r in mods), max(r.y1 for r in mods),
    )
    below = [b for b in page.get_text("blocks") if code_box.y0 <= b[1] < c_bot + 5]
    text_bot = max((b[3] for b in below), default=code_box.y1)
    return cells, code_box, text_bot


def convert(paths, lw_pt, lh_pt, crop, out_dir, margin=5.67):
    os.makedirs(out_dir, exist_ok=True)
    report = []
    for fidx, path in enumerate(paths, 1):
        src = fitz.open(path)
        cells, code_box, text_bot = page_geometry(src[0])
        c_top, c_bot = cells[0]
        if crop == "tight":
            x0 = max(src[0].rect.x0, code_box.x0 - margin)
            x1 = min(src[0].rect.x1, code_box.x1 + margin)
            y_rel = (code_box.y0 - c_top - margin, text_bot - c_top + margin)
        else:
            x0, x1 = src[0].rect.x0, src[0].rect.x1
            y_rel = (0.0, c_bot - c_top)
        out = fitz.open()
        for i in range(len(src)):
            for top, bottom in cells:
                y0 = top + y_rel[0]
                y1 = min(top + y_rel[1], src[i].rect.height)
                clip = fitz.Rect(x0, y0, x1, y1)
                if clip.is_empty or clip.height <= 0:
                    continue
                sc = min(lw_pt / clip.width, lh_pt / clip.height)
                w, h = clip.width * sc, clip.height * sc
                pg = out.new_page(width=lw_pt, height=lh_pt)
                pg.show_pdf_page(
                    fitz.Rect((lw_pt - w) / 2, (lh_pt - h) / 2,
                              (lw_pt + w) / 2, (lh_pt + h) / 2),
                    src, i, clip=clip,
                )
        m = re.search(r"gtin_(\d+)", os.path.basename(path))
        gtin = m.group(1) if m else "labels"
        name = os.path.join(out_dir, "labels_%s_%d.pdf" % (gtin, fidx))
        out.save(name, deflate=True, garbage=4, clean=True)
        report.append((name, out.page_count, len(cells), len(src)))
        src.close()
        out.close()
    return report


def verify(out_files, dpi=300, per_file=6):
    """Kod na kazhdoi proverennoi stranitse obyazan chitatsya pri dpi printera; dublei net."""
    problems = []
    seen = set()
    try:
        import io

        import zxingcpp
        from PIL import Image
    except ImportError:
        return ["Moduli proverki (zxing-cpp, Pillow) nedostupny - proverka propushchena"], 0
    for f in out_files:
        d = fitz.open(f)
        step = max(1, len(d) // per_file)
        for i in range(0, len(d), step):
            pix = d[i].get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            res = zxingcpp.read_barcodes(img)
            if not res:
                problems.append("%s str.%d: kod ne chitaetsya pri %d dpi"
                                % (os.path.basename(f), i + 1, dpi))
                continue
            if res[0].text in seen:
                problems.append("%s str.%d: dubl koda" % (os.path.basename(f), i + 1))
            seen.add(res[0].text)
        d.close()
    return problems, len(seen)


def collect_inputs(args):
    out = []
    for a in args:
        if os.path.isdir(a):
            out += sorted(glob.glob(os.path.join(a, "*.pdf")))
        elif a.lower().endswith(".pdf"):
            out.append(a)
    return [p for p in out if os.path.isfile(p)]


def main(argv):
    print("=" * 62)
    print("ChZ konvert etikaletok: kazhdyi kod na otdelnyi list")
    print("=" * 62)
    args = argv[1:]
    pdfs = collect_inputs(args)
    rest = [a for a in args if not a.lower().endswith(".pdf") and not os.path.isdir(a)]
    w_mm = float(rest[0]) if len(rest) >= 1 else 20.0
    h_mm = float(rest[1]) if len(rest) >= 2 else 29.0
    dpi = int(rest[2]) if len(rest) >= 3 and rest[2].isdigit() else 300

    if not pdfs:
        print("\nVhodnye PDF ne peredany.")
        print("Peretaishche faily na etot .bat libo ukazhite papku i (neobyazatelno)")
        print("razmer lista i dpi:  ChZ_Label_Convert.bat <faily|papka> [W mm] [H mm] [dpi]")
        print("Po umolchaniyu: 20 x 29 mm, proverka pri 300 dpi.")
        if os.name == "nt":
            input("\nNazhmite Enter dlya vykhoda.")
        return 2

    out_dir = os.path.join(os.path.dirname(os.path.abspath(pdfs[0])),
                           "etiketki_%dx%d" % (int(w_mm), int(h_mm)))
    print("\nVhodnykh failov: %d" % len(pdfs))
    print("List: %g x %g mm. Rezultat: %s\n" % (w_mm, h_mm, out_dir))

    r = convert(pdfs, w_mm * 72 / 25.4, h_mm * 72 / 25.4, "tight", out_dir)
    total = 0
    bad = False
    for name, pages, cells, src_pages in r:
        total += pages
        exp = src_pages * cells
        ok = pages == exp
        bad = bad or not ok
        print("%s: %d listov (%d str x %d koda) [%s]"
              % (os.path.basename(name), pages, src_pages, cells,
                 "OK" if ok else "OSHIBKA, ozhidalos %d" % exp))
    print("ITOGO listov: %d\n" % total)

    probs, uniq = verify(sorted(glob.glob(os.path.join(out_dir, "*.pdf"))), dpi)
    print("Proverka chteniya kodov pri %d dpi: provereno %d, zamechaniy %d" % (dpi, uniq, len(probs)))
    for p in probs:
        print("   ", p)

    if bad or probs:
        print("\nREZULTAT: est zamechaniya - proveryte faily pered pechatyu.")
    else:
        print("\nREZULTAT: vsyo v poryadke, faily gotovy k pechati.")
    print("Pechat: masshtab 100%%, bez 'vpisat v stranitsu', razreshenie printera to zhe, chto proveryalos (%d dpi)." % dpi)
    if os.name == "nt":
        input("\nNazhmite Enter dlya vykhoda.")
    return 1 if (bad or probs) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
