#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Печать этикеток DataMatrix (Честный ЗНАК) на принтер TSC.
Версия portable: самодостаточна, внешних библиотек не требует.

Способ подключения принтера настраивается полем «Принтер» (или PRINTER_FILE /
переменной окружения PRINTER):
  * имя общего доступа Windows            "TSC MH341"
  * путь общего доступа                   "\\\\server\\TSC MH341"
  * сетевой адрес IP[:порт]               "192.168.1.50" или "192.168.1.50:9100"

Разделителем AI 93 (криптохвост) в CSV является байт GS (0x1D). Запятая и
любые другие печатаемые символы могут находиться внутри серийника (AI 21) и
разделителями не считаются.
"""

import csv
import os
import re
import socket
import sys

# ==============================================================================
# БЛОК ЛОКАЛЬНОГО ПОДКЛЮЧЕНИЯ ПАПКИ ВСТРОЕННОГО PYTHON (ПЕРЕНОСИМОСТЬ БЕЗ PIP)
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_candidates = [
    os.path.join(BASE_DIR, "tk12_overlay"),
    os.path.join(BASE_DIR, "win-embed"),
    os.path.join(BASE_DIR, "..", "tk12_overlay"),
    os.path.join(BASE_DIR, "..", "win-embed"),
]

for _p in _candidates:
    _p = os.path.normpath(_p)
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
# ==============================================================================

# ==============================================================================
# ПРОВЕРКА TKINTER (встроенный Python без tkinter работает только консольно)
# ==============================================================================
NO_GUI = "--no-gui" in sys.argv or os.environ.get("NO_GUI") == "1"
tk = None
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError:
    NO_GUI = True

if NO_GUI and tk is None:
    # Консольный режим: печать всего файла или диапазона строк без окна
    CSV_FILE = os.environ.get("CSV_FILE") or (sys.argv[1] if len(sys.argv) > 1 else None)
    START_ROW = int(os.environ.get("START_ROW", "1"))
    END_ROW = int(os.environ.get("END_ROW", "1000000000"))
    LABEL_W = int(os.environ.get("LABEL_W", "15"))
    LABEL_H = int(os.environ.get("LABEL_H", "15"))
    DM_SIZE = int(os.environ.get("DM_SIZE", "11"))
    PRINTER = os.environ.get("PRINTER") or None  # "TSC MH341" или "192.168.1.50:9100"
    DRY_RUN = os.environ.get("DRY_RUN") == "1" or "--dry" in sys.argv
    MAKE_PRN = os.environ.get("MAKE_PRN") == "1" or "--prn" in sys.argv
    # Текст под кодом: TEXT_BLOCK — шаблон ('{N}' номер, '{КИЗ}' текст КИЗ);
    # TEXT_MODE=number|human включает '{N}'/'{КИЗ}' без задания шаблона.
    TEXT_BLOCK = os.environ.get("TEXT_BLOCK") or None
    if os.environ.get("TEXT_MODE") == "number":
        TEXT_BLOCK = "{N}"
    elif os.environ.get("TEXT_MODE") == "human":
        TEXT_BLOCK = "{КИЗ}"
    OUT_DIR = os.environ.get("OUT_DIR") or BASE_DIR
# ==============================================================================

# ==============================================================================
# НАСТРОЙКА ПРИНТЕРА (имя общего доступа ИЛИ сетевой адрес)
# ==============================================================================
DEFAULT_PRINTER_NAME = "TSC MH341"  # имя общего доступа Windows по умолчанию
DEFAULT_NET_PORT = 9100             # порт RAW-печати по умолчанию
PRINTER_FILE = os.environ.get("PRINTER_FILE") or os.path.join(BASE_DIR, "printer.txt")


def load_saved_printer():
    """Читает сохранённый адрес принтера из printer.txt рядом со скриптом."""
    try:
        with open(PRINTER_FILE, "r", encoding="utf-8-sig") as f:
            saved = f.readline().strip()
        if saved:
            return saved
    except OSError:
        pass
    return os.environ.get("PRINTER") or DEFAULT_PRINTER_NAME


def parse_printer_spec(spec):
    """Разбирает настройку принтера. Возвращает ('smb', путь) или ('tcp', host, port).

    Форматы:
      'TSC MH341'                      -> общий доступ \\\\localhost\\TSC MH341
      '\\\\server\\TSC MH341'             -> общий доступ как есть
      '192.168.1.50'                   -> TCP 9100
      '192.168.1.50:9100'              -> TCP с портом
      'printserver.local:6101'         -> TCP по имени хоста
    """
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("Не указан принтер! Укажите имя, путь или IP принтера.")

    # Сетевой путь Windows: \\сервер\имя
    if spec.startswith("\\\\"):
        parts = [p for p in spec.lstrip("\\").split("\\") if p]
        if len(parts) < 2:
            raise ValueError(
                f"Некорректный сетевой путь: {spec}\n"
                "Формат: \\\\сервер\\имя_принтера (например \\\\localhost\\TSC MH341)"
            )
        return ("smb", spec.rstrip("\\"))

    # Сетевой адрес host[:port] — IPv4 или DNS-имя с портом/точкой/дефисом
    m = re.fullmatch(
        r"(\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9][A-Za-z0-9._-]*)(?::(\d{1,5}))?", spec
    )
    if m and (":" in spec or "." in spec or re.fullmatch(r"\d+(\.\d+){3}", spec)):
        host = m.group(1)
        port = int(m.group(2)) if m.group(2) else DEFAULT_NET_PORT
        if not 1 <= port <= 65535:
            raise ValueError(f"Некорректный порт принтера: {port} (1..65535)")
        if re.fullmatch(r"\d+(\.\d+){3}", host) and any(int(o) > 255 for o in host.split(".")):
            raise ValueError(f"Некорректный IP-адрес принтера: {host}")
        return ("tcp", host, port)

    # Всё остальное — имя принтера в общем доступе Windows (буквы/цифры/пробелы)
    if re.fullmatch(r"[^\W_][^\W_ .\-]*( [^\W_ .\-]+)*", spec, re.UNICODE):
        return ("smb", f"\\\\localhost\\{spec}")

    raise ValueError(
        f"Не удалось распознать принтер: {spec}\n"
        "Форматы: 'TSC MH341' | '\\\\сервер\\имя' | '192.168.1.50' | '192.168.1.50:9100'"
    )
# ==============================================================================

# --- ГЛОБАЛЬНЫЕ КОНСТАНТЫ ПРИНТЕРА ---
DPI = 300  # Разрешение принтера TSC MH341
DOTS_PER_MM = 12  # 300 dpi / 25.4 мм ~ 12 точек на 1 мм

GS = "\x1d"  # байт-разделитель полей GS1 (в CSV разделяет AI 21 и AI 93)


def normalize_raw_code(raw_code):
    """Готовит строку из CSV для команды DMATRIX прошивки TSC.

    Рабочая схема (из проверенного на принтере gui_printer.py): все байты
    кода, включая разделитель GS (0x1D), передаются ВНУТРИ строки DMATRIX
    НАПРЯМУЮ — прошивка с CODEPAGE UTF-8 принимает их как есть и кодирует
    в матрице корректно. Никаких '~dNN'/'\\dNN' маркеров для GS не используется.
    Двойные кавычки экранируются как \" (экранирование делает escape_text_block).

    Разделителем криптохвоста AI 93 служит байт GS (0x1D) непосредственно
    перед '93'. Всё, что до него — GTIN (AI 01) и серийник (AI 21), где
    допустимы ЛЮБЫЕ печатаемые символы: запятая, точка, '+', '%', '~',
    двойная кавычка и прочие. Код НИКОГДА не разрезается по запятой.

    В начале payload всегда ставится '~1' — маркер GS1 (FNC1) содержимого.
    """
    s = raw_code.strip()

    # Текстовая запись GS в CSV ('\x1d', '\x01D') -> реальный байт GS
    s = re.sub(r"(?<![0-9A-Za-z])\\x0?1[dD]", GS, s)
    s = s.replace(" " + GS, GS).replace(GS + " ", GS)

    # Если в начале кода нет префикса группы GS1 (~1), добавляем его
    if not s.startswith("~1"):
        s = "~1" + s
    return s


def find_suspicious_codes(lines):
    """Строки с управляющими байтами вне разделителя GS (например переводы
    строк или табуляции внутри кода). Кавычка, '~' и прочие печатаемые
    символы передаются принтеру корректно и предупреждения не требуют."""
    bad = []
    for i, line in enumerate(lines, start=1):
        for pos, ch in enumerate(line, start=1):
            if ord(ch) < 32 and ch != GS:
                bad.append(
                    f"строка {i}, позиция {pos}: управляющий символ {ch!r} — "
                    f"в выгрузке ЧЗ его быть не должно, проверьте файл"
                )
    return bad


def human_gs1(code):
    """Текстовое представление КИЗ: печатаемые символы как есть, GS (0x1D)
    заменяется на читаемый маркер '<GS>' — ровно так, как возвращает сканер
    (zxing/промышленные сканеры ЧЗ)."""
    return code.replace(GS, "<GS>")


def resolve_text_block(template, label_number, raw_code, human_code):
    """Подставляет служебные плейсхолдеры в шаблон текста под кодом.

    {N}   — номер этикетки (с учётом стартового номера и диапазона печати)
    {КИЗ} — текстовое представление КИЗ, как его читает сканер
    {code} — сырая строка из CSV
    """
    if template is None:
        return None
    return (
        template.replace("{N}", str(label_number))
        .replace("{КИЗ}", human_code)
        .replace("{code}", raw_code.replace(GS, "␟"))
    )


TEXT_BLOCK_FONT = "ROMAN.TTF"      # встроенный шрифт принтера
TEXT_BLOCK_MULT = 2.5               # множитель размера шрифта (x и y одинаково)


def escape_text_block(content):
    """Экранирование содержимого строки TSPL (DMATRIX/BLOCK) — рабочая схема
    из gui_printer.py: двойная кавычка -> \", обратный слэш -> \\.
    Байт GS (0x1D) и прочие управляющие символы, кроме переводов строк,
    передаются внутри строки НАПРЯМУЮ. Переводы строк в тексте BLOCK
    заменяются пробелом, чтобы команда оставалась в одной строке пакета."""
    out = []
    for ch in content:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch in "\r\n":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def format_text_block(text, x, y, w, h, rotation=0, mult=TEXT_BLOCK_MULT,
                      space=None, align=1, fit=0):
    """BLOCK x,y,width,height,"font",rotation,x-mult,y-mult,[space,]align,fit,"content"

    align по спецификации принтера: 0 и 1 - по левому краю, 2 - по центру,
    3 - по правому. По умолчанию 1 (левый край).
    Множитель для TTF одинаковый по x и y, может быть дробным (2.5).
    """
    m = ("%g" % mult)
    if space is not None:
        tail = f"{m},{m},{space},{align},{fit}"
    else:
        tail = f"{m},{m},{align},{fit}"
    content = escape_text_block(text)
    line = (
        f"BLOCK {x},{y},{w},{h},\"{TEXT_BLOCK_FONT}\",{rotation},"
        f"{tail},\"{content}\""
    )
    return line


def format_tspl(raw_code, label_w, label_h, dmatrix_size,
                 text_block=None, label_number=1):
    """Формирует TSPL-пакет с кодом DataMatrix.

    Код печатается одной командой DMATRIX. Байт GS (0x1D) передаётся внутри
    строки DMATRIX напрямую (прошивка с CODEPAGE UTF-8 кодирует его в матрице
    корректно), двойные кавычки экранируются как \".
    """
    # Расчет геометрии в точках (dots) для 300 dpi
    total_width_dots = label_w * DOTS_PER_MM
    total_height_dots = label_h * DOTS_PER_MM
    # Высота текстового блока под кодом: ~= строка TTF при множителе 2.5
    text_block_dots = int(54) if text_block else 0
    # Матрица должна влезать в область над текстом; уменьшаем модуль, если нет
    avail_h0 = total_height_dots - text_block_dots
    xm0 = int(avail_h0 // 22)
    dmatrix_dots = min(dmatrix_size * DOTS_PER_MM, xm0 * 22)
    if dmatrix_dots < 22:
        dmatrix_dots = 22

    # Координаты для точного центрирования (код центрируется в области НАД
    # текстовым блоком, чтобы не наезжать на текст)
    avail_h = total_height_dots - text_block_dots
    x_pos = int((total_width_dots - dmatrix_dots) / 2)
    y_pos = int((avail_h - dmatrix_dots) / 2)

    if x_pos < 8:
        x_pos = 8
    if y_pos < 8:
        y_pos = 8

    # Размер модуля ячейки xm подбираем под желаемый размер кода:
    # сторона GS1-матрицы для ЧЗ-кода (78 символов) = 22 модуля, как в
    # рабочем эталоне пользователя (x5 при коде ~12 мм на 300 dpi)
    xm = max(1, int(dmatrix_dots // 22))

    # payload -> строка TSPL: кавычки -> \", остальные байты (включая GS)
    # уходят в принтер как есть — ровно как в рабочем gui_printer.py
    clean_string = escape_text_block(normalize_raw_code(raw_code))

    # Структура пакета по рабочей эталонной форме пользователя:
    #   SIZE 20 mm,20 mm / GAP 2 mm, 0 / CODEPAGE UTF-8 / CLS
    #   DMATRIX x,y,0,0,c126,x5,r0,"~1<код>" / [BLOCK ...] / PRINT 1,1
    # Размеры матрицы в эталоне '0,0' — прошивка сама подбирает сторону под
    # содержимое; модуль x<N> задаёт размер точки.
    if text_block:
        text_block = resolve_text_block(
            text_block, label_number, raw_code.strip(), human_gs1(raw_code)
        )
    block_cmd = ""
    if text_block:
        # Блок текста — в нижней части этикетки (код центрирован над ним),
        # по всей ширине. Многострочный (переносы \n в содержимом).
        bx = 8
        bw = max(16, total_width_dots - 16)
        by = max(y_pos + dmatrix_dots + 4, total_height_dots - text_block_dots)
        bh = max(14, total_height_dots - by - 4)
        block_cmd = format_text_block(text_block, bx, by, bw, bh) + "\r\n"

    tspl = f"""SIZE {label_w} mm,{label_h} mm
GAP 2 mm, 0
CODEPAGE UTF-8
CLS
DMATRIX {x_pos},{y_pos},0,0,c126,x{xm},r0,"{clean_string}"
{block_cmd}PRINT 1,1
"""
    return tspl


def send_to_printer(tspl_commands, printer_spec=None):
    """Отправляет TSPL-команды на принтер: общий доступ Windows (SMB) или TCP (RAW).

    Пакет нормализуется к терминаторам CRLF (как в рабочем gui_printer.py):
    часть прошивок TSC и серверов печати корректно разбирают команды только
    по '\r\n' — при '\n' строка может быть проглочена, и этикетка не печатается.
    """
    data = tspl_commands.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    kind, *target = parse_printer_spec(printer_spec or DEFAULT_PRINTER_NAME)

    if kind == "smb":
        network_printer_path = target[0]
        try:
            with open(network_printer_path, "wb") as printer:
                printer.write(data)
        except Exception as e:
            raise Exception(
                f"Принтер не ответил по пути: {network_printer_path}\n"
                f"Проверьте общий доступ к принтеру!\n"
                f"Ошибка системы: {e}"
            )
    else:
        host, port = target
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                sock.sendall(data)
        except Exception as e:
            raise Exception(
                f"Принтер не ответил по адресу: {host}:{port}\n"
                f"Проверьте IP-адрес принтера, порт RAW (обычно 9100) и доступ к сети!\n"
                f"Ошибка системы: {e}"
            )


def check_file_integrity(path, codes):
    """Возвращает список проблем целостности выгрузки (пусто = файл годен).

    Ловит два типовых повреждения после копирования/пересохранения:
      * потерянный служебный байт GS перед криптохвостом «93» — код печатается
        неверно, принтер может пропустить этикетку;
      * склейка двух КИЗ в одну строку (теряется перевод строки) — печатается
        обрезанная или пустая матрица;
      * расхождение числа непустых строк файла и распознанных кодов.
    """
    problems = []
    raw_count = sum(
        1 for raw in open(path, encoding="utf-8-sig", newline="")
        if raw.strip()
    )
    if raw_count != len(codes):
        problems.append(
            f"в файле {raw_count} непустых строк, а распознано кодов "
            f"{len(codes)}"
        )
    for i, c in enumerate(codes, start=1):
        if c.startswith("01") and len(c) > 30 and GS not in c:
            problems.append(f"строка {i}: не найден разделитель GS перед «93»")
        elif c.count(GS + "93") >= 2:
            problems.append(
                f"строка {i}: два криптохвоста «93» в одной строке — коды "
                "склеились (потерян перевод строки)"
            )
        elif c.count(GS) > 1:
            problems.append(f"строка {i}: лишний разделитель GS внутри кода")
        # длинноватый код: два КИЗ склеились в одну строку без GS — у корректного
        # кода ЧЗ максимальная длина 33 символа + криптохвост '93' (5) = 38
        elif len(c) > 42:
            problems.append(
                f"строка {i}: длина {len(c)} — похоже, два кода склеились "
                "в одну строку (корректный код ЧЗ не длиннее ~40 символов)"
            )
    return problems


def save_prn_packets(path, start_row, end_row, lbl_w, lbl_h, dm_s,
                     text_block=None, prn_path=None, progress_cb=None):
    """Сохраняет пакеты этикеток в ОДИН .prn-файл для анализа кода.

    Побайтовая копия того, что ушло бы на принтер (включая CRLF и байты GS),
    с текстовыми комментариями-разметкой (начинаются с '#'): принтер игнорирует
    мусор между командами TSPL, а человек видит каждую этикетку. Если файл
    .prn отправить на принтер напрямую — печатаются те же этикетки.

    Возвращает путь к .prn.
    """
    codes = read_code_lines(path)
    if not prn_path:
        base = os.path.splitext(os.path.basename(path))[0]
        prn_path = os.path.join(
            os.path.dirname(os.path.abspath(path)) or BASE_DIR,
            f"{base}_{start_row}-{end_row}.prn",
        )
    n = 0
    with open(prn_path, "wb") as pf:
        for current_index in range(start_row, min(end_row, len(codes)) + 1):
            code = codes[current_index - 1]
            tspl_packet = format_tspl(code, lbl_w, lbl_h, dm_s,
                                      text_block=text_block,
                                      label_number=current_index)
            # нормализация к CRLF — ровно как в send_to_printer
            data = tspl_packet.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")

            # комментарий строим из payload напрямую (без разбора строки
            # пакета: в payload есть реальный байт GS, а на нём Python
            # splitlines() резал бы строку). GS показываем как <GS>, байт
            # GS в hex-дампе = 1D, криптохвост '93' = 39 33.
            payload = escape_text_block(normalize_raw_code(code))
            def _hex(b):
                return " ".join(f"{x:02X}" for x in b)
            def _vis(b):
                # GS показываем как <GS>, реальные переводы строк (их в payload
                # быть не должно) — пробелом; остальные байты, включая '\',
                # остаются КАК ЕСТЬ для побайтовой сверки с пакетом
                return b.replace(b"\x1d", b"<GS>").replace(b"\r", b" ").replace(b"\n", b" ")
            code_b = code.encode("latin-1", "replace")
            payload_b = payload.encode("latin-1", "replace")
            comment = (
                ("# ── этикетка " + str(current_index) + " ──\r\n").encode("utf-8")
                + ("# код из CSV: ").encode("utf-8") + _vis(code_b) + b"\r\n"
                + b"#    hex: " + _hex(code_b).encode() + b"\r\n"
                + b"# payload DMATRIX: " + _vis(payload_b) + b"\r\n"
                + b"#    hex: " + _hex(payload_b).encode() + b"\r\n"
            )
            pf.write(comment + data)
            n += 1
            if progress_cb:
                progress_cb(current_index, n)
    return prn_path, n


def read_code_lines(path):
    """Читает CSV: список непустых кодов (нумерация строк = нумерация кодов).

    CSV читается с quoting=QUOTE_NONE, чтобы кавычки и GS внутри кода не
    меняли разбиение на строки: в выгрузке ЧЗ один код занимает ровно одну
    строку.
    """
    with open(path, mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, quoting=csv.QUOTE_NONE)
        codes = [row[0].strip() for row in reader if row and row[0].strip()]

    # Если в CSV GS записан текстом ('\x1d' / '\x01D'), а не байтом (ручная
    # выгрузка или блокнот), восстанавливаем реальный байт GS перед '93'.
    fixed = []
    for c in codes:
        if GS not in c:
            c = re.sub(r"(?<![0-9A-Za-z])\\x0?1[dD]", GS, c)
            if GS not in c and re.search(r"93[0-9A-Za-z]{4}$", c) and c.startswith("01"):
                # криптохвост '93' идёт последним; серийник ЧЗ = 13 символов
                # после '01'+14 цифр GTIN -> позиция GS фиксирована
                pos = 16 + 13
                if c[pos:pos + 2] == "93":
                    c = c[:pos] + GS + c[pos:]
        fixed.append(c)
    return fixed


def count_codes(path):
    return len(read_code_lines(path))


def print_range(path, start_row, end_row, lbl_w, lbl_h, dm_s, dry_run=False,
                out_dir=None, progress_cb=None, printer_spec=None,
                text_block=None):
    """Печатает строки [start_row..end_row] из CSV. Возвращает число отправленных
    этикеток. При dry_run пишет пакеты в .prn-файлы вместо принтера.
    text_block — необязательный текст (можно с переносами \n), печатается
    блоком BLOCK под кодом шрифтом ROMAN.TTF."""
    codes = read_code_lines(path)
    problems = check_file_integrity(path, codes)
    if problems:
        raise ValueError(
            "Проверьте целостность выгрузки — часть кодов повреждена "
            "(при копировании могли потеряться служебные символы GS или "
            "переводы строк):\n"
            + "\n".join(problems[:5])
            + ("\n..." if len(problems) > 5 else "")
        )
    printed_count = 0
    for current_index in range(start_row, min(end_row, len(codes)) + 1):
        code = codes[current_index - 1]
        # номер этикетки = строка в файле (с учётом смещения старта)
        tspl_packet = format_tspl(code, lbl_w, lbl_h, dm_s,
                                  text_block=text_block,
                                  label_number=current_index)
        if dry_run:
            out_name = os.path.join(
                out_dir or BASE_DIR, f"label_{current_index:06d}.prn"
            )
            with open(out_name, "wb") as pf:
                pf.write(tspl_packet.encode("utf-8"))
        else:
            send_to_printer(tspl_packet, printer_spec)
        printed_count += 1
        if progress_cb:
            progress_cb(current_index, printed_count)
    return printed_count


class PrinterApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Управление печатью TSC MH341")
        self.root.geometry("520x640")
        self.root.resizable(False, False)

        self.file_path = tk.StringVar()
        self.printer_spec = tk.StringVar(value=load_saved_printer())
        self.total_lines_in_file = 0

        # --- БЛОК 1: Выбор файла ---
        frame_file = tk.LabelFrame(root, text=" 1. Источник данных (CSV) ")
        frame_file.pack(fill="x", padx=15, pady=10, ipady=5)

        self.entry_file = tk.Entry(
            frame_file, textvariable=self.file_path, width=45
        )
        self.entry_file.config(state="readonly")
        self.entry_file.pack(side="left", padx=10, pady=10)

        btn_browse = tk.Button(
            frame_file, text="Обзор...", command=self.browse_file
        )
        btn_browse.pack(side="left", padx=5, pady=10)

        self.lbl_info = tk.Label(
            root, text="Кодов в файле: 0", fg="gray", font=("Arial", 9)
        )
        self.lbl_info.pack(anchor="w", padx=20, pady=0)

        # --- БЛОК 2: Настройка размеров ---
        frame_size = tk.LabelFrame(root, text=" 2. Параметры геометрии (мм) ")
        frame_size.pack(fill="x", padx=15, pady=10, ipady=5)

        tk.Label(frame_size, text="Ширина этикетки:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        self.spin_label_w = tk.Spinbox(frame_size, from_=10, to=100, width=5)
        self.spin_label_w.delete(0, "end")
        self.spin_label_w.insert(0, "15")
        self.spin_label_w.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(frame_size, text="Высота этикетки:").grid(
            row=0, column=2, sticky="w", padx=10, pady=5
        )
        self.spin_label_h = tk.Spinbox(frame_size, from_=10, to=100, width=5)
        self.spin_label_h.delete(0, "end")
        self.spin_label_h.insert(0, "15")
        self.spin_label_h.grid(row=0, column=3, padx=5, pady=5)

        tk.Label(frame_size, text="Размер DataMatrix:").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        self.spin_dm_size = tk.Spinbox(frame_size, from_=5, to=90, width=5)
        self.spin_dm_size.delete(0, "end")
        self.spin_dm_size.insert(0, "11")
        self.spin_dm_size.grid(row=1, column=1, padx=5, pady=5)

        tk.Label(
            frame_size,
            text="* Поля вычисляются автоматически",
            fg="darkblue",
            font=("Arial", 8, "italic"),
        ).grid(row=1, column=2, columnspan=2, sticky="w", padx=10, pady=5)

        # --- БЛОК 2.4: Текст под кодом (BLOCK) ---
        frame_text = tk.LabelFrame(root, text=" Текст под кодом ")
        frame_text.pack(fill="x", padx=15, pady=(0, 10), ipady=2)

        self.text_mode_var = tk.StringVar(value="none")
        mode_row = tk.Frame(frame_text)
        mode_row.pack(anchor="w", padx=10, pady=(6, 0))
        for txt, val in (
            ("Без текста", "none"),
            ("Номер этикетки", "number"),
            ("Текст КИЗ", "human"),
            ("Свой текст", "custom"),
        ):
            rb = tk.Radiobutton(
                mode_row, text=txt, value=val, variable=self.text_mode_var
            )
            rb.pack(side="left", padx=(0, 10))

        self.text_block_var = tk.StringVar(value="Этикетка {N}")
        self.ent_text_block = tk.Entry(frame_text, textvariable=self.text_block_var, width=45)
        self.ent_text_block.pack(side="left", padx=10, pady=(4, 2))

        tk.Label(
            frame_text.master,
            text="Режимы: номер этикетки — '{N}'; текст КИЗ — '{КИЗ}' (как читает "
                 "сканер, GS в скобках); свой текст — произвольная строка, доступны "
                 "плейсхолдеры {N} и {КИЗ}. Двойные кавычки экранируются автоматически",
            fg="gray",
            font=("Arial", 8),
            wraplength=470,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 4))

        # --- БЛОК 2.5: Принтер ---
        frame_printer = tk.LabelFrame(root, text=" Принтер ")
        frame_printer.pack(fill="x", padx=15, pady=(0, 10), ipady=5)

        self.ent_printer = tk.Entry(frame_printer, textvariable=self.printer_spec, width=45)
        self.ent_printer.pack(side="left", padx=10, pady=(8, 2))

        tk.Label(
            frame_printer.master,
            text="Имя общего доступа ('TSC MH341'), путь ('\\\\сервер\\имя') "
                 "или IP[:порт] ('192.168.1.50:9100', порт по умолчанию 9100)",
            fg="gray",
            font=("Arial", 8),
            wraplength=470,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 4))

        # --- БЛОК 3: Диапазон печати ---
        frame_range = tk.LabelFrame(root, text=" 3. Диапазон печати ")
        frame_range.pack(fill="x", padx=15, pady=10, ipady=5)

        tk.Label(frame_range, text="Печатать с строки №:").grid(
            row=0, column=0, sticky="w", padx=10, pady=10
        )
        self.ent_start = tk.Entry(frame_range, width=7)
        self.ent_start.insert(0, "1")
        self.ent_start.grid(row=0, column=1, padx=5, pady=10)

        tk.Label(frame_range, text="по строку №:").grid(
            row=0, column=2, sticky="w", padx=10, pady=10
        )
        self.ent_end = tk.Entry(frame_range, width=7)
        self.ent_end.insert(0, "1")
        self.ent_end.grid(row=0, column=3, padx=5, pady=10)

        # --- БЛОК 4: Кнопка запуска ---
        self.btn_print = tk.Button(
            root,
            text="ЗАПУСТИТЬ ПЕЧАТЬ",
            bg="#228B22",
            fg="white",
            font=("Arial", 11, "bold"),
            command=self.start_printing_process,
            height=2,
        )
        self.btn_print.pack(fill="x", padx=15, pady=(15, 4))

        btn_prn = tk.Button(
            root,
            text="Сохранить .PRN для анализа (без печати)",
            bg="#4a6fa5",
            fg="white",
            font=("Arial", 9),
            command=self.save_prn_process,
        )
        btn_prn.pack(fill="x", padx=15, pady=(0, 15))

    def save_prn_process(self):
        """Сохраняет пакеты выбранных этикеток в .prn — побайтовую копию того,
        что ушло бы на принтер, с комментариями (GS показан как <GS>)."""
        path = self.file_path.get()
        if not path or not os.path.exists(path):
            messagebox.showwarning("Внимание", "Пожалуйста, выберите файл CSV!")
            return
        try:
            lbl_w = int(self.spin_label_w.get())
            lbl_h = int(self.spin_label_h.get())
            dm_s = int(self.spin_dm_size.get())
            start_row = int(self.ent_start.get())
            end_row = int(self.ent_end.get())
            if start_row < 1 or end_row > self.total_lines_in_file or start_row > end_row:
                messagebox.showwarning(
                    "Ошибка диапазона",
                    f"Неверный диапазон строк! Доступно от 1 до {self.total_lines_in_file}.",
                )
                return
            prn_path, n = save_prn_packets(
                path, start_row, end_row, lbl_w, lbl_h, dm_s,
                text_block=self._compose_text_block(),
            )
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать PRN:\n{e}")
            return
        messagebox.showinfo(
            "PRN создан",
            f"Сохранено этикеток: {n}\n{prn_path}\n\n"
            "Файл — побайтовая копия пакетов для принтера (с CRLF и байтами GS)."
            " Служебные комментарии GS показываются как <GS>. Открывается "
            "шестнадцатеричным редактором или Notepad++ (View -> Show "
            "Symbol -> Show End of Line / All Characters).",
        )

    def browse_file(self):
        file_selected = filedialog.askopenfilename(
            filetypes=[("Таблицы CSV", "*.csv"), ("Все файлы", "*.*")]
        )
        if file_selected:
            self.file_path.set(file_selected)
            try:
                lines = read_code_lines(file_selected)
                self.total_lines_in_file = len(lines)
                # предупреждение о повреждениях — сразу при выборе файла
                problems = check_file_integrity(file_selected, lines)
                if problems:
                    shown = "\n".join(problems[:8])
                    more = f"\n... и ещё {len(problems) - 8}" if len(problems) > 8 else ""
                    self.lbl_info.config(
                        text=f"Кодов в файле: {len(lines)}  "
                             f"(проблем целостности: {len(problems)})",
                        fg="red"
                    )
                    messagebox.showwarning(
                        "Проверьте файл",
                        "В выгрузке найдены повреждения. Печать таких кодов "
                        "заблокирована — принтер напечатает пустую или битую "
                        f"этикетку:\n{shown}{more}\n\n"
                        "При копировании из почты/браузера/блокнота теряются "
                        "служебные символы GS и переводы строк. Возьмите файл "
                        "выгрузки ЧЗ как есть, без пересохранения "
                        "(кодировка UTF-8).",
                    )
                else:
                    self.lbl_info.config(
                        text=f"Кодов в файле: {len(lines)}", fg="green"
                    )
                self.ent_end.delete(0, "end")
                self.ent_end.insert(0, str(len(lines)))
                bad = find_suspicious_codes(lines)
                if bad:
                    shown = "\n".join(bad[:5])
                    more = f"\n... и ещё {len(bad) - 5}" if len(bad) > 5 else ""
                    messagebox.showwarning(
                        "Проверьте файл",
                        "В коде найдены управляющие символы, которых не "
                        "должно быть в выгрузке ЧЗ:\n"
                        f"{shown}{more}\n\n"
                        "Проверьте файл: возможно, он сохранён с искажением "
                        "кодировки.",
                    )
            except Exception as e:
                messagebox.showerror(
                    "Ошибка чтения", f"Не удалось проанализировать файл:\n{e}"
                )

    def _compose_text_block(self):
        """Текст под кодом по выбранному режиму (None = без текста)."""
        mode = self.text_mode_var.get()
        if mode == "none":
            return None
        if mode == "number":
            return "{N}"
        if mode == "human":
            return "{КИЗ}"
        tpl = self.text_block_var.get().strip()
        return tpl or None

    def start_printing_process(self):
        path = self.file_path.get()
        if not path or not os.path.exists(path):
            messagebox.showwarning("Внимание", "Пожалуйста, выберите файл CSV!")
            return

        try:
            lbl_w = int(self.spin_label_w.get())
            lbl_h = int(self.spin_label_h.get())
            dm_s = int(self.spin_dm_size.get())
            start_row = int(self.ent_start.get())
            end_row = int(self.ent_end.get())
            parse_printer_spec(self.printer_spec.get())

            if dm_s >= lbl_w or dm_s >= lbl_h:
                messagebox.showwarning(
                    "Ошибка размеров",
                    "Размер DataMatrix должен быть меньше размера этикетки!",
                )
                return

            if (
                start_row < 1
                or end_row > self.total_lines_in_file
                or start_row > end_row
            ):
                messagebox.showwarning(
                    "Ошибка диапазона",
                    f"Неверный диапазон строк! Доступно от 1 до {self.total_lines_in_file}.",
                )
                return

        except ValueError as e:
            msg = str(e)
            if msg and ("принтер" in msg.lower() or "адрес" in msg.lower()
                        or "порт" in msg.lower() or "формат" in msg.lower()):
                messagebox.showerror("Ошибка принтера", msg)
            else:
                messagebox.showerror(
                    "Ошибка ввода",
                    "Все числовые параметры должны быть целыми числами!",
                )
            return

        try:
            # Запоминаем настройку принтера для следующих запусков
            try:
                with open(PRINTER_FILE, "w", encoding="utf-8") as pf:
                    pf.write(self.printer_spec.get().strip() + "\n")
            except OSError:
                pass  # папка только для чтения — не мешаем печати

            printed_count = print_range(
                path, start_row, end_row, lbl_w, lbl_h, dm_s,
                printer_spec=self.printer_spec.get(),
                text_block=self._compose_text_block(),
            )
            messagebox.showinfo(
                "Успех",
                f"Печать завершена!\nУспешно отправлено этикеток: {printed_count}"
            )

        except Exception as e:
            messagebox.showerror(
                "Ошибка печати",
                f"Произошел сбой при отправке на принтер:\n{e}"
            )


def run_console():
    """Консольный режим для встроенного Python без tkinter (NO_GUI=1 или --no-gui)."""
    if not CSV_FILE or not os.path.exists(CSV_FILE):
        print("Ошибка: укажите CSV-файл: python gui_printer_port.py --no-gui <файл.csv>")
        print("или переменную окружения CSV_FILE. Параметры: START_ROW, END_ROW,")
        print("LABEL_W, LABEL_H, DM_SIZE, PRINTER, TEXT_BLOCK (текст под кодом),")
        print("DRY_RUN=1 (пакеты в .prn), OUT_DIR.")
        sys.exit(2)
    total = count_codes(CSV_FILE)
    end = min(END_ROW, total)
    if START_ROW < 1 or START_ROW > end:
        print(f"Ошибка: неверный диапазон. Доступно строк: {total}.")
        sys.exit(2)
    print(f"Кодов в файле: {total}. Печать строк {START_ROW}..{end}")
    printer = load_saved_printer() if not PRINTER else PRINTER
    try:
        parse_printer_spec(printer)
    except ValueError as e:
        print(f"Ошибка: {e}")
        sys.exit(2)
    print(f"Принтер: {printer}")
    with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
        lines = [row[0].strip() for row in csv.reader(f, quoting=csv.QUOTE_NONE)
                 if row and row[0].strip()]
    for warn in find_suspicious_codes(lines)[:5]:
        print(f"ВНИМАНИЕ: {warn}")
    if DRY_RUN:
        os.makedirs(OUT_DIR, exist_ok=True)
    if TEXT_BLOCK:
        print(f"Текст под кодом: {TEXT_BLOCK}")
    if MAKE_PRN:
        prn_path, n = save_prn_packets(
            CSV_FILE, START_ROW, end, LABEL_W, LABEL_H, DM_SIZE,
            text_block=TEXT_BLOCK,
            progress_cb=lambda i, c: print(f"  строка {i} -> этикетка {c}"),
        )
        print(f"Готово. PRN: {prn_path} (этикеток: {n})")
        return
    n = print_range(CSV_FILE, START_ROW, end, LABEL_W, LABEL_H, DM_SIZE,
                    dry_run=DRY_RUN, out_dir=OUT_DIR, printer_spec=printer,
                    text_block=TEXT_BLOCK,
                    progress_cb=lambda i, c: print(f"  строка {i} -> этикетка {c}"))
    print(f"Готово. Отправлено этикеток: {n}" + (" (DRY_RUN: файлы .prn в " + OUT_DIR + ")" if DRY_RUN else ""))


# Точка входа для запуска графического интерфейса
if __name__ == "__main__":
    if NO_GUI:
        run_console()
    else:
        window = tk.Tk()
        app = PrinterApp(window)
        window.mainloop()
