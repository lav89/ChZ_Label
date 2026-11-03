# -*- coding: utf-8 -*-
# ПОРТАТИВНЫЙ ЗАПУСК: рядом лежит win-embed\ — встроенный Python 3.13
# (с Tkinter) и библиотеками: pystrich, reportlab, Pillow. Запуск — двойной
# клик по "Генератор datamatrix.bat".
# Ничего устанавливать не нужно. Логика генерации ниже — без изменений.
# (clean_gs1_string / extract_gtin_from_file / run_generation / AppMarkingGUI)
# оставлен БЕЗ изменений.
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
NO_GUI = '--no-gui' in _sys.argv  # запуск без окна: "Генератор datamatrix.bat" файл.csv --no-gui
_VEND = None
for _c in (_os.path.join(_HERE, 'win-embed', 'libs'),
           _os.path.join(_HERE, '_vendor', 'libs')):
    if _os.path.isdir(_c):
        _VEND = _c
        if _c not in _sys.path:
            _sys.path.insert(1, _c)
def _dm_pil_check():  # понятная диагностика, если Pillow не подошёл по версии
    try:
        from PIL import Image  # noqa: F401
    except ImportError as _e:
        try:
            _v = open(_os.path.join(_VEND, 'PIL', '_version.py'), encoding='utf-8').read()
        except Exception:
            _v = ''
        _sys.stderr.write(
            'Не подходит библиотека Pillow (PIL): %s\n'
            'Версия Pillow в комплекте: %s, версия Python: %s.\n'
            'Перешлите это сообщение разработчику - комплект пересобирается\n'
            'под Вашу версию Python за пару минут.\n'
            % (_e, _v.strip(), _sys.version.split()[0]))
        raise

# Если скрипт запустили НЕ встроенным Python (двойной клик по .py), а своим
# системным — библиотека Pillow в комплекте под него может не подойти. Даём
# понятную подсказку вместо трассировки.
if _sys.version_info[:2] not in ((3, 12), (3, 13)) and 'win-embed' not in _os.path.normcase(_sys.executable):
    _sys.stderr.write(
        'Внимание: скрипт запущен внешним Python %s, а не встроенным из win-embed.\r\n'
        'Запустите "Генератор datamatrix.bat" — он использует встроенный Python\r\n'
        'со всеми библиотеками, ничего устанавливать не нужно.\r\n'
        '(Если запускать именно этим Python, нужны: tkinter, pystrich, reportlab, Pillow)\r\n\r\n'
        % _sys.version.split()[0])
if _os.name == 'posix':  # предзагрузка библиотек Pillow для проверки на Linux
    try:
        import ctypes as _ct
        _pl = _os.path.join(_HERE, 'win-embed', 'libs', 'pillow.libs')
        if not _os.path.isdir(_pl): _pl = _os.path.join(_HERE, '..', 'win-embed', 'libs', 'pillow.libs')
        if _os.path.isdir(_pl):
            for _f in sorted(_os.listdir(_pl)):
                if _f.startswith('lib') and '.so' in _f:
                    try:
                        _ct.CDLL(_os.path.join(_pl, _f), mode=_ct.RTLD_GLOBAL)
                    except OSError:
                        pass
    except Exception:
        pass
else:
    _dm_pil_check()

import csv
import os
import io
import re
import threading
import subprocess
if not NO_GUI:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
from pystrich.datamatrix import DataMatrixEncoder, FNC1
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

def clean_gs1_string(raw_line):
    """Очистка строки от текстовых артефактов разделителей Честного Знака"""
    text = raw_line.strip()
    text = text.replace("<GS>", "\x1d")
    text = text.replace("[GS]", "\x1d")
    text = text.replace("\\x1d", "\x1d")
    text = text.replace("\\x", "\x1d")
    
    for identifier in [" 91", " 92", " 93", "_91", "_92", "_93"]:
        if identifier in text:
            text = text.replace(identifier, "\x1d" + identifier[1:])
            
    return text

def extract_gtin_from_file(csv_path):
    """
    Ищет GTIN (14 цифр после '01' или просто первые 14 цифр) 
    в первой заполненной строке файла для красивого именования.
    """
    try:
        with open(csv_path, mode='r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                clean_line = line.strip()
                if not clean_line:
                    continue
                
                # Шаблон 1: Ищем 14 цифр, которые идут сразу после признака "01" в начале или после спецсимволов
                match = re.search(r'(?:^|[^0-9])01([0-9]{14})', clean_line)
                if match:
                    return match.group(1)
                
                # Шаблон 2: Если "01" нет, но строка начинается с 14 цифр (чистый GTIN)
                match_pure = re.match(r'^([0-9]{14})', clean_line)
                if match_pure:
                    return match_pure.group(1)
                    
                # Шаблон 3: На крайний случай берем любые первые 14 цифр подряд из строки
                match_any = re.search(r'([0-9]{14})', clean_line)
                if match_any:
                    return match_any.group(1)
    except Exception:
        pass
    return None

def _tsl_text(s):
    """Текст для TSPL (TSC): кириллица в CP1251 (шрифт TSS24.BF2 принтера)."""
    return s.replace('"', '').encode('cp1251', errors='replace').decode('cp1251')


def _tspl_text_width_dots(text, pt, prn_dots):
    """Ширина строки в точках принтера при кегле pt (реальная метрика TTF,
    как в PDF). Возвращает None, если TTF недоступен (тогда оценка 0.55*кегель)."""
    try:
        from PIL import ImageFont
        here = os.path.dirname(os.path.abspath(__file__))
        for d in (os.path.join(here, 'assets'),
                  os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts'),
                  '/usr/share/fonts/truetype/liberation'):
            fp = os.path.join(d, 'LiberationSans-Regular.ttf')
            if not os.path.exists(fp):
                fp = os.path.join(d, 'arial.ttf')
            if os.path.exists(fp):
                px = max(16, int(round(pt * prn_dots * 25.4 / 72.0))) * 4
                f = ImageFont.truetype(fp, px)
                dots = pt * prn_dots * 25.4 / 72.0
                return f.getlength(text) / px * dots
    except Exception:
        pass
    return None


def _text_dots_width(text, pt, prn_dots):
    """Ширина строки в точках принтера при кегле pt (TTF-метрика как в PDF;
    без TTF — оценка 0.52*кегель на символ)."""
    wpt = None
    try:
        from reportlab.pdfbase import pdfmetrics
        font = 'Helvetica'
        wpt = pdfmetrics.stringWidth(text, font, pt)
    except Exception:
        wpt = len(text) * pt * 0.52
    return wpt * prn_dots * 25.4 / 72.0


def _tspl_dm_text(raw):
    """Содержимое КМ для команды DMATRIX (принтеры TSC, режим c126 = GS1).
    Экранирование как в эталонном PRN принтера: первый символ ~ = FNC1
    (его добавляем сами), дальше GS (\x1d) -> ~d01D; прочие непечатаемые и
    '~' -> ~dNNN (NNN — байт в шестнадцатеричном виде; пример эталона:
    ~d029 = 0x29 = '(')."""
    out = ['~']
    for ch in raw:
        o = ord(ch)
        # кавычка, ~ и все непечатаемые/нелатинские — ~dNNN (NNN = байт в HEX):
        # кавычку выбрасывать НЕЛЬЗЯ — серийный номер ЧЗ может её содержать
        # (в партии «виноград 40» таких ~9% кодов); удаление портит КМ.
        if o < 32 or o > 126 or ch in ('~', '"'):
            out.append('~d%03X' % o)
        else:
            out.append(ch)
    return ''.join(out)

def run_generation(csv_path, code_size, padding, max_pages, force_gs1, progress_callback, caption=None, number_start=None, prn_dir=None, printer_name=None, code_text=True, font_size=None, max_labels_per_file=500, prn_native=True, prn_dots=None):
    """Основная логика генерации с динамическим GTIN-префиксом"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Файл {csv_path} не найден!")

    page_size_pt = code_size * mm
    padding_pt = padding * mm
    barcode_size_pt = page_size_pt - (2 * padding_pt)
    
    if barcode_size_pt <= 0:
        raise ValueError("Размер полей слишком большой! Штрихкод не помещается на странице.")

    total_count = 0
    file_part = 1
    current_file_pages = 0
    c = None
    
    output_dir = os.path.dirname(csv_path)

    # Автоматически вытаскиваем GTIN для префикса
    gtin = extract_gtin_from_file(csv_path)
    pdf_prefix = f"gtin_{gtin}" if gtin else "datamatrix"

    # Шрифт с кириллицей для подписей: assets\LiberationSans-Regular.ttf
    # (в комплекте); нет — системный Arial; нет и его — базовый Helvetica.
    caption = (caption or '').strip() or None
    base_fs = max(3.0, float(font_size)) if font_size else 6.2
    caption_font = ('Helvetica-Bold', base_fs)
    _here = os.path.dirname(os.path.abspath(__file__))
    run_generation._tfont_cache = {}
    run_generation._tfont_bold = None
    tdots_px = max(8, int(round(base_fs * 203.0 / 72.0)))   # кегль в точках принтера
    def _find_font(*names):
        for n in names:
            for d in (os.path.join(_here, 'assets'),
                      os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts'),
                      '/usr/share/fonts/truetype/liberation'):
                p2 = os.path.join(d, n)
                if os.path.exists(p2):
                    return p2
        return None
    _fpath = _find_font('LiberationSans-Regular.ttf', 'arial.ttf')
    if _fpath:
        try:
            from PIL import ImageFont as _IFont
            run_generation._tfont_cache[base_fs] = _IFont.truetype(_fpath, tdots_px)
            _bpath = _find_font('LiberationSans-Bold.ttf', 'arialbd.ttf')
            if _bpath:
                run_generation._tfont_bold = _IFont.truetype(_bpath, tdots_px)
        except Exception:
            pass
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont as _RLTTFont
            pdfmetrics.registerFont(_RLTTFont('LabelFont', _fpath))
            caption_font = ('LabelFont', base_fs)
            _bpath = _find_font('LiberationSans-Bold.ttf', 'arialbd.ttf')
            if _bpath:
                pdfmetrics.registerFont(_RLTTFont('LabelFontB', _bpath))
        except Exception:
            pass


    # Вывод PRN для принтеров TSC (язык TSPL, 203 dpi = 8 точек/мм)
    def _env_num_local(name, dflt):
        try:
            return float(os.environ.get(name, '').strip() or dflt)
        except ValueError:
            return dflt

    prn_file = None
    prn_dots = float(prn_dots) if prn_dots else _env_num_local('PRN_DPI', 8.0)   # 8 = 203 dpi; 11.811 = 300 dpi (например TSC MH341)
    if prn_dir:
        os.makedirs(prn_dir, exist_ok=True)
        prn_name = f"{pdf_prefix}.prn" if gtin else "datamatrix.prn"
        prn_file = open(os.path.join(prn_dir, prn_name), 'wb')

    def _text_font(pt_size):
        """TTF для подписей (общий для PDF и PRN) или None."""
        return getattr(run_generation, '_tfont_cache', {}).get(pt_size)

    def _wrap_font():
        """Шрифт, которым измеряем перенос: жирный (код рисуем жирным), else reg."""
        return run_generation._tfont_bold or run_generation._tfont_cache.get(base_fs)

    def _twd(s):
        """Ширина строки на кегле base_fs в тех же единицах, что и avail_w у
        _wrap_lines. PIL-шрифт измеряем честно; если он недоступен — по
        reportlab (PDF-кегль) или грубой прикидкой."""
        fnt = _wrap_font()
        if fnt is not None:
            try:
                return int(fnt.getlength(s)) + 2
            except Exception:
                try:
                    return int(fnt.getmask(s).size[0]) + 2
                except Exception:
                    pass
        try:
            from reportlab.pdfbase import pdfmetrics as _pm
            return int(_pm.stringWidth(s, caption_font[0], caption_font[1])) + 2
        except Exception:
            pass
        return sum(24 if ord(ch) > 127 else 12 for ch in s)

    def _wrap_lines(lines, avail_w):
        """Перенос строк по ширине: сперва по словам/границам ")(" , куски длиннее
        строки режем посимвольно — итоговая строка гарантированно влезает."""
        out = []
        for t0 in lines:
            # жёсткая гарантия ширины: строку-то, что всё равно длиннее полосы
            # целиком (даже посимвольно не режется переносом), дробим по символам
            # принудительно — так ни одна строка не уйдёт за край этикетки.
            if t0 and _twd(t0) <= avail_w:
                out.append(t0)
                continue
            if t0 and ' ' not in t0 and _twd(t0[:1]) > avail_w:
                # даже один символ шире строки — невозможный кегль, пропускаем кроху
                pass
            t = t0
            tokens = []
            rest = t
            while ')(' in rest:
                i2 = rest.index(')(') + 2
                tokens.append(rest[:i2])
                rest = rest[i2:]
            if rest or not tokens:
                tokens.append(rest)
            # токен, который сам длиннее строки, дробим посимвольно сразу —
            # иначе жадная сборка не оставит места и текст уедет за край
            split_tokens = []
            for tk0 in tokens:
                if _twd(tk0) <= avail_w:
                    split_tokens.append(tk0)
                    continue
                while tk0:
                    p3 = tk0[:-1]
                    while p3 and _twd(p3) > avail_w:
                        p3 = p3[:-1]
                    if not p3:
                        p3 = tk0[:1]
                    split_tokens.append(p3)
                    tk0 = tk0[len(p3):]
            tokens = split_tokens
            cur = ''
            for tk in tokens:
                # строка со словами переносится по словам (подписи, человекочитаемый
                # текст); слитные блоки (содержимое КМ) — по границам ")("
                if ' ' in tk and _twd(cur + tk) > avail_w:
                    words = tk.split(' ')
                    words = [w if i == 0 else ' ' + w for i, w in enumerate(words)]
                    for w in words:
                        piece = cur + w
                        while len(piece) > len(cur) and _twd(piece) > avail_w:
                            out.append(cur if len(cur) > 0 else piece[:len(cur)])
                            piece = piece[len(cur):]
                            cur = ''
                        cur = piece
                    continue
                while tk:
                    piece = tk
                    while piece and _twd((cur + piece) if cur else piece) > avail_w:
                        piece = piece[:-1]
                    if not piece:
                        piece = tk[0]          # один символ — всегда печатаем
                    if cur and _twd(cur + piece) > avail_w:
                        out.append(cur)
                        cur = ''
                        continue
                    cur += piece
                    tk = tk[len(piece):]
            if cur:
                out.append(cur)
        return out

    def _tspl_text_dots(t):
        """Кегль (pt) в точки принтера (через prn_dots: 8 = 203 dpi, 11.811 = 300)."""
        return max(8, int(round(float(t) * prn_dots * 25.4 / 72.0)))

    def _render_text_bitmap(text, dots, img_w):
        """Строка текста как 1-битный bitmap нужной высоты (dots — строка в точках
        принтера). Рендер через FreeType-маску на большом кегле (HarfBuzz/raqm на
        части сборок Pillow падает — его обходим). Если строка не влезает в
        img_w — сжимаем по ширине; при чрезмерном сжатии возвращаем None
        (строка должна была быть перенесена)."""
        from PIL import Image as _PILImage
        fnt = run_generation._tfont_bold or run_generation._tfont_cache.get(base_fs)
        if fnt is None:
            return None
        try:
            mask = fnt.getmask(text)
            mw, mh = mask.size
            if mw < 1 or mh < 1:
                return None
            img = _PILImage.new('L', (mw, mh), 0)
            img.putdata([255 if v else 0 for v in mask])
        except Exception:
            return None
        bbox = img.getbbox()
        if bbox is None:
            return None
        img = img.crop(bbox)
        target_h = max(6, dots)
        scale = target_h / img.height
        target_w = max(1, int(round(img.width * scale)))
        if target_w > img_w:
            if target_w <= int(img_w * 1.12):
                target_w = img_w      # лёгкое сжатие по ширине допустимо
            else:
                return None           # строка должна быть перенесена
        img = img.resize((target_w, target_h), _PILImage.BILINEAR)
        frame = target_w + (8 - target_w % 8) % 8
        bpr = frame // 8
        px = img.load()
        out = []
        for y in range(target_h):
            row = bytearray(bpr)
            for x in range(target_w):
                if px[x, y] > 110:
                    row[x // 8] |= 0x80 >> (x % 8)
            out.append(bytes(row))
        return out, target_w, frame

    def write_prn_label(validated_line, lines):
        """Один кадр TSPL: та же матрица, что и в PDF, в BITMAP + текст."""
        # Полная матрица с finder-рамкой и тихой зоной — ровно как в PDF-картинке.
        # Строка grid[0] — НИЖНЯЯ (pystrich рендерит снизу вверх), TSPL пишет
        # BITMAP сверху вниз, поэтому строки идут в обратном порядке.
        renderer = DataMatrixEncoder(FNC1 + validated_line if force_gs1 else validated_line).init_renderer()
        grid = renderer.matrix
        n = len(grid)
        W = int(code_size * prn_dots)                       # этикетка в точках (203 dpi)
        tdots = _tspl_text_dots(base_fs)                    # кегль подписи в точках принтера
        # перенос широких строк: реальная ширина тем же шрифтом и кеглем
        avail_w = int(W * 0.96)
        lines = _wrap_lines(lines, avail_w)
        prepared = []           # (текст, строки-байты битмапа или None)
        for _t in lines:
            _r = _render_text_bitmap(_t, tdots + 2, W)
            if _r is None:
                # не влезла по ширине (или нет TTF) — принудительная резка посимвольно
                chunks = []
                rest2 = _t
                while rest2:
                    piece2 = rest2
                    while piece2 and _render_text_bitmap(piece2, tdots + 2, W) is None:
                        piece2 = piece2[:-1]
                    if not piece2:
                        piece2 = rest2[0]
                    chunks.append(piece2)
                    rest2 = rest2[len(piece2):]
                prepared.append((None, chunks))
                continue
            prepared.append((_t, _r))
        text_h = 0
        for _t, _r in prepared:
            text_h += (len(_r[0]) if isinstance(_r, tuple) else tdots + 2) + 6
        # тихая зона из 2 модулей уже встроена в матрицу (как в PDF-картинке),
        # поэтому код + поля = (n + 4) модулей по высоте
        avail = int(code_size * prn_dots) - text_h - 8
        mod = max(1, min(int((code_size - 2 * padding) * prn_dots) // (n + 4), avail // (n + 4)))
        bw = n * mod                                        # ширина кода в точках
        bpr = (bw + 7) // 8
        x0 = max(0, (W - bw - mod) // 2)
        y0 = max(0, int(code_size * prn_dots) - bw - text_h - 4)

        frame = bytearray()
        for s in (f'SIZE {code_size:g} mm,{code_size:g} mm', 'CLS', 'GAP 2 mm,0 mm',
                  'DENSITY 8', 'DIRECTION 0'):
            frame += (s + '\r\n').encode('ascii')
        # заголовок BITMAP заканчивается запятой — сразу после него идут байты
        # данных, БЕЗ перевода строки (иначе принтер сдвинет картинку)
        frame += f'BITMAP {x0},{y0},{bpr},{bw},0,'.encode('ascii')
        row = bytearray(bpr)
        for ry in range(n - 1, -1, -1):
            row = bytearray(bpr)
            for rx in range(n):
                if grid[ry][rx]:
                    bx0 = rx * mod
                    for dx in range(mod):
                        row[(bx0 + dx) // 8] |= 0x80 >> ((bx0 + dx) % 8)
            for _ in range(mod):
                frame += bytes(row)
        frame += b'\r\n'
        ty = y0 + bw + 6
        for _t, _r in prepared:
            if isinstance(_r, tuple):
                rows, gw, fw = _r
                bpr2 = fw // 8
                tx = max(0, (W - gw) // 2)
                frame += ('BITMAP %d,%d,%d,%d,0,' % (tx, ty, bpr2, len(rows))).encode('ascii')
                for row in rows:
                    frame += row
                frame += b'\r\n'
                ty += len(rows) + 6
            else:
                # чанки переполнившихся строк: рендерим каждый (уже влезает)
                for chunk in _r:
                    res2 = _render_text_bitmap(chunk, tdots + 2, W)
                    if res2 is not None:
                        rows, gw, fw = res2
                        bpr2 = fw // 8
                        tx = max(0, (W - gw) // 2)
                        frame += ('BITMAP %d,%d,%d,%d,0,' % (tx, ty, bpr2, len(rows))).encode('ascii')
                        for row in rows:
                            frame += row
                        frame += b'\r\n'
                        ty += len(rows) + 6
                    else:
                        enc_t = _tsl_text(chunk)
                        out_w = len(enc_t) * 12
                        frame += ('TEXT %d,%d,"2",0,1,1,"%s"\r\n' % (max(0, (W - out_w) // 2), ty, enc_t)).encode('cp1251', errors='replace')
                        ty += tdots + 6
        frame += b'PRINT 1,1\r\n'
        prn_file.write(frame)

    # --- Текст под кодом ----------------------------------------------------
    # Подпись "содержимое кода" выводится читаемо: AI в скобках, как у
    # производителей: (01)04640000000000(21)SER123(17)261031. Если в подписи
    # есть кириллица, в PRN она печатается картинкой (шрифт TSC её не знает).
    _AI_FIXED = {'00': 18, '01': 14, '02': 14, '11': 6, '12': 6, '13': 6,
                 '15': 6, '17': 6, '20': 2}

    def _ai_val(seg, pos, ln, vlen=None):
        """(ai, значение, новая позиция) или None."""
        ai = seg[pos:pos + ln]
        if len(ai) < ln or not ai.isdigit():
            return None
        if vlen is not None:
            val = seg[pos + ln:pos + ln + vlen]
            if len(val) != vlen:
                return None
            return ai, val, pos + ln + vlen
        nxt = seg.find('(', pos + ln)
        if nxt < 0:
            return ai, seg[pos + ln:], len(seg)
        return ai, seg[pos + ln:nxt], nxt

    def human_gs1(validated_line):
        """Содержимое КМ читаемым текстом: (01)046...(21)серия(17)261031.
        GS (\x1d) = конец переменной AI. AI ищутся по таблице длин."""
        _AI_FIXED = {'00': 18, '01': 14, '02': 14, '11': 6, '12': 6, '13': 6,
                     '15': 6, '17': 6, '20': 2}
        _AI_VAR = ('21', '22', '30', '37', '90', '91', '92', '93', '94', '95',
                   '96', '97', '98', '99')
        _AI_VAR3 = tuple(str(x) for x in range(310, 380))
        _AI_VAR4 = tuple(str(x) for x in range(400, 410)) + tuple(str(x) for x in range(420, 430))
        out = []
        pos = 0
        s = validated_line
        if s.startswith('('):
            s = re.sub(r'\((\d{2,4})\)', r'\1', s)
        while pos < len(s):
            if s[pos] == '\x1d':
                pos += 1
                continue
            matched = False
            for ln in (2, 3, 4):
                ai = s[pos:pos + ln]
                if len(ai) < ln or not ai.isdigit():
                    continue
                if ai in _AI_FIXED:
                    vlen = _AI_FIXED[ai]
                    val = s[pos + ln:pos + ln + vlen]
                    if len(val) == vlen:
                        out.append('(%s)%s' % (ai, val))
                        pos += ln + vlen
                        matched = True
                        break
                elif (ln == 2 and ai in _AI_VAR) or (ln == 3 and ai in _AI_VAR3) or (ln == 4 and ai in _AI_VAR4):
                    nxt = len(s)
                    g = s.find('\x1d', pos + ln)
                    if g >= 0:
                        nxt = g
                    out.append('(%s)%s' % (ai, s[pos + ln:nxt]))
                    pos = nxt
                    matched = True
                    break
            if not matched:
                # мусорный хвост — до следующего GS
                g = s.find('\x1d', pos)
                out.append(s[pos:g if g >= 0 else len(s)])
                pos = len(s) if g < 0 else g + 1
        # страховка: управляющие символы GS/FNC1 в подпись не попадают
        return ''.join(out).replace('\x1d', '').replace('\x00', '')

    def label_text_lines(validated_line, total_count):
        """Строки текста под кодом: подпись + порядковый номер, если заданы."""
        parts = []
        if code_text:
            parts.append(human_gs1(validated_line))
        if caption:
            parts.append(caption)
        if number_start is not None:
            parts.append(str(number_start + total_count))
        return parts

    # Предварительный подсчет непустых строк
    valid_lines = []
    with open(csv_path, mode='r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.strip():
                valid_lines.append(line)

    total_lines = len(valid_lines)
    if total_lines == 0:
        return 0, 0, output_dir

    for idx, line in enumerate(valid_lines):
        if c is None:
            start_num = total_count + 1
            end_num = min(total_count + max_pages, total_lines)
            
            current_pdf_name = os.path.join(output_dir, f"{pdf_prefix}_{start_num}-{end_num}.pdf")
            c = canvas.Canvas(current_pdf_name, pagesize=(page_size_pt, page_size_pt))
            current_file_pages = 0

        try:
            validated_line = clean_gs1_string(line)
            
            if force_gs1:
                final_string = FNC1 + validated_line
            else:
                final_string = validated_line

            encoder = DataMatrixEncoder(final_string)
            img_bytes = encoder.get_imagedata()
            img_reader = ImageReader(io.BytesIO(img_bytes))

            total_count += 1
            c.setPageSize((page_size_pt, page_size_pt))
            texts = label_text_lines(validated_line, total_count - 1)
            if texts:
                from reportlab.pdfbase import pdfmetrics as _pdfmetrics
                # перенос по той же функции, что и для принтера: ширина строки в
                # PDF-точках (1 pt = 1/72", точки принтера * 72/203)
                wrap_w = page_size_pt - 2 * padding_pt
                _wf = _wrap_font()
                # переносим в пикселях того же TTF-шрифта, которым мэрится PRN,
                # а порог в pt пересчитываем в пиксели (kegel pt -> px при 203dpi)
                if _wf is not None:
                    _px_per_pt = tdots_px / base_fs
                    draw_lines = _wrap_lines(texts, int(wrap_w * _px_per_pt))
                else:
                    draw_lines = _wrap_lines(texts, int(wrap_w))
                line_h = caption_font[1] * 1.25
                text_block_pt = len(draw_lines) * line_h + 1.0 * mm
                bc_size = min(barcode_size_pt, page_size_pt - 2 * padding_pt - text_block_pt)
                bc_y = padding_pt + text_block_pt
                c.drawImage(
                    img_reader, 
                    (page_size_pt - bc_size) / 2.0, 
                    bc_y, 
                    width=bc_size, 
                    height=bc_size
                )
                ty = padding_pt + 0.9 * mm
                for t in draw_lines:
                    c.setFont(caption_font[0], caption_font[1])
                    c.drawCentredString(page_size_pt / 2.0, ty, t)
                    ty += line_h
            else:
                c.drawImage(
                    img_reader, 
                    padding_pt, 
                    padding_pt, 
                    width=barcode_size_pt, 
                    height=barcode_size_pt
                )
            if prn_file and prn_native:
                # нативная команда принтера: DMATRIX строится прошивкой TSC,
                # FNC1 кодируется знаком ~ в начале, GS — как ~d01D
                # FNC1 в pystrich — объект кодового слова, в строке он может быть
                # вставлен как маркер; для DMATRIX его не дублируем — режим c126
                dm_raw = str(validated_line)
                x0n = int(padding * prn_dots)
                wn = max(8, int((code_size - 2 * padding) * prn_dots))
                Wn = int(code_size * prn_dots)
                # x-модуль: берём РЕАЛЬНУЮ сторону матрицы по тому же энкодеру,
                # что и в PDF (pystrich), иначе принтер подберёт сторону сам и
                # код может выйти за квадрат wn. Сторона = len(matrix) - 4
                # (pystrich рендерит с L-рамкой из 2 модулей с каждой стороны).
                try:
                    _n = len(DataMatrixEncoder(FNC1 + dm_raw).init_renderer().matrix) - 4
                    # GS1-режим c126 сжимает данные — сторона будет не больше;
                    # запас не нужен, но при отличии от ASCII-режима уточняем:
                except Exception:
                    _n = 26
                xm = max(1, wn // _n)
                bw_est = xm * _n
                cmd = 'DMATRIX %d,%d,%d,%d,c126,x%d,r0,"%s"' % (
                    x0n, x0n, wn, wn, xm, _tspl_dm_text(dm_raw))
                # подпись (содержимое кода): если включена — печатаем под кодом
                # в нижней полосе; кегль подбираем по реальной ширине текста,
                # при необходимости переносим по словам (1-2 строки).
                Hn = int(code_size * prn_dots)
                tlines = []
                tfs = 0.0
                if code_text:
                    _t = human_gs1(validated_line)
                    if any(ord(ch) > 126 for ch in _t):
                        _t = ''      # не-ASCII нативным шрифтом TSC не печатается
                    # font "2" квадратный 24x24 точки @203dpi (35 @300dpi).
                    # Подбор: симметричные множители (1,2,3...) по высоте; ширину
                    # строки при масштабе x считаем реальной метрикой * (sc*base/c).
                    _base_pt = 24.0 * 72.0 / (prn_dots * 25.4)   # кегль font2 = ~8.4pt@300
                    _avail_w = Wn - 2 * x0n
                    _marks = [k + 1 for k in range(len(_t) - 1) if _t[k:k + 2] == ')(']
                    for _sc in (1, 2, 3):
                        _lh = 24.0 * prn_dots / 8.0 * _sc + 3
                        _cap_w = _avail_w * 0.98
                        for _np in (0, 1, 2):
                            if _np == 0:
                                _ls = [_t]
                            else:
                                _idx = sorted(_marks, key=lambda k: abs(k - len(_t) // 2))[:_np]
                                if len(set(_idx)) < _np:
                                    continue
                                _idx = sorted(set(_idx))
                                _ls = []
                                _prev = 0
                                for _cut in _idx + [len(_t)]:
                                    _ls.append(_t[_prev:_cut])
                                    _prev = _cut
                            # ширина строки при масштабе sc (метрика в pt -> pt -> точки):
                            # реальная высота текста = 24dots*sc => множитель к метрике
                            _sc_pt = _sc * 24.0 * 72.0 / (prn_dots * 25.4)  # кегль при sc
                            _wmax = max(_text_dots_width(_l, _sc_pt, prn_dots) for _l in _ls)
                            okw = _wmax <= _cap_w
                            okh = len(_ls) * _lh <= Hn - bw_est - 4
                            if not tlines:
                                pass
                            if okw and okh:
                                tlines, tfs = _ls, _sc_pt
                                break
                        if tlines:
                            break
                fr = bytearray()
                for s in (f'SIZE {code_size:g} mm,{code_size:g} mm', 'GAP 2 mm,0 mm',
                          'CLS', 'DENSITY 8', 'DIRECTION 0'):
                    fr += (s + '\r\n').encode('ascii')
                fr += (cmd + '\r\n').encode('ascii')
                if tlines:
                    _base_pt = 24.0 * 72.0 / (prn_dots * 25.4)
                    _sc = max(1, int(round(tfs / _base_pt)))
                    # текст сверху: код центрирован, верхняя полоса = (Hn-bw_est)/2
                    
                    _lh = 24.0 * prn_dots / 8.0 * _sc + 3
                    ty = x0n
                    for _l in tlines:
                        _enc = _tsl_text(_l)
                        fr += ('TEXT %d,%d,"2",0,%d,%d,"%s"' % (
                            x0n, ty, _sc, _sc, _enc)).encode('cp1251', errors='replace')
                        fr += b'\r\n'
                        ty += int(_lh)
                fr += b'PRINT 1,1\r\n'

                prn_file.write(fr)
            elif prn_file:
                _plines = texts if texts else label_text_lines(validated_line, total_count - 1)
                write_prn_label(validated_line, _plines)
            c.showPage()
            
            current_file_pages += 1

            if total_count % 5 == 0 or total_count == total_lines:
                progress_callback(total_count, total_lines)

            if current_file_pages >= max_pages:
                c.save()
                c = None
                file_part += 1

        except Exception as e:
            print(f"Ошибка при обработке строки: {e}")

    if c is not None:
        c.save()
    else:
        file_part -= 1
    if prn_file:
        prn_file.close()
        
    return total_count, file_part, output_dir


if not NO_GUI:
    class AppMarkingGUI:
        def __init__(self, root):
            self.root = root
            self.root.title("Генератор DataMatrix (Честный Знак)")
            self.root.geometry("580x560")
            self.root.resizable(False, False)
        
            style = ttk.Style()
            style.theme_use('clam')
        
            self.csv_path_var = tk.StringVar()
            self.code_size_var = tk.DoubleVar(value=20.0)
            self.padding_var = tk.DoubleVar(value=1.5)
            self.max_pages_var = tk.IntVar(value=5000)
            self.gs1_mode_var = tk.BooleanVar(value=True)
            self.caption_var = tk.StringVar(value="")
            self.number_start_var = tk.StringVar(value="")
            self.prn_enabled_var = tk.BooleanVar(value=False)
            self.prn_native_var = tk.BooleanVar(value=True)
            self.prn_dpi_var = tk.DoubleVar(value=8.0)
            self.code_text_var = tk.BooleanVar(value=True)
            self.font_size_var = tk.DoubleVar(value=6.2)

            self.create_widgets()

        def create_widgets(self):
            # --- Выбор файла ---
            file_frame = ttk.LabelFrame(self.root, text=" Выбор данных ", padding=10)
            file_frame.pack(fill="x", padx=15, pady=10)
        
            ttk.Entry(file_frame, textvariable=self.csv_path_var, width=45).pack(side="left", padx=(0, 5))
            ttk.Button(file_frame, text="Обзор...", command=self.browse_file).pack(side="left")

            # --- Параметры ---
            params_frame = ttk.LabelFrame(self.root, text=" Настройки печати ", padding=10)
            params_frame.pack(fill="x", padx=15, pady=5)

            ttk.Label(params_frame, text="Размер этикетки (мм):").grid(row=0, column=0, sticky="w", pady=5)
            ttk.Entry(params_frame, textvariable=self.code_size_var, width=10).grid(row=0, column=1, sticky="w", padx=(5, 20))
        
            ttk.Label(params_frame, text="Размер полей (мм):").grid(row=0, column=2, sticky="w", pady=5)
            ttk.Entry(params_frame, textvariable=self.padding_var, width=10).grid(row=0, column=3, sticky="w", padx=5)

            ttk.Label(params_frame, text="Кодов в одном PDF:").grid(row=1, column=0, sticky="w", pady=5)
            ttk.Entry(params_frame, textvariable=self.max_pages_var, width=10).grid(row=1, column=1, sticky="w", padx=(5, 20))
        
            # Текстовая подсказка вместо ввода префикса вручную
            ttk.Label(params_frame, text="Префикс файла:", font=('Arial', 9, 'bold')).grid(row=1, column=2, sticky="w", pady=5)
            ttk.Label(params_frame, text="gtin_XXXXXXXXXXXXXX", foreground="gray").grid(row=1, column=3, sticky="w", padx=5)

            ttk.Checkbutton(params_frame, text="Принудительный GS1 режим (FNC1)", variable=self.gs1_mode_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
            ttk.Checkbutton(params_frame, text="PRN-файл для принтера TSC", variable=self.prn_enabled_var).grid(row=2, column=2, columnspan=2, sticky="w", pady=(10, 0))
            ttk.Checkbutton(params_frame, text="код командой DMATRIX (без текста)", variable=self.prn_native_var).grid(row=3, column=2, columnspan=2, sticky="w", pady=(2, 0))
            dpi_row = ttk.Frame(params_frame)
            dpi_row.grid(row=4, column=2, columnspan=2, sticky="w", pady=(4, 0))
            ttk.Label(dpi_row, text="Точек/мм PRN:").pack(side="left", padx=(0, 4))
            ttk.Spinbox(dpi_row, from_=4.0, to=24.0, increment=0.001, textvariable=self.prn_dpi_var, width=7).pack(side="left")
            ttk.Label(dpi_row, text="(8 = 203 dpi, 11.811 = 300 dpi)", foreground="gray").pack(side="left", padx=4)

            # --- Текст на этикетке ---
            text_frame = ttk.LabelFrame(self.root, text=" Текст на этикетке ", padding=10)
            text_frame.pack(fill="x", padx=15, pady=5)

            ttk.Label(text_frame, text="Своя подпись (текст):").grid(row=0, column=0, sticky="w", pady=5)
            ttk.Entry(text_frame, textvariable=self.caption_var, width=34).grid(row=0, column=1, columnspan=3, sticky="w", padx=5)

            ttk.Label(text_frame, text="Порядковый номер с:").grid(row=1, column=0, sticky="w", pady=5)
            ttk.Entry(text_frame, textvariable=self.number_start_var, width=10).grid(row=1, column=1, sticky="w", padx=5)
            ttk.Label(text_frame, text="пусто — без номеров", foreground="gray").grid(row=1, column=2, columnspan=2, sticky="w", padx=5)

            ttk.Checkbutton(text_frame, text="Подписывать код его содержимым  (01)…(21)…", variable=self.code_text_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
            ttk.Label(text_frame, text="Шрифт подписи (пт):").grid(row=3, column=0, sticky="w", pady=5)
            ttk.Spinbox(text_frame, from_=3.0, to=20.0, increment=0.5, textvariable=self.font_size_var, width=10).grid(row=3, column=1, sticky="w", padx=5)
            ttk.Label(text_frame, text="длинные строки переносятся автоматически", foreground="gray").grid(row=3, column=2, columnspan=2, sticky="w", padx=5)

            # --- Блок прогресса ---
            self.progress_frame = ttk.Frame(self.root, padding=5)
            self.progress_frame.pack(fill="x", padx=15, pady=(10, 0))
        
            self.lbl_status = ttk.Label(self.progress_frame, text="Готов к работе")
            self.lbl_status.pack(anchor="w")
        
            self.progress_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", mode="determinate")
            self.progress_bar.pack(fill="x", pady=5)

            # --- Кнопка запуска ---
            self.btn_start = ttk.Button(self.root, text="ГЕНЕРИРОВАТЬ", command=self.start_generation_thread, padding=10)
            self.btn_start.pack(fill="x", padx=15, pady=15)

        def browse_file(self):
            file_path = filedialog.askopenfilename(
                title="Выберите CSV файл с кодами маркировки",
                filetypes=[("CSV Files", "*.csv"), ("Text Files", "*.txt"), ("All Files", "*.*")]
            )
            if file_path:
                self.csv_path_var.set(file_path)

        def update_progress_ui(self, current, total):
            percent = (current / total) * 100
            self.progress_bar['value'] = percent
            self.lbl_status.config(text=f"Обработано: {current} из {total} кодов ({int(percent)}%)")
            self.root.update_idletasks()

        def start_generation_thread(self):
            csv_path = self.csv_path_var.get()
            if not csv_path:
                messagebox.showerror("Ошибка", "Пожалуйста, выберите CSV файл!")
                return

            self.btn_start.config(state="disabled")
            self.lbl_status.config(text="Анализ файла и поиск GTIN...")
            self.progress_bar['value'] = 0
        
            threading.Thread(target=self.async_worker, args=(csv_path,), daemon=True).start()

        def async_worker(self, csv_path):
            try:
                try:
                    number_start = int(self.number_start_var.get().strip()) if self.number_start_var.get().strip() else None
                except ValueError:
                    self.root.after(0, lambda: messagebox.showerror("Ошибка", "Порядковый номер должен быть целым числом."))
                    self.root.after(0, lambda: self.btn_start.config(state="normal"))
                    return
                caption = self.caption_var.get().strip() or None
                prn_dir = os.path.dirname(csv_path) if self.prn_enabled_var.get() else None
                code_text = bool(self.code_text_var.get())
                font_size = max(3.0, float(self.font_size_var.get()))

                total, parts, output_dir = run_generation(
                    csv_path=csv_path,
                    code_size=self.code_size_var.get(),
                    padding=self.padding_var.get(),
                    max_pages=self.max_pages_var.get(),
                    force_gs1=self.gs1_mode_var.get(),
                    progress_callback=self.update_progress_ui,
                    caption=caption,
                    number_start=number_start,
                    prn_dir=prn_dir,
                    code_text=code_text,
                    font_size=font_size,
                    prn_native=bool(self.prn_native_var.get()),
                    prn_dots=float(self.prn_dpi_var.get())
                )

                if total == 0:
                    self.root.after(0, lambda: messagebox.showwarning("Внимание", "Выбранный файл пуст."))
                    self.root.after(0, lambda: self.lbl_status.config(text="Файл пуст"))
                    return

                self.root.after(0, lambda: messagebox.showinfo(
                    "Успех", 
                    ("Генерация успешно завершена!\n\n"
                     f"Всего обработано кодов: {total}\n"
                     f"Создано PDF-файлов: {parts}\n"
                     + (f"PRN для принтера TSC сохранён рядом с CSV\n" if self.prn_enabled_var.get() else "")
                     + "\nПапка с файлами сейчас откроется автоматически.")
                ))
                self.root.after(0, lambda: self.lbl_status.config(text="Готово!"))
            
                            # Автоматическое открытие папки в Проводнике Windows
                if os.path.exists(output_dir):
                    subprocess.Popen(f'explorer "{os.path.normpath(output_dir)}"')

            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", f"Произошла ошибка:\n{str(e)}"))
                self.root.after(0, lambda: self.lbl_status.config(text="Ошибка выполнения"))
            finally:
                self.root.after(0, lambda: self.btn_start.config(state="normal"))


if __name__ == "__main__":
    if NO_GUI:
        import sys, os
        csv_path = sys.argv[1] if len(sys.argv) > 1 else input("Путь к CSV с кодами: ").strip('"')
        def _env_num(name, dflt):
            v = os.environ.get(name, "").strip()
            return type(dflt)(v) if v else dflt
        total, parts, out_dir = run_generation(
            csv_path=csv_path,
            code_size=float(os.environ.get("CODE_SIZE", "20.0")),
            padding=float(os.environ.get("PADDING", "1.5")),
            max_pages=int(os.environ.get("MAX_PAGES", "5000")),
            force_gs1=os.environ.get("FORCE_GS1", "1") != "0",
            progress_callback=lambda cur, tot: print("  %d/%d" % (cur, tot)),
            caption=os.environ.get("CAPTION", "").strip() or None,
            number_start=int(os.environ["NUMBER_START"]) if os.environ.get("NUMBER_START", "").strip() else None,
            prn_dir=os.environ.get("PRN_DIR", "").strip() or None,
            code_text=os.environ.get("CODE_TEXT", "1") != "0",
            font_size=_env_num("FONT_SIZE", 6.2),
            prn_native=os.environ.get("PRN_NATIVE", "1") != "0"
        )
        print("Готово: %d кодов, файлов: %d, папка: %s" % (total, parts, out_dir))
        raise SystemExit(0)
    try:
        root = tk.Tk()
        app = AppMarkingGUI(root)
        root.mainloop()
    except Exception as _e:
        # Если графическая среда недоступна — консольный режим (та же логика)
        print("Графический интерфейс недоступен (%s). Режим консоли." % _e)
        print("CSV первым аргументом или переменной окружения, параметры:")
        print("  CODE_SIZE=20 PADDING=1.5 MAX_PAGES=5000 FORCE_GS1=1")
        print("  CAPTION=TEXT NUMBER_START=1 PRN_DIR=out CODE_TEXT=0 FONT_SIZE=8 PRN_NATIVE=1")
        import sys
        csv_path = sys.argv[1] if len(sys.argv) > 1 else input("Путь к CSV с кодами: ").strip('"')
        def _env_num(name, dflt):
            v = os.environ.get(name, "").strip()
            return type(dflt)(v) if v else dflt
        total, parts, out_dir = run_generation(
            csv_path=csv_path,
            code_size=float(os.environ.get("CODE_SIZE", "20.0")),
            padding=float(os.environ.get("PADDING", "1.5")),
            max_pages=int(os.environ.get("MAX_PAGES", "5000")),
            force_gs1=os.environ.get("FORCE_GS1", "1") != "0",
            progress_callback=lambda cur, tot: print("  %d/%d" % (cur, tot)),
            caption=os.environ.get("CAPTION", "").strip() or None,
            number_start=int(os.environ["NUMBER_START"]) if os.environ.get("NUMBER_START", "").strip() else None,
            prn_dir=os.environ.get("PRN_DIR", "").strip() or None,
            code_text=os.environ.get("CODE_TEXT", "1") != "0",
            font_size=_env_num("FONT_SIZE", 6.2),
            prn_native=os.environ.get("PRN_NATIVE", "1") != "0"
        )
        print("Готово: %d кодов, файлов: %d, папка: %s" % (total, parts, out_dir))
