import os, sys, json, re, subprocess, time, tempfile, shutil, threading
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6 import sip

MUMU_BIN = ""  # путь к MuMuManager.exe: определяется при старте (find_mumu_manager) и запоминается в config.json
CREATE_NO_WINDOW = 0x08000000  # без этого флага при каждом вызове MuMuManager.exe мигало бы консольное окно

def _open_mumu_hidden():
    # Аналог macOS "open -g -a": поднимаем главное приложение MuMuPlayer (MuMuNxMain.exe) свёрнутым, без кражи фокуса.
    try:
        if is_mumu_process_alive(): return
        exe = os.path.join(os.path.dirname(MUMU_BIN), "MuMuNxMain.exe")
        if not os.path.isfile(exe): return
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 7  # SW_SHOWMINNOACTIVE
        subprocess.Popen([exe], startupinfo=si, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, cwd=os.path.dirname(exe))
    except Exception: pass

def find_mumu_manager(saved=""):
    cands = [os.environ.get("MUMU_MANAGER", ""), saved]
    subdirs = [r"Netease\MuMuPlayer\nx_main", r"Netease\MuMuPlayer-12.0\shell", r"Netease\MuMu\nx_main", r"Netease\MuMuPlayerGlobal-12.0\shell", r"Netease\MuMuPlayerGlobal\nx_main"]
    roots = [os.environ.get(v, "") for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    for d in "CDEFG": roots += [d + ":\\Program Files", d + ":\\Program Files (x86)", d + ":\\"]
    for r in roots:
        for sd in subdirs:
            r and cands.append(os.path.join(r, sd, "MuMuManager.exe"))
    cands.append(shutil.which("MuMuManager.exe") or "")
    return next((os.path.normpath(c) for c in cands if c and os.path.isfile(c)), "")

def get_config_path():
    p = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MuMu Launcher")
    os.makedirs(p, exist_ok=True)
    return os.path.join(p, "config.json")
CONFIG_PATH, REALTIME_POLL_MS, LAUNCH_PENDING_TIMEOUT = get_config_path(), 500, 12
MUMU_BOOT_WAIT_TIMEOUT = 90  # сек: сколько максимум ждать полного поднятия MuMuPlayer перед отменой очереди запуска
LAUNCH_STAGGER_SEC = 0.5     # сек: пауза между запусками профилей (и после полной готовности MuMu перед первым запуском)
OPEN_VERIFY_AFTER = 20        # сек: если после "холодного" запуска профиль так и не стал running - шлём open повторно
OPEN_MAX_RETRIES = 2         # сколько повторных open максимум
KILL_GUARD_SEC = 15          # сек: после Stop следим, не поднимется ли профиль из уже отправленного open, и гасим повторно
DEFAULT_STICKERS = ["∙", "⚡", "💸", "🔥", "💎", "⚠️", "❓", "🐸", "🍔", "🍓", "💩", "☑️", "🗯️", "👍", "❤️", "😂", "👀", "🎯"]
SEP_ROLE = Qt.ItemDataRole.UserRole + 1  # флаг "это служебный разделитель, а не профиль" на QListWidgetItem
NOTE_COLORS = ["#FFD60A", "#FF9F0A", "#30D158", "#3B82F6","#00838F", "#BF5AF2", "#FF453A", "#AC8E68", "#8E8E93"]
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

def get_scroll_css(t="dark"):
    h, hh = ("rgba(0,0,0,0.18)", "rgba(0,0,0,0.35)") if t == "light" else ("rgba(255,255,255,0.2)", "rgba(255,255,255,0.4)")
    return f"QScrollBar:vertical{{border:none;background:transparent;width:10px;margin:2px 2px 2px 0;}}QScrollBar::handle:vertical{{background:{h};min-height:20px;border-radius:4px;}}QScrollBar::handle:vertical:hover{{background:{hh};}}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;background:none;}}QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:transparent;}}QScrollBar:horizontal{{border:none;background:transparent;height:10px;margin:0 2px 2px 2px;}}QScrollBar::handle:horizontal{{background:{h};min-width:20px;border-radius:4px;}}QScrollBar::handle:horizontal:hover{{background:{hh};}}QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;background:none;}}QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{{background:transparent;}}"

def get_menu_css(t="dark"):
    bg, border, color = ("#FFFFFF", "#E5E5EA", "#1C1C1E") if t == "light" else ("#28282C", "#3A3A3C", "#EEEEEE")
    return f"QMenu{{background-color:{bg};border:1px solid {border};border-radius:12px;padding:6px;}}QMenu::item{{background-color:transparent;border-radius:8px;padding:6px 12px;color:{color};font-size:12px;font-weight:500;margin:1px 0;}}QMenu::item:selected{{background-color:#0A84FF;color:#FFF;}}QMenu::item:disabled{{color:#666666;}}QMenu::separator{{height:1px;background:{border};margin:4px 6px;}}"+get_scroll_css(t)

def get_menu_toggle_css(t="dark"):
    color, hover_bg, active_bg = ("#1C1C1E", "rgba(0,0,0,0.06)", "rgba(10,132,255,0.15)") if t == "light" else ("#EEEEEE", "rgba(255,255,255,0.08)", "rgba(10,132,255,0.22)")
    return f"QPushButton{{background-color:transparent;border:none;border-radius:8px;padding:6px 12px;color:{color};font-size:12px;font-weight:500;text-align:left;margin:1px 0;}}QPushButton:hover{{background-color:{hover_bg};}}QPushButton:checked{{background-color:{active_bg};}}"

def get_btn_style(t="dark", sel=False):
    if sel: return "QPushButton{background:#0A84FF;border:1px solid #0A84FF;color:#FFF;border-radius:8px;font-size:15px;}QPushButton:hover{background:#2292FF;border:1px solid #4DA8FF;}"
    return "QPushButton{background:#E5E5EA;border:1px solid #D1D1D6;color:#1C1C1E;border-radius:8px;font-size:15px;}QPushButton:hover{background:#D8D8DC;border-color:#B0B0B5;}" if t == "light" else "QPushButton{background:#2E2E2E;border:1px solid #3A3A3A;color:#FFF;border-radius:8px;font-size:15px;}QPushButton:hover{background:#383838;border-color:#55555A;}"

def get_checkbox_css(t="dark"):
    if t == "light":
        return (
            "QPushButton{background:#FFFFFF;border:1.5px solid #C7C7CC;border-radius:8px;color:transparent;font-size:11px;font-weight:bold;padding:0;margin:0;}"
            "QPushButton:hover{background:#F2F2F7;border-color:#A2A2A7;}"
            "QPushButton:checked{background:#8E8E93;border-color:#8E8E93;color:#FFFFFF;}"
            "QPushButton:checked:hover{background:#6C6C70;border-color:#6C6C70;}"
        )
    return (
        "QPushButton{background:#1C1C1E;border:1.5px solid #3A3A3C;border-radius:8px;color:transparent;font-size:11px;font-weight:bold;padding:0;margin:0;}"
        "QPushButton:hover{background:#2C2C2E;border-color:#48484A;}"
        "QPushButton:checked{background:#636366;border-color:#636366;color:#FFFFFF;}"
        "QPushButton:checked:hover{background:#48484A;border-color:#48484A;}"
    )

def get_dlg_css(t="dark"):
    return ("QDialog{background:#F6F6F9;color:#1C1C1E;border-radius:10px;}QLineEdit{background:#FFF;border:1px solid #D1D1D6;border-radius:8px;padding:6px;color:#1C1C1E;}QLineEdit:focus{border-color:#0A84FF;}QPushButton{background:#E5E5EA;border:1px solid #D1D1D6;border-radius:8px;color:#1C1C1E;padding:5px;}QPushButton:hover{background:#D8D8DC;border-color:#B0B0B5;}QPushButton:disabled{background:#F2F2F7;color:#A1A1A6;border-color:#E5E5EA;}" if t == "light" else "QDialog{background:#1E1E1E;color:#FFF;border-radius:10px;}QLineEdit{background:#262626;border:1px solid #333;border-radius:8px;padding:6px;color:#FFF;}QLineEdit:focus{border-color:#0A84FF;}QPushButton{background:#2C2C2C;border:1px solid #3A3A3A;border-radius:8px;color:#FFF;padding:5px;}QPushButton:hover{background:#3A3A3A;border-color:#55555A;}QPushButton:disabled{background:#1A1A1A;color:#555;border-color:#2A2A2A;}") + get_scroll_css(t)

SORT_OPTIONS = [{"key":"sort_name_asc","icon":""},{"key":"sort_name_desc","icon":""},{"key":"sort_id_asc","icon":""},{"key":"sort_id_desc","icon":""}]
TR = {
 "ru":{"profile_label":"ПРОФИЛЬ","sort_running_first":"Всегда сначала запущенные","sort_name_asc":"Имя (А → Я)","sort_name_desc":"Имя (Я → А)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Поиск (по имени, ID, заметке)...","btn_stop_all":"Закрыть все","settings_tooltip":"Настройки","settings_title":"Настройки","always_on_top":"Поверх всех","theme_label":"Тема","theme_dark":"Тёмная","theme_light":"Светлая","language_label":"Язык","sticker_settings_btn":"Настройки стикеров ▾","reset_btn":"Сброс ▾","close_btn":"Сохранить","reset_all":"Сбросить все стикеры","reset_except":"Сбросить все кроме...","reset_specific":"Сбросить конкретные...","reset_notes":"Сбросить все заметки","sticker_mgr_title":"Настройки стикеров","sticker_mgr_placeholder":"Новый символ...","sticker_mgr_add":"Добавить","sticker_mgr_delete":"Удалить","sticker_mgr_save":"Сохранить","sticker_mgr_badge":"📌 Основной стикер по умолчанию","tt_first":"В начало списка (сделать основным)","tt_left":"Назад на одну позицию","tt_right":"Вперёд на одну позицию","tt_last":"В конец списка","confirm":"Подтвердить","title_except":"Сбросить все, кроме...","title_specific":"Сбросить конкретные...","notes_label":"ЗАМЕТКИ","stickers_label":"СТИКЕРЫ","note_placeholder":"Напишите заметку...\n(Shift+Enter для переноса)","note_saved":"Сохранено ✓","note_tooltip_prefix":"📜Заметка: ","confirm_reset_stickers_title":"Сбросить все стикеры?","confirm_reset_stickers_text":"Все стикеры на всех профилях будут сброшены к значению по умолчанию.\nЭто действие нельзя отменить.","confirm_reset_notes_title":"Удалить все заметки?","confirm_reset_notes_text":"Все заметки на всех профилях будут удалены.\nЭто действие нельзя отменить.","btn_cancel":"Назад","btn_confirm_delete":"Подтвердить","language_search_placeholder":"🔍 Поиск языка...","no_stickers_selected":"Ни на одном девайсе не выбран стикер","nothing_selected":"Нигде не выбрано","empty_reset_stickers":"Нет установленных стикеров для сброса.\nВсе девайсы уже используют стикер по умолчанию.","empty_reset_notes":"Нет заметок для удаления.\nНи на одном девайсе нет сохраненных записей.","edit_config":"Изменить конфиг","clone_profile":"Клон","delete_profile":"Удалить","confirm_delete_profile_title":"Удалить профиль?","confirm_delete_profile_text":"Вы уверены, что хотите удалить {name}?\nЭто действие нельзя отменить.","select_all_btn":"Отметить все","deselect_all_btn":"Снять отметки","selected_label":"Отмечено: {n}","start_selected_tooltip":"Запустить отмеченные","stop_selected_tooltip":"Остановить отмеченные","config_editor_title":"Конфигурация девайса ID: ","invalid_json":"Ошибка: невалидный JSON!","bulk_config_btn":"Изменить конфиг всех профилей","bulk_config_title":"Конфигурация всех профилей","bulk_config_hint":"Вставьте нужный отрезок конфига с любого профиля — он применится сразу ко всем профилям.","bulk_config_placeholder":"Просто вставьте нужный отрезок конфига с нужного профиля и вставьте сюда. Он применится сразу на всех профилях! Например:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Применить конфиг ко всем профилям?","bulk_config_confirm_text":"Указанные параметры будут применены сразу к {n} профилям.\nВнимание: все запущенные устройства будут автоматически выключены перед изменением конфига.","bulk_config_empty":"Добавьте хотя бы один параметр конфигурации.","bulk_config_result_ok":"Готово! Конфиг применён к {n} профилям ✓","bulk_config_result_partial":"Применено: {ok}, с ошибкой: {fail}","single_config_confirm_title":"Сохранить изменения?","single_config_confirm_text":"Для применения новой конфигурации запущенное устройство будет автоматически выключено.\nПродолжить?","confirm_clone_profile_title":"Клонировать профиль?","confirm_clone_profile_text":"Устройство сейчас запущено. Для клонирования оно будет автоматически выключено.\nПродолжить?","add_device_tooltip":"Создать устройство","create_tablet":"Планшет 2560 × 1440","create_phone":"Телефон 1440 × 2560","creating_device":"Создание устройства...","create_device_error":"Ошибка создания устройства","empty_no_profiles":"Профилей нету, добавьте первый :)","sep_running":"ВКЛ","sep_all":"ВСЕ","sep_running_search":"ВКЛ (ПОИСК)","sep_search":"ПОИСК","empty_mumu_not_running":"MuMuPlayer не запущен"},
 "uk":{"profile_label":"ПРОФІЛЬ","sort_running_first":"Спочатку запущені","sort_name_asc":"Ім'я (А → Я)","sort_name_desc":"Ім'я (Я → А)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Пошук (за ім'ям, ID, нотаткою)...","btn_stop_all":"Закрити всі","settings_tooltip":"Налаштування","settings_title":"Налаштування","always_on_top":"Поверх усіх","theme_label":"Тема","theme_dark":"Темна","theme_light":"Світла","language_label":"Мова","sticker_settings_btn":"Налаштування стікерів ▾","reset_btn":"Скинути ▾","close_btn":"Зберегти","reset_all":"Скинути всі стікери","reset_except":"Скинути всі крім...","reset_specific":"Скинути конкретні...","reset_notes":"Скинути всі нотатки","sticker_mgr_title":"Налаштування стікерів","sticker_mgr_placeholder":"Новий символ...","sticker_mgr_add":"Додати","sticker_mgr_delete":"Видалити","sticker_mgr_save":"Зберегти","sticker_mgr_badge":"📌 Основний стікер за замовчуванням","tt_first":"На початок списку (зробити основним)","tt_left":"Назад на одну позицію","tt_right":"Вперед на одну позицію","tt_last":"У кінець списку","confirm":"Підтвердити","title_except":"Скинути всі, крім...","title_specific":"Скинути конкретні...","notes_label":"НОТАТКИ","stickers_label":"СТІКЕРИ","note_placeholder":"Напишіть нотатку...\n(Shift+Enter для переносу)","note_saved":"Збережено ✓","note_tooltip_prefix":"📜Нотатка: ","confirm_reset_stickers_title":"Скинути всі стікери?","confirm_reset_stickers_text":"Усі стікери на всіх профілях буде скинуто до значення за замовчуванням.\nЦю дію не можна скасувати.","confirm_reset_notes_title":"Видалити всі нотатки?","confirm_reset_notes_text":"Усі нотатки на всіх профілях буде видалено.\nЦю дію не можна скасувати.","btn_cancel":"Назад","btn_confirm_delete":"Підтвердити","language_search_placeholder":"🔍 Пошук мови...","no_stickers_selected":"Ні на одному девайсі не вибрано стікер","nothing_selected":"Ніде не вибрано","empty_reset_stickers":"Немає встановлених стікерів для скидання.\nУсі девайси вже використовують стікер за замовчуванням.","empty_reset_notes":"Немає нотаток для видалення.\nНі на одному девайсі немає збережених записів.","edit_config":"Змінити конфіг","clone_profile":"Клон","delete_profile":"Видалити","confirm_delete_profile_title":"Видалити профіль?","confirm_delete_profile_text":"Ви впевнені, що хочете видалити {name}?\nЦю дію не можна скасувати.","select_all_btn":"Позначити всі","deselect_all_btn":"Зняти позначки","selected_label":"Позначено: {n}","start_selected_tooltip":"Запустити позначені","stop_selected_tooltip":"Зупинити позначені","config_editor_title":"Конфігурація девайса ID: ","invalid_json":"Помилка: невалідний JSON!","bulk_config_btn":"Змінити конфіг усіх профілів","bulk_config_title":"Конфігурація всіх профілів","bulk_config_hint":"Вставте потрібний відрізок конфігу з будь-якого профілю — він застосується одразу до всіх профілів.","bulk_config_placeholder":"Просто вставте потрібний відрізок конфігу з потрібного профілю і вставте сюди. Він застосується одразу на всіх профілях! Наприклад:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Застосувати конфіг до всіх профілів?","bulk_config_confirm_text":"Вказані параметри буде застосовано одразу до {n} профілів.\nУвага: всі запущені пристрої будуть автоматично вимкнені перед зміною конфігу.","bulk_config_empty":"Додайте хоча б один параметр конфігурації.","bulk_config_result_ok":"Готово! Конфіг застосовано до {n} профілів ✓","bulk_config_result_partial":"Застосовано: {ok}, з помилкою: {fail}","single_config_confirm_title":"Зберегти зміни?","single_config_confirm_text":"Для застосування нової конфігурації запущений пристрій буде автоматично вимкнено.\nПродовжити?","confirm_clone_profile_title":"Клонувати профіль?","confirm_clone_profile_text":"Пристрій зараз запущено. Для клонування його буде автоматично вимкнено.\nПродовжити?","add_device_tooltip":"Створити пристрій","create_tablet":"Планшет 2560 × 1440","create_phone":"Телефон 1440 × 2560","creating_device":"Створення пристрою...","create_device_error":"Помилка створення пристрою","empty_no_profiles":"Профілів немає, додайте перший :)","sep_running":"УВІМК.","sep_all":"УСІ","sep_running_search":"УВІМК. (ПОШУК)","sep_search":"ПОШУК","empty_mumu_not_running":"MuMuPlayer не запущено"},
 "en":{"profile_label":"PROFILE","sort_running_first":"Running first","sort_name_asc":"Name (A → Z)","sort_name_desc":"Name (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Search (by name, ID, note)...","btn_stop_all":"Close all","settings_tooltip":"Settings","settings_title":"Settings","always_on_top":"Always on top","theme_label":"Theme","theme_dark":"Dark","theme_light":"Light","language_label":"Language","sticker_settings_btn":"Sticker settings ▾","reset_btn":"Reset ▾","close_btn":"Save","reset_all":"Reset all stickers","reset_except":"Reset all except...","reset_specific":"Reset specific...","reset_notes":"Reset all notes","sticker_mgr_title":"Sticker settings","sticker_mgr_placeholder":"New symbol...","sticker_mgr_add":"Add","sticker_mgr_delete":"Delete","sticker_mgr_save":"Save","sticker_mgr_badge":"📌 Main default sticker","tt_first":"To top of list (make main)","tt_left":"Back one position","tt_right":"Forward one position","tt_last":"To end of list","confirm":"Confirm","title_except":"Reset all except...","title_specific":"Reset specific...","notes_label":"NOTES","stickers_label":"STICKERS","note_placeholder":"Write a note...\n(Shift+Enter for newline)","note_saved":"Saved ✓","note_tooltip_prefix":"📜Note: ","confirm_reset_stickers_title":"Reset all stickers?","confirm_reset_stickers_text":"All stickers on all profiles will be reset to default.\nThis action cannot be undone.","confirm_reset_notes_title":"Delete all notes?","confirm_reset_notes_text":"All notes on all profiles will be deleted.\nThis action cannot be undone.","btn_cancel":"Back","btn_confirm_delete":"Confirm","language_search_placeholder":"🔍 Search language...","no_stickers_selected":"No sticker selected on any device","nothing_selected":"Nothing selected","empty_reset_stickers":"No set stickers to reset.\nAll devices are already using the default sticker.","empty_reset_notes":"No notes to delete.\nNo saved records on any device.","edit_config":"Edit config","clone_profile":"Clone","delete_profile":"Delete","confirm_delete_profile_title":"Delete profile?","confirm_delete_profile_text":"Are you sure you want to delete {name}?\nThis action cannot be undone.","select_all_btn":"Select all","deselect_all_btn":"Deselect all","selected_label":"Selected: {n}","start_selected_tooltip":"Start selected","stop_selected_tooltip":"Stop selected","config_editor_title":"Device config ID: ","invalid_json":"Error: Invalid JSON!","bulk_config_btn":"Edit config of all profiles","bulk_config_title":"All profiles configuration","bulk_config_hint":"Paste the needed config snippet from any profile — it will be applied to all profiles at once.","bulk_config_placeholder":"Just paste the needed config snippet from the desired profile and paste here. It will apply immediately to all profiles! For example:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Apply config to all profiles?","bulk_config_confirm_text":"The specified parameters will be applied to {n} profiles at once.\nWarning: All running devices will be automatically turned off before changing the config.","bulk_config_empty":"Add at least one config parameter.","bulk_config_result_ok":"Done! Config applied to {n} profiles ✓","bulk_config_result_partial":"Applied: {ok}, with error: {fail}","single_config_confirm_title":"Save changes?","single_config_confirm_text":"To apply the new configuration, the running device will be automatically turned off.\nContinue?","confirm_clone_profile_title":"Clone profile?","confirm_clone_profile_text":"Device is currently running. It will be automatically turned off for cloning.\nContinue?","add_device_tooltip":"Create device","create_tablet":"Tablet 2560 × 1440","create_phone":"Phone 1440 × 2560","creating_device":"Creating device...","create_device_error":"Device creation error","empty_no_profiles":"No profiles yet, add the first one :)","sep_running":"ON","sep_all":"ALL","sep_running_search":"ON (SEARCH)","sep_search":"SEARCH","empty_mumu_not_running":"MuMuPlayer is not running"},
 "es":{"profile_label":"PERFIL","sort_running_first":"Primero los ejecutándose","sort_name_asc":"Nombre (A → Z)","sort_name_desc":"Nombre (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Buscar (por nombre, ID, nota)...","btn_stop_all":"Cerrar todo","settings_tooltip":"Ajustes","settings_title":"Ajustes","always_on_top":"Encima de todos","theme_label":"Tema","theme_dark":"Oscuro","theme_light":"Claro","language_label":"Idioma","sticker_settings_btn":"Ajustes de stickers ▾","reset_btn":"Restablecer ▾","close_btn":"Guardar","reset_all":"Restablecer todos los stickers","reset_except":"Restablecer todos excepto...","reset_specific":"Restablecer específicos...","reset_notes":"Restablecer todas las notas","sticker_mgr_title":"Ajustes de stickers","sticker_mgr_placeholder":"Nuevo símbolo...","sticker_mgr_add":"Añadir","sticker_mgr_delete":"Eliminar","sticker_mgr_save":"Guardar","sticker_mgr_badge":"📌 Sticker principal por defecto","tt_first":"Al inicio de la lista (hacer principal)","tt_left":"Atrás una posición","tt_right":"Adelante una posición","tt_last":"Al final de la lista","confirm":"Confirmar","title_except":"Restablecer todos, excepto...","title_specific":"Restablecer específicos...","notes_label":"NOTAS","stickers_label":"STICKERS","note_placeholder":"Escribe una nota...\n(Shift+Enter para salto de línea)","note_saved":"Guardado ✓","note_tooltip_prefix":"📜Nota: ","confirm_reset_stickers_title":"¿Restablecer todos los stickers?","confirm_reset_stickers_text":"Todos los stickers en todos los perfiles se restablecerán al valor por defecto.\nEsta acción no se puede deshacer.","confirm_reset_notes_title":"¿Eliminar todas las notas?","confirm_reset_notes_text":"Todas las notas en todos los perfiles se eliminarán.\nEsta acción no se puede deshacer.","btn_cancel":"Atrás","btn_confirm_delete":"Confirmar","language_search_placeholder":"🔍 Buscar idioma...","no_stickers_selected":"Ningún dispositivo tiene sticker seleccionado","nothing_selected":"Nada seleccionado","empty_reset_stickers":"No hay stickers establecidos para restablecer.\nTodos los dispositivos ya usan el sticker por defecto.","empty_reset_notes":"No hay notas para eliminar.\nNingún dispositivo tiene registros guardados.","edit_config":"Cambiar config","clone_profile":"Clon","delete_profile":"Eliminar","confirm_delete_profile_title":"¿Eliminar perfil?","confirm_delete_profile_text":"¿Estás seguro de que quieres eliminar {name}?\nEsta acción no se puede deshacer.","select_all_btn":"Marcar todo","deselect_all_btn":"Desmarcar todo","selected_label":"Marcados: {n}","start_selected_tooltip":"Iniciar marcados","stop_selected_tooltip":"Detener marcados","config_editor_title":"Configuración del dispositivo ID: ","invalid_json":"¡Error: JSON no válido!","bulk_config_btn":"Cambiar config de todos los perfiles","bulk_config_title":"Configuración de todos los perfiles","bulk_config_hint":"Pega el fragmento de config de cualquier perfil — se aplicará inmediatamente a todos los perfiles.","bulk_config_placeholder":"Simplemente pega el fragmento de config del perfil deseado y pégalo aquí. ¡Se aplicará inmediatamente a todos los perfiles! Por ejemplo:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"¿Aplicar config a todos los perfiles?","bulk_config_confirm_text":"Los parámetros indicados se aplicarán de inmediato a {n} perfiles.\nAtención: todos los dispositivos en ejecución se apagarán automáticamente antes de cambiar la config.","bulk_config_empty":"Añade al menos un parámetro de configuración.","bulk_config_result_ok":"¡Listo! Config aplicada a {n} perfiles ✓","bulk_config_result_partial":"Aplicado: {ok}, con error: {fail}","single_config_confirm_title":"¿Guardar cambios?","single_config_confirm_text":"Para aplicar la nueva configuración, el dispositivo en ejecución se apagará automáticamente.\n¿Continuar?","confirm_clone_profile_title":"¿Clonar perfil?","confirm_clone_profile_text":"El dispositivo está actualmente en ejecución. Se apagará automáticamente para clonarlo.\n¿Continuar?","add_device_tooltip":"Crear dispositivo","create_tablet":"Tablet 2560 × 1440","create_phone":"Teléfono 1440 × 2560","creating_device":"Creando dispositivo...","create_device_error":"Error al crear el dispositivo","empty_no_profiles":"No hay perfiles, añade el primero :)","sep_running":"ACTIVO","sep_all":"TODOS","sep_running_search":"ACTIVO (BÚSQUEDA)","sep_search":"BÚSQUEDA","empty_mumu_not_running":"MuMuPlayer no está en ejecución"},
 "de":{"profile_label":"PROFIL","sort_running_first":"Laufende zuerst","sort_name_asc":"Name (A → Z)","sort_name_desc":"Name (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Suche (nach Name, ID, Notiz)...","btn_stop_all":"Alle schließen","settings_tooltip":"Einstellungen","settings_title":"Einstellungen","always_on_top":"Immer im Vordergrund","theme_label":"Design","theme_dark":"Dunkel","theme_light":"Hell","language_label":"Sprache","sticker_settings_btn":"Sticker-Einstellungen ▾","reset_btn":"Zurücksetzen ▾","close_btn":"Speichern","reset_all":"Alle Sticker zurücksetzen","reset_except":"Alle zurücksetzen außer...","reset_specific":"Bestimmte zurücksetzen...","reset_notes":"Alle Notizen zurücksetzen","sticker_mgr_title":"Sticker-Einstellungen","sticker_mgr_placeholder":"Neues Symbol...","sticker_mgr_add":"Hinzufügen","sticker_mgr_delete":"Löschen","sticker_mgr_save":"Speichern","sticker_mgr_badge":"📌 Haupt-Standard-Sticker","tt_first":"An den Anfang der Liste (als Haupt-Sticker)","tt_left":"Eine Position zurück","tt_right":"Eine Position vor","tt_last":"Ans Ende der Liste","confirm":"Bestätigen","title_except":"Alle zurücksetzen, außer...","title_specific":"Bestimmte zurücksetzen...","notes_label":"NOTIZEN","stickers_label":"STICKER","note_placeholder":"Notiz schreiben...\n(Shift+Enter für Zeilenumbruch)","note_saved":"Gespeichert ✓","note_tooltip_prefix":"📜Notiz: ","confirm_reset_stickers_title":"Alle Sticker zurücksetzen?","confirm_reset_stickers_text":"Alle Sticker auf allen Profilen werden auf den Standardwert zurückgesetzt.\nDiese Aktion kann nicht rückgängig gemacht werden.","confirm_reset_notes_title":"Alle Notizen löschen?","confirm_reset_notes_text":"Alle Notizen auf allen Profilen werden gelöscht.\nDiese Aktion kann nicht rückgängig gemacht werden.","btn_cancel":"Zurück","btn_confirm_delete":"Bestätigen","language_search_placeholder":"🔍 Sprache suchen...","no_stickers_selected":"Auf keinem Gerät ist ein Sticker ausgewählt","nothing_selected":"Nichts ausgewählt","empty_reset_stickers":"Keine gesetzten Sticker zum Zurücksetzen.\nAlle Geräte verwenden bereits den Standard-Sticker.","empty_reset_notes":"Keine Notizen zum Löschen.\nAuf keinem Gerät sind gespeicherte Einträge vorhanden.","edit_config":"Konfig ändern","clone_profile":"Klon","delete_profile":"Löschen","confirm_delete_profile_title":"Profil löschen?","confirm_delete_profile_text":"Sind Sie sicher, dass Sie {name} löschen möchten?\nDiese Aktion kann nicht rückgängig gemacht werden.","select_all_btn":"Alle markieren","deselect_all_btn":"Markierungen aufheben","selected_label":"Markiert: {n}","start_selected_tooltip":"Markierte starten","stop_selected_tooltip":"Markierte stoppen","config_editor_title":"Gerätekonfiguration ID: ","invalid_json":"Fehler: Ungültiges JSON!","bulk_config_btn":"Konfig aller Profile ändern","bulk_config_title":"Konfiguration aller Profile","bulk_config_hint":"Fügen Sie den benötigten Konfigurationsausschnitt aus einem beliebigen Profil ein — er wird sofort auf alle Profile angewendet.","bulk_config_placeholder":"Fügen Sie einfach den benötigten Konfig-Ausschnitt vom gewünschten Profil hier ein. Er wird sofort auf alle Profile angewendet! Zum Beispiel:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Konfig auf alle Profile anwenden?","bulk_config_confirm_text":"Die angegebenen Parameter werden sofort auf {n} Profile angewendet.\nAchtung: Alle laufenden Geräte werden vor der Konfig-Änderung automatisch ausgeschaltet.","bulk_config_empty":"Fügen Sie mindestens einen Konfigurationsparameter hinzu.","bulk_config_result_ok":"Fertig! Konfig auf {n} Profile angewendet ✓","bulk_config_result_partial":"Angewendet: {ok}, mit Fehler: {fail}","single_config_confirm_title":"Änderungen speichern?","single_config_confirm_text":"Um die neue Konfiguration anzuwenden, wird das laufende Gerät automatisch ausgeschaltet.\nFortfahren?","confirm_clone_profile_title":"Profil klonen?","confirm_clone_profile_text":"Das Gerät läuft derzeit. Es wird automatisch ausgeschaltet, um es zu klonen.\nFortfahren?","add_device_tooltip":"Gerät erstellen","create_tablet":"Tablet 2560 × 1440","create_phone":"Telefon 1440 × 2560","creating_device":"Gerät wird erstellt...","create_device_error":"Fehler beim Erstellen des Geräts","empty_no_profiles":"Keine Profile vorhanden, füge das erste hinzu :)","sep_running":"AN","sep_all":"ALLE","sep_running_search":"AN (SUCHE)","sep_search":"SUCHE","empty_mumu_not_running":"MuMuPlayer läuft nicht"},
 "zh":{"profile_label":"配置","sort_running_first":"已启动优先","sort_name_asc":"名称 (A → Z)","sort_name_desc":"名称 (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 搜索（名称、ID、备注）...","btn_stop_all":"关闭全部","settings_tooltip":"设置","settings_title":"设置","always_on_top":"窗口置顶","theme_label":"主题","theme_dark":"深色","theme_light":"浅色","language_label":"语言","sticker_settings_btn":"贴纸设置 ▾","reset_btn":"重置 ▾","close_btn":"保存","reset_all":"重置所有贴纸","reset_except":"重置所有除了...","reset_specific":"重置指定...","reset_notes":"重置所有备注","sticker_mgr_title":"贴纸设置","sticker_mgr_placeholder":"新符号...","sticker_mgr_add":"添加","sticker_mgr_delete":"删除","sticker_mgr_save":"保存","sticker_mgr_badge":"📌 默认主贴纸","tt_first":"移至顶部（设为主贴纸）","tt_left":"向左移动一位","tt_right":"向右移动一位","tt_last":"移至末尾","confirm":"确认","title_except":"重置所有，除了...","title_specific":"重置指定...","notes_label":"备注","stickers_label":"贴纸","note_placeholder":"撰写备注...\n(Shift+Enter 换行)","note_saved":"已保存 ✓","note_tooltip_prefix":"📜备注: ","confirm_reset_stickers_title":"重置所有贴纸？","confirm_reset_stickers_text":"所有配置文件上的贴纸都将重置为默认值。\n此操作无法撤销。","confirm_reset_notes_title":"删除所有备注？","confirm_reset_notes_text":"所有配置文件上的备注都将被删除。\n此操作无法撤销。","btn_cancel":"返回","btn_confirm_delete":"确认","language_search_placeholder":"🔍 搜索语言...","no_stickers_selected":"未在任何设备上选择贴纸","nothing_selected":"未选择任何内容","empty_reset_stickers":"没有可重置的设置贴纸。\n所有设备已在使用默认贴纸。","empty_reset_notes":"没有要删除的备注。\n任何设备上都没有保存的记录。","edit_config":"修改配置","clone_profile":"克隆","delete_profile":"删除","confirm_delete_profile_title":"删除配置文件？","confirm_delete_profile_text":"确定要删除 {name} 吗？\n此操作无法撤销。","select_all_btn":"全选","deselect_all_btn":"取消全选","selected_label":"已选择: {n}","start_selected_tooltip":"启动已选","stop_selected_tooltip":"停止已选","config_editor_title":"设备配置 ID: ","invalid_json":"错误：无效的 JSON！","bulk_config_btn":"修改所有配置文件","bulk_config_title":"所有配置文件设置","bulk_config_hint":"从任何配置文件粘贴所需的配置片段 — 它将立即应用于所有配置文件。","bulk_config_placeholder":"只需从所需的配置文件中复制配置片段并粘贴到此处。它将立即应用于所有配置文件！例如：\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"应用配置到所有配置文件？","bulk_config_confirm_text":"指定参数将立即应用于 {n} 个配置文件。\n注意：在更改配置之前，所有正在运行的设备将自动关闭。","bulk_config_empty":"请至少添加一个配置参数。","bulk_config_result_ok":"完成！配置已应用于 {n} 个配置文件 ✓","bulk_config_result_partial":"已应用: {ok}，失败: {fail}","single_config_confirm_title":"保存更改？","single_config_confirm_text":"为了应用新配置，正在运行的设备将自动关闭。\n是否继续？","confirm_clone_profile_title":"克隆配置文件？","confirm_clone_profile_text":"设备当前正在运行。克隆前将自动关闭。\n是否继续？","add_device_tooltip":"创建设备","create_tablet":"平板 2560 × 1440","create_phone":"手机 1440 × 2560","creating_device":"正在创建设备...","create_device_error":"创建设备失败","empty_no_profiles":"暂无配置文件，请添加第一个 :)","sep_running":"已启动","sep_all":"全部","sep_running_search":"已启动（搜索）","sep_search":"搜索","empty_mumu_not_running":"MuMuPlayer 未运行"},
 "fr":{"profile_label":"PROFIL","sort_running_first":"En cours d'exécution d'abord","sort_name_asc":"Nom (A → Z)","sort_name_desc":"Nom (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Rechercher (nom, ID, note)...","btn_stop_all":"Fermer tout","settings_tooltip":"Paramètres","settings_title":"Paramètres","always_on_top":"Toujours au-dessus","theme_label":"Thème","theme_dark":"Sombre","theme_light":"Clair","language_label":"Langue","sticker_settings_btn":"Paramètres des stickers ▾","reset_btn":"Réinitialiser ▾","close_btn":"Enregistrer","reset_all":"Réinitialiser tous les stickers","reset_except":"Réinitialiser tout sauf...","reset_specific":"Réinitialiser les spécifiques...","reset_notes":"Réinitialiser toutes les notes","sticker_mgr_title":"Paramètres des stickers","sticker_mgr_placeholder":"Nouveau symbole...","sticker_mgr_add":"Ajouter","sticker_mgr_delete":"Supprimer","sticker_mgr_save":"Enregistrer","sticker_mgr_badge":"📌 Sticker principal par défaut","tt_first":"En haut de la liste (définir comme principal)","tt_left":"Reculer d'une position","tt_right":"Avancer d'une position","tt_last":"À la fin de la liste","confirm":"Confirmer","title_except":"Réinitialiser tout, sauf...","title_specific":"Réinitialiser les spécifiques...","notes_label":"NOTES","stickers_label":"STICKERS","note_placeholder":"Écrire une note...\n(Shift+Entrée pour saut de ligne)","note_saved":"Enregistré ✓","note_tooltip_prefix":"📜Note : ","confirm_reset_stickers_title":"Réinitialiser tous les stickers ?","confirm_reset_stickers_text":"Tous les stickers de tous les profils seront réinitialisés à la valeur par défaut.\nCette action est irréversible.","confirm_reset_notes_title":"Supprimer toutes les notes ?","confirm_reset_notes_text":"Toutes les notes de tous les profils seront supprimées.\nCette action est irréversible.","btn_cancel":"Retour","btn_confirm_delete":"Confirmer","language_search_placeholder":"🔍 Rechercher une langue...","no_stickers_selected":"Aucun sticker sélectionné sur aucun appareil","nothing_selected":"Rien n'est sélectionné","empty_reset_stickers":"Aucun sticker défini à réinitialiser.\nTous les appareils utilisent déjà le sticker par défaut.","empty_reset_notes":"Aucune note à supprimer.\nAucun enregistrement sauvegardé sur aucun appareil.","edit_config":"Modifier la config","clone_profile":"Cloner","delete_profile":"Supprimer","confirm_delete_profile_title":"Supprimer le profil ?","confirm_delete_profile_text":"Êtes-vous sûr de vouloir supprimer {name} ?\nCette action est irréversible.","select_all_btn":"Tout sélectionner","deselect_all_btn":"Tout désélectionner","selected_label":"Sélectionnés : {n}","start_selected_tooltip":"Démarrer la sélection","stop_selected_tooltip":"Arrêter la sélection","config_editor_title":"Configuration de l'appareil ID : ","invalid_json":"Erreur : JSON non valide !","bulk_config_btn":"Modifier la config de tous les profils","bulk_config_title":"Configuration de tous les profils","bulk_config_hint":"Collez l'extrait de config de n'importe quel profil — il sera appliqué immédiatement à tous les profils.","bulk_config_placeholder":"Collez simplement l'extrait de config du profil souhaité ici. Il s'appliquera immédiatement à tous les profils ! Par exemple :\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Appliquer la config à tous les profils ?","bulk_config_confirm_text":"Les paramètres spécifiés seront appliqués immédiatement à {n} profils.\nAttention : tous les appareils en cours d'exécution seront automatiquement éteints avant de modifier la config.","bulk_config_empty":"Ajoutez au moins un paramètre de configuration.","bulk_config_result_ok":"Terminé ! Config appliquée à {n} profils ✓","bulk_config_result_partial":"Appliqué : {ok}, avec erreur : {fail}","single_config_confirm_title":"Enregistrer les modifications ?","single_config_confirm_text":"Pour appliquer la nouvelle configuration, l'appareil en cours d'exécution sera automatiquement éteint.\nContinuer ?","confirm_clone_profile_title":"Cloner le profil ?","confirm_clone_profile_text":"L'appareil est actuellement en cours d'exécution. Il sera automatiquement éteint pour le clonage.\nContinuer ?","add_device_tooltip":"Créer un appareil","create_tablet":"Tablette 2560 × 1440","create_phone":"Téléphone 1440 × 2560","creating_device":"Création de l'appareil...","create_device_error":"Erreur lors de la création de l'appareil","empty_no_profiles":"Aucun profil, ajoutez le premier :)","sep_running":"ACTIF","sep_all":"TOUS","sep_running_search":"ACTIF (RECHERCHE)","sep_search":"RECHERCHE","empty_mumu_not_running":"MuMuPlayer n'est pas démarré"},
 "it":{"profile_label":"PROFILO","sort_running_first":"Prima quelli in esecuzione","sort_name_asc":"Nome (A → Z)","sort_name_desc":"Nome (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Cerca (per nome, ID, nota)...","btn_stop_all":"Chiudi tutti","settings_tooltip":"Impostazioni","settings_title":"Impostazioni","always_on_top":"Sempre in primo piano","theme_label":"Tema","theme_dark":"Scuro","theme_light":"Chiaro","language_label":"Lingua","sticker_settings_btn":"Impostazioni sticker ▾","reset_btn":"Ripristina ▾","close_btn":"Salva","reset_all":"Ripristina tutti gli sticker","reset_except":"Ripristina tutti tranne...","reset_specific":"Ripristina specifici...","reset_notes":"Ripristina tutte le note","sticker_mgr_title":"Impostazioni sticker","sticker_mgr_placeholder":"Nuovo simbolo...","sticker_mgr_add":"Aggiungi","sticker_mgr_delete":"Elimina","sticker_mgr_save":"Salva","sticker_mgr_badge":"📌 Sticker principale predefinito","tt_first":"All'inizio della lista (imposta come principale)","tt_left":"Indietro di una posizione","tt_right":"Avanti di una posizione","tt_last":"Alla fine della lista","confirm":"Conferma","title_except":"Ripristina tutti, tranne...","title_specific":"Ripristina specifici...","notes_label":"NOTE","stickers_label":"STICKER","note_placeholder":"Scrivi una nota...\n(Shift+Invio per nuova riga)","note_saved":"Salvato ✓","note_tooltip_prefix":"📜Nota: ","confirm_reset_stickers_title":"Ripristinare tutti gli sticker?","confirm_reset_stickers_text":"Tutti gli sticker su tutti i profili verranno ripristinati al valore predefinito.\nQuesta azione non può essere annullata.","confirm_reset_notes_title":"Eliminare tutte le note?","confirm_reset_notes_text":"Tutte le note su tutti i profili verranno eliminate.\nQuesta azione non può essere annullata.","btn_cancel":"Indietro","btn_confirm_delete":"Conferma","language_search_placeholder":"🔍 Cerca lingua...","no_stickers_selected":"Nessun dispositivo ha uno sticker selezionato","nothing_selected":"Niente di selezionato","empty_reset_stickers":"Nessuno sticker impostato da ripristinare.\nTutti i dispositivi usano già lo sticker predefinito.","empty_reset_notes":"Nessuna nota da eliminare.\nNessun registro salvato su alcun dispositivo.","edit_config":"Modifica config","clone_profile":"Clona","delete_profile":"Elimina","confirm_delete_profile_title":"Eliminare il profilo?","confirm_delete_profile_text":"Sei sicuro di voler eliminare {name}?\nQuesta azione non può essere annullata.","select_all_btn":"Seleziona tutti","deselect_all_btn":"Deseleziona tutti","selected_label":"Selezionati: {n}","start_selected_tooltip":"Avvia selezionati","stop_selected_tooltip":"Arresta selezionati","config_editor_title":"Configurazione dispositivo ID: ","invalid_json":"Errore: JSON non valido!","bulk_config_btn":"Modifica config di tutti i profili","bulk_config_title":"Configurazione di tutti i profili","bulk_config_hint":"Incolla lo snippet di config da qualsiasi profilo — verrà applicato immediatamente a tutti i profili.","bulk_config_placeholder":"Incolla semplicemente lo snippet di config dal profilo desiderato qui. Verrà applicato immediatamente a tutti i profili! Ad esempio:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Applicare la config a tutti i profili?","bulk_config_confirm_text":"I parametri specificati verranno applicati immediatamente a {n} profili.\nAttenzione: tutti i dispositivi in esecuzione verranno automaticamente spenti prima di modificare la config.","bulk_config_empty":"Aggiungi almeno un parametro di configurazione.","bulk_config_result_ok":"Fatto! Config applicata a {n} profili ✓","bulk_config_result_partial":"Applicato: {ok}, con errore: {fail}","single_config_confirm_title":"Salvare le modifiche?","single_config_confirm_text":"Per applicare la nuova configurazione, il dispositivo in esecuzione verrà spento automaticamente.\nContinuare?","confirm_clone_profile_title":"Clonare il profilo?","confirm_clone_profile_text":"Il dispositivo è attualmente in esecuzione. Verrà spento automaticamente per il clonaggio.\nContinuare?","add_device_tooltip":"Crea dispositivo","create_tablet":"Tablet 2560 × 1440","create_phone":"Telefono 1440 × 2560","creating_device":"Creazione dispositivo...","create_device_error":"Errore durante la creazione del dispositivo","empty_no_profiles":"Nessun profilo, aggiungi il primo :)","sep_running":"ACCESO","sep_all":"TUTTI","sep_running_search":"ACCESO (RICERCA)","sep_search":"RICERCA","empty_mumu_not_running":"MuMuPlayer non è in esecuzione"},
 "pt":{"profile_label":"PERFIL","sort_running_first":"Em execução primeiro","sort_name_asc":"Nome (A → Z)","sort_name_desc":"Nome (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Pesquisar (nome, ID, nota)...","btn_stop_all":"Fechar tudo","settings_tooltip":"Configurações","settings_title":"Configurações","always_on_top":"Sempre no topo","theme_label":"Tema","theme_dark":"Escuro","theme_light":"Claro","language_label":"Idioma","sticker_settings_btn":"Configurações de stickers ▾","reset_btn":"Redefinir ▾","close_btn":"Salvar","reset_all":"Redefinir todos os stickers","reset_except":"Redefinir todos exceto...","reset_specific":"Redefinir específicos...","reset_notes":"Redefinir todas as notas","sticker_mgr_title":"Configurações de stickers","sticker_mgr_placeholder":"Novo símbolo...","sticker_mgr_add":"Adicionar","sticker_mgr_delete":"Excluir","sticker_mgr_save":"Salvar","sticker_mgr_badge":"📌 Sticker principal padrão","tt_first":"Ir para o início da lista (tornar principal)","tt_left":"Voltar uma posição","tt_right":"Avançar uma posição","tt_last":"Ir para o final da lista","confirm":"Confirmar","title_except":"Redefinir todos, exceto...","title_specific":"Redefinir específicos...","notes_label":"NOTAS","stickers_label":"STICKERS","note_placeholder":"Escreva uma nota...\n(Shift+Enter para nova linha)","note_saved":"Salvo ✓","note_tooltip_prefix":"📜Nota: ","confirm_reset_stickers_title":"Redefinir todos os stickers?","confirm_reset_stickers_text":"Todos os stickers em todos os perfis serão redefinidos para o padrão.\nEsta ação não pode ser desfeita.","confirm_reset_notes_title":"Excluir todas as notas?","confirm_reset_notes_text":"Todas as notas em todos os perfis serão excluídas.\nEsta ação não pode ser desfeita.","btn_cancel":"Voltar","btn_confirm_delete":"Confirmar","language_search_placeholder":"🔍 Pesquisar idioma...","no_stickers_selected":"Nenhum dispositivo tem sticker selecionado","nothing_selected":"Nada selecionado","empty_reset_stickers":"Nenhum sticker definido para redefinir.\nTodos os dispositivos já usam o sticker padrão.","empty_reset_notes":"Nenhuma nota para excluir.\nNenhum registro salvo em qualquer dispositivo.","edit_config":"Editar config","clone_profile":"Clonar","delete_profile":"Excluir","confirm_delete_profile_title":"Excluir perfil?","confirm_delete_profile_text":"Tem certeza de que deseja excluir {name}?\nEsta ação não pode ser desfeita.","select_all_btn":"Marcar tudo","deselect_all_btn":"Desmarcar tudo","selected_label":"Marcados: {n}","start_selected_tooltip":"Iniciar marcados","stop_selected_tooltip":"Parar marcados","config_editor_title":"Configuração do dispositivo ID: ","invalid_json":"Erro: JSON inválido!","bulk_config_btn":"Editar config de todos os perfis","bulk_config_title":"Configuração de todos os perfis","bulk_config_hint":"Cole o trecho de config de qualquer perfil — ele será aplicado imediatamente a todos os perfis.","bulk_config_placeholder":"Basta colar o trecho de config do perfil desejado aqui. Ele será aplicado imediatamente a todos os perfis! Por exemplo:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Aplicar config a todos os perfis?","bulk_config_confirm_text":"Os parâmetros especificados serão aplicados imediatamente a {n} perfis.\nAtenção: todos os dispositivos em execução serão desligados automaticamente antes de alterar a config.","bulk_config_empty":"Adicione pelo menos um parâmetro de configuração.","bulk_config_result_ok":"Pronto! Config aplicada a {n} perfis ✓","bulk_config_result_partial":"Aplicado: {ok}, com erro: {fail}","single_config_confirm_title":"Salvar alterações?","single_config_confirm_text":"Para aplicar a nova configuração, o dispositivo em execução será desligado automaticamente.\nContinuar?","confirm_clone_profile_title":"Clonar perfil?","confirm_clone_profile_text":"O dispositivo está em execução. Ele será desligado automaticamente para clonagem.\nContinuar?","add_device_tooltip":"Criar dispositivo","create_tablet":"Tablet 2560 × 1440","create_phone":"Celular 1440 × 2560","creating_device":"Criando dispositivo...","create_device_error":"Erro ao criar dispositivo","empty_no_profiles":"Nenhum perfil, adicione o primeiro :)","sep_running":"LIGADO","sep_all":"TODOS","sep_running_search":"LIGADO (PESQUISA)","sep_search":"PESQUISA","empty_mumu_not_running":"MuMuPlayer não está em execução"},
 "pl":{"profile_label":"PROFIL","sort_running_first":"Najpierw uruchomione","sort_name_asc":"Nazwa (A → Z)","sort_name_desc":"Nazwa (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Szukaj (po nazwie, ID, notatce)...","btn_stop_all":"Zamknij wszystko","settings_tooltip":"Ustawienia","settings_title":"Ustawienia","always_on_top":"Zawsze na wierzchu","theme_label":"Motyw","theme_dark":"Ciemny","theme_light":"Jasny","language_label":"Język","sticker_settings_btn":"Ustawienia naklejek ▾","reset_btn":"Resetuj ▾","close_btn":"Zapisz","reset_all":"Zresetuj wszystkie naklejki","reset_except":"Zresetuj wszystkie oprócz...","reset_specific":"Zresetuj wybrane...","reset_notes":"Zresetuj wszystkie notatki","sticker_mgr_title":"Ustawienia naklejek","sticker_mgr_placeholder":"Nowy symbol...","sticker_mgr_add":"Dodaj","sticker_mgr_delete":"Usuń","sticker_mgr_save":"Zapisz","sticker_mgr_badge":"📌 Domyślna główna naklejka","tt_first":"Na początek listy (ustaw jako główną)","tt_left":"Cofnij o jedną pozycję","tt_right":"Przesuń o jedną pozycję","tt_last":"Na koniec listy","confirm":"Potwierdź","title_except":"Zresetuj wszystkie, oprócz...","title_specific":"Zresetuj wybrane...","notes_label":"NOTATKI","stickers_label":"NAKLEJKI","note_placeholder":"Napisz notatkę...\n(Shift+Enter dla nowej linii)","note_saved":"Zapisano ✓","note_tooltip_prefix":"📜Notatka: ","confirm_reset_stickers_title":"Zresetować wszystkie naklejki?","confirm_reset_stickers_text":"Wszystkie naklejki na wszystkich profilach zostaną zresetowane do wartości domyślnej.\nTej operacji nie można cofnąć.","confirm_reset_notes_title":"Usunąć wszystkie notatki?","confirm_reset_notes_text":"Wszystkie notatki na wszystkich profilach zostaną usunięte.\nTej operacji nie można cofnąć.","btn_cancel":"Wstecz","btn_confirm_delete":"Potwierdź","language_search_placeholder":"🔍 Szukaj języka...","no_stickers_selected":"Brak wybranej naklejki na jakimkolwiek urządzeniu","nothing_selected":"Nic nie wybrano","empty_reset_stickers":"Brak ustawionych naklejek do zresetowania.\nWszystkie urządzenia używają już domyślnej naklejki.","empty_reset_notes":"Brak notatek do usunięcia.\nBrak zapisanych rekordów na jakimkolwiek urządzeniu.","edit_config":"Edytuj konfig","clone_profile":"Klonuj","delete_profile":"Usuń","confirm_delete_profile_title":"Usunąć profil?","confirm_delete_profile_text":"Czy na pewno chcesz usunąć {name}?\nTej operacji nie można cofnąć.","select_all_btn":"Zaznacz wszystko","deselect_all_btn":"Odznacz wszystko","selected_label":"Zaznaczone: {n}","start_selected_tooltip":"Uruchom zaznaczone","stop_selected_tooltip":"Zatrzymaj zaznaczone","config_editor_title":"Konfiguracja urządzenia ID: ","invalid_json":"Błąd: Nieprawidłowy JSON!","bulk_config_btn":"Edytuj konfig wszystkich profili","bulk_config_title":"Konfiguracja wszystkich profili","bulk_config_hint":"Wklej fragment konfigu z dowolnego profilu — zostanie on od razu zastosowany do wszystkich profili.","bulk_config_placeholder":"Po prostu wklej potrzebny fragment konfigu z wybranego profilu tutaj. Zostanie zastosowany natychmiast do wszystkich profili! Na przykład:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Zastosować konfig do wszystkich profili?","bulk_config_confirm_text":"Określone parametry zostaną natychmiast zastosowane do {n} profili.\nUwaga: wszystkie uruchomione urządzenia zostaną automatycznie wyłączone przed zmianą konfigu.","bulk_config_empty":"Dodaj co najmniej jeden parametr konfiguracji.","bulk_config_result_ok":"Gotowe! Konfig zastosowany do {n} profili ✓","bulk_config_result_partial":"Zastosowano: {ok}, z błędem: {fail}","single_config_confirm_title":"Zapisać zmiany?","single_config_confirm_text":"Aby zastosować nową konfigurację, uruchomione urządzenie zostanie automatycznie wyłączone.\nKontynuować?","confirm_clone_profile_title":"Sklonować profil?","confirm_clone_profile_text":"Urządzenie jest obecnie uruchomione. Zostanie automatycznie wyłączone w celu sklonowania.\nKontynuować?","add_device_tooltip":"Utwórz urządzenie","create_tablet":"Tablet 2560 × 1440","create_phone":"Telefon 1440 × 2560","creating_device":"Tworzenie urządzenia...","create_device_error":"Błąd tworzenia urządzenia","empty_no_profiles":"Brak profili, dodaj pierwszy :)","sep_running":"WŁ.","sep_all":"WSZYSTKIE","sep_running_search":"WŁ. (SZUKAJ)","sep_search":"SZUKAJ","empty_mumu_not_running":"MuMuPlayer nie jest uruchomiony"},
 "tr":{"profile_label":"PROFİL","sort_running_first":"Önce çalışanlar","sort_name_asc":"İsim (A → Z)","sort_name_desc":"İsim (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Ara (isim, ID, not ile)...","btn_stop_all":"Tümünü kapat","settings_tooltip":"Ayarlar","settings_title":"Ayarlar","always_on_top":"Her zaman üstte","theme_label":"Tema","theme_dark":"Karanlık","theme_light":"Açık","language_label":"Dil","sticker_settings_btn":"Sticker ayarları ▾","reset_btn":"Sıfırla ▾","close_btn":"Kaydet","reset_all":"Tüm stickerları sıfırla","reset_except":"Hariç tümünü sıfırla...","reset_specific":"Özel sıfırla...","reset_notes":"Tüm notları sıfırla","sticker_mgr_title":"Sticker ayarları","sticker_mgr_placeholder":"Yeni sembol...","sticker_mgr_add":"Ekle","sticker_mgr_delete":"Sil","sticker_mgr_save":"Kaydet","sticker_mgr_badge":"📌 Varsayılan ana sticker","tt_first":"Listenin başına (ana sticker yap)","tt_left":"Bir konum geri","tt_right":"Bir konum ileri","tt_last":"Listenin sonuna","confirm":"Onayla","title_except":"Hariç tümünü sıfırla...","title_specific":"Özel sıfırla...","notes_label":"NOTLAR","stickers_label":"STICKERLAR","note_placeholder":"Bir not yazın...\n(Alt satır için Shift+Enter)","note_saved":"Kaydedildi ✓","note_tooltip_prefix":"📜Not: ","confirm_reset_stickers_title":"Tüm stickerlar sıfırlansın mı?","confirm_reset_stickers_text":"Tüm profillerdeki tüm stickerlar varsayılan değere sıfırlanacaktır.\nBu işlem geri alınamaz.","confirm_reset_notes_title":"Tüm notlar silinsin mi?","confirm_reset_notes_text":"Tüm profillerdeki tüm notlar silinecektir.\nBu işlem geri alınamaz.","btn_cancel":"Geri","btn_confirm_delete":"Onayla","language_search_placeholder":"🔍 Dil ara...","no_stickers_selected":"Hiçbir cihazda sticker seçilmedi","nothing_selected":"Hiçbir şey seçilmedi","empty_reset_stickers":"Sıfırlanacak özel sticker yok.\nTüm cihazlar zaten varsayılan stickerı kullanıyor.","empty_reset_notes":"Silinecek not yok.\nHiçbir cihazda kayıtlı veri bulunmuyor.","edit_config":"Yapılandırmayı düzenle","clone_profile":"Klonla","delete_profile":"Sil","confirm_delete_profile_title":"Profil silinsin mi?","confirm_delete_profile_text":"{name} profilini silmek istediğinizden emin misiniz?\nBu işlem geri alınamaz.","select_all_btn":"Tümünü seç","deselect_all_btn":"Seçimleri kaldır","selected_label":"Seçilen: {n}","start_selected_tooltip":"Seçilenleri başlat","stop_selected_tooltip":"Seçilenleri durdur","config_editor_title":"Cihaz yapılandırma ID: ","invalid_json":"Hata: Geçersiz JSON!","bulk_config_btn":"Tüm profillerin yapılandırmasını düzenle","bulk_config_title":"Tüm profillerin yapılandırması","bulk_config_hint":"Herhangi bir profilden gerekli yapılandırma kodunu yapıştırın — anında tüm profillere uygulanacaktır.","bulk_config_placeholder":"İstediğiniz profilden gerekli yapılandırma kodunu kopyalayıp buraya yapıştırın. Anında tüm profillere uygulanacaktır! Örneğin:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Yapılandırma tüm profillere uygulansın mı?","bulk_config_confirm_text":"Belirtilen parametreler anında {n} profile uygulanacaktır.\nUyarı: Çalışan tüm cihazlar yapılandırma değiştirilmeden önce otomatik olarak kapatılacaktır.","bulk_config_empty":"En az bir yapılandırma parametresi ekleyin.","bulk_config_result_ok":"Tamamlandı! Yapılandırma {n} profile uygulandı ✓","bulk_config_result_partial":"Uygulandı: {ok}, hatalı: {fail}","single_config_confirm_title":"Değişiklikler kaydedilsin mi?","single_config_confirm_text":"Yeni yapılandırmayı uygulamak için çalışan cihaz otomatik olarak kapatılacaktır.\nDevam edilsin mi?","confirm_clone_profile_title":"Profil klonlansın mı?","confirm_clone_profile_text":"Cihaz şu anda çalışıyor. Klonlama için otomatik olarak kapatılacaktır.\nDevam edilsin mi?","add_device_tooltip":"Cihaz oluştur","create_tablet":"Tablet 2560 × 1440","create_phone":"Telefon 1440 × 2560","creating_device":"Cihaz oluşturuluyor...","create_device_error":"Cihaz oluşturma hatası","empty_no_profiles":"Henüz profil yok, ilkini ekleyin :)","sep_running":"AÇIK","sep_all":"TÜMÜ","sep_running_search":"AÇIK (ARAMA)","sep_search":"ARAMA","empty_mumu_not_running":"MuMuPlayer çalışmıyor"},
 "ja":{"profile_label":"プロファイル","sort_running_first":"起動中を優先","sort_name_asc":"名前 (A → Z)","sort_name_desc":"名前 (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 検索 (名前、ID、メモ)...","btn_stop_all":"すべて閉じる","settings_tooltip":"設定","settings_title":"設定","always_on_top":"常に最前面表示","theme_label":"テーマ","theme_dark":"ダーク","theme_light":"ライト","language_label":"言語","sticker_settings_btn":"ステッカー設定 ▾","reset_btn":"リセット ▾","close_btn":"保存","reset_all":"すべてのステッカーをリセット","reset_except":"指定以外をすべてリセット...","reset_specific":"指定ステッカーをリセット...","reset_notes":"すべてのメモをリセット","sticker_mgr_title":"ステッカー設定","sticker_mgr_placeholder":"新しいシンボル...","sticker_mgr_add":"追加","sticker_mgr_delete":"削除","sticker_mgr_save":"保存","sticker_mgr_badge":"📌 デフォルトのメインステッカー","tt_first":"リストの先頭へ（メインに設定）","tt_left":"1つ前に移動","tt_right":"1つ後に移動","tt_last":"リストの末尾へ","confirm":"確認","title_except":"指定以外をすべてリセット...","title_specific":"指定ステッカーをリセット...","notes_label":"メモ","stickers_label":"ステッカー","note_placeholder":"メモを入力...\n(Shift+Enterで改行)","note_saved":"保存しました ✓","note_tooltip_prefix":"📜メモ: ","confirm_reset_stickers_title":"すべてのステッカーをリセットしますか？","confirm_reset_stickers_text":"すべてのプロファイルのステッカーがデフォルト値にリセットされます。\nこの操作は取り消せません。","confirm_reset_notes_title":"すべてのメモを削除しますか？","confirm_reset_notes_text":"すべてのプロファイルのメモが削除されます。\nこの操作は取り消せません。","btn_cancel":"戻る","btn_confirm_delete":"確認","language_search_placeholder":"🔍 言語を検索...","no_stickers_selected":"ステッカーが選択されているデバイスはありません","nothing_selected":"何も選択されていません","empty_reset_stickers":"リセットする設定済みステッカーがありません。\nすべてのデバイスがすでにデフォルトステッカーを使用しています。","empty_reset_notes":"削除するメモがありません。\n保存された記録のあるデバイスはありません。","edit_config":"設定の編集","clone_profile":"複製","delete_profile":"削除","confirm_delete_profile_title":"プロファイルを削除しますか？","confirm_delete_profile_text":"{name} を削除してもよろしいですか？\nこの操作は取り消せません。","select_all_btn":"すべて選択","deselect_all_btn":"選択解除","selected_label":"選択中: {n}","start_selected_tooltip":"選択した項目を起動","stop_selected_tooltip":"選択した項目を停止","config_editor_title":"デバイス設定 ID: ","invalid_json":"エラー: 無効なJSONです！","bulk_config_btn":"全プロファイルの設定を編集","bulk_config_title":"全プロファイルの設定","bulk_config_hint":"任意のプロファイルから必要な設定コードを貼り付けると、すべてのプロファイルに即座に適用されます。","bulk_config_placeholder":"希望するプロファイルから必要な設定コードをここに貼り付けるだけです。すべてのプロファイルに即座に適用されます！例:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"全プロファイルに設定を適用しますか？","bulk_config_confirm_text":"指定されたパラメータが {n} 個のプロファイルに即座に適用されます。\n注意: 設定変更前に起動中のすべてのデバイスが自動的に停止します。","bulk_config_empty":"設定パラメータを少なくとも1つ追加してください。","bulk_config_result_ok":"完了！{n} 個のプロファイルに設定が適用されました ✓","bulk_config_result_partial":"適用: {ok}、エラー: {fail}","single_config_confirm_title":"変更を保存しますか？","single_config_confirm_text":"新しい設定を適用するため、起動中のデバイスは自動的に停止します。\n続行しますか？","confirm_clone_profile_title":"プロファイルを複製しますか？","confirm_clone_profile_text":"デバイスは現在起動中です。複製のため自動的に停止します。\n続行しますか？","add_device_tooltip":"デバイスを作成","create_tablet":"タブレット 2560 × 1440","create_phone":"スマートフォン 1440 × 2560","creating_device":"デバイスを作成中...","create_device_error":"デバイス作成エラー","empty_no_profiles":"プロファイルがありません。最初のプロファイルを追加してください :)","sep_running":"起動中","sep_all":"すべて","sep_running_search":"起動中（検索）","sep_search":"検索","empty_mumu_not_running":"MuMuPlayer が起動していません"},
 "ko":{"profile_label":"프로필","sort_running_first":"실행 중인 항목 우선","sort_name_asc":"이름 (A → Z)","sort_name_desc":"이름 (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 검색 (이름, ID, 메모)...","btn_stop_all":"모두 닫기","settings_tooltip":"설정","settings_title":"설정","always_on_top":"항상 위","theme_label":"테마","theme_dark":"다크","theme_light":"라이트","language_label":"언어","sticker_settings_btn":"스티커 설정 ▾","reset_btn":"초기화 ▾","close_btn":"저장","reset_all":"모든 스티커 초기화","reset_except":"제외하고 모두 초기화...","reset_specific":"특정 스티커 초기화...","reset_notes":"모든 메모 초기화","sticker_mgr_title":"스티커 설정","sticker_mgr_placeholder":"새 기호...","sticker_mgr_add":"추가","sticker_mgr_delete":"삭제","sticker_mgr_save":"저장","sticker_mgr_badge":"📌 기본 메인 스티커","tt_first":"목록 맨 위로 (메인으로 설정)","tt_left":"한 단계 뒤로","tt_right":"한 단계 앞으로","tt_last":"목록 맨 끝으로","confirm":"확인","title_except":"제외하고 모두 초기화...","title_specific":"특정 스티커 초기화...","notes_label":"메모","stickers_label":"스티커","note_placeholder":"메모를 입력하세요...\n(줄바꿈은 Shift+Enter)","note_saved":"저장됨 ✓","note_tooltip_prefix":"📜메모: ","confirm_reset_stickers_title":"모든 스티커를 초기화하시겠습니까?","confirm_reset_stickers_text":"모든 프로필의 모든 스티커가 기본값으로 초기화됩니다.\n이 작업은 취소할 수 없습니다.","confirm_reset_notes_title":"모든 메모를 삭제하시겠습니까?","confirm_reset_notes_text":"모든 프로필의 모든 메모가 삭제됩니다.\n이 작업은 취소할 수 없습니다.","btn_cancel":"뒤로","btn_confirm_delete":"확인","language_search_placeholder":"🔍 언어 검색...","no_stickers_selected":"선택된 스티커가 있는 기기가 없습니다","nothing_selected":"선택된 항목 없음","empty_reset_stickers":"초기화할 스티커가 없습니다.\n모든 기기가 이미 기본 스티커를 사용 중입니다.","empty_reset_notes":"삭제할 메모가 없습니다.\n저장된 기록이 있는 기기가 없습니다.","edit_config":"설정 수정","clone_profile":"복제","delete_profile":"삭제","confirm_delete_profile_title":"프로필을 삭제하시겠습니까?","confirm_delete_profile_text":"{name} 프로필을 삭제하시겠습니까?\n이 작업은 취소할 수 없습니다.","select_all_btn":"전체 선택","deselect_all_btn":"선택 해제","selected_label":"선택됨: {n}","start_selected_tooltip":"선택 항목 실행","stop_selected_tooltip":"선택 항목 중지","config_editor_title":"기기 설정 ID: ","invalid_json":"오류: 올바르지 않은 JSON입니다!","bulk_config_btn":"모든 프로필 설정 수정","bulk_config_title":"모든 프로필 설정","bulk_config_hint":"원하는 프로필의 설정 코드 조각을 붙여넣으면 모든 프로필에 즉시 적용됩니다.","bulk_config_placeholder":"원하는 프로필의 설정 코드 조각을 여기에 붙여넣기만 하면 됩니다. 모든 프로필에 즉시 적용됩니다! 예:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"모든 프로필에 설정을 적용하시겠습니까?","bulk_config_confirm_text":"지정된 매개변수가 {n}개 프로필에 즉시 적용됩니다.\n주의: 설정 변경 전 실행 중인 모든 기기가 자동으로 종료됩니다.","bulk_config_empty":"최소 하나의 설정 매개변수를 추가하세요.","bulk_config_result_ok":"완료! {n}개 프로필에 설정이 적용되었습니다 ✓","bulk_config_result_partial":"적용됨: {ok}, 오류: {fail}","single_config_confirm_title":"변경 사항을 저장하시겠습니까?","single_config_confirm_text":"새 설정을 적용하기 위해 실행 중인 기기가 자동으로 종료됩니다.\n계속하시겠습니까?","confirm_clone_profile_title":"프로필을 복제하시겠습니까?","confirm_clone_profile_text":"기기가 현재 실행 중입니다. 복제를 위해 자동으로 종료됩니다.\n계속하시겠습니까?","add_device_tooltip":"기기 생성","create_tablet":"태블릿 2560 × 1440","create_phone":"스마트폰 1440 × 2560","creating_device":"기기 생성 중...","create_device_error":"기기 생성 오류","empty_no_profiles":"프로필이 없습니다. 첫 번째 프로필을 추가하세요 :)","sep_running":"실행 중","sep_all":"전체","sep_running_search":"실행 중 (검색)","sep_search":"검색","empty_mumu_not_running":"MuMuPlayer가 실행 중이지 않습니다"},
 "ar":{"profile_label":"الملف الشخصي","sort_running_first":"المشغلة أولاً","sort_name_asc":"الاسم (أ ← ي)","sort_name_desc":"الاسم (ي ← أ)","sort_id_asc":"المعرف (0 ← 9)","sort_id_desc":"المعرف (9 ← 0)","search_placeholder":"🔍 بحث (بالاسم، المعرف، الملاحظة)...","btn_stop_all":"إغلاق الكل","settings_tooltip":"الإعدادات","settings_title":"الإعدادات","always_on_top":"دائماً في الأعلى","theme_label":"المظهر","theme_dark":"داكن","theme_light":"فاتح","language_label":"اللغة","sticker_settings_btn":"إعدادات الملصقات ▾","reset_btn":"إعادة ضبط ▾","close_btn":"حفظ","reset_all":"إعادة ضبط جميع الملصقات","reset_except":"إعادة ضبط الكل باستثناء...","reset_specific":"إعادة ضبط ملصقات محددة...","reset_notes":"إعادة ضبط جميع الملاحظات","sticker_mgr_title":"إعدادات الملصقات","sticker_mgr_placeholder":"رمز جديد...","sticker_mgr_add":"إضافة","sticker_mgr_delete":"حذف","sticker_mgr_save":"حفظ","sticker_mgr_badge":"📌 الملصق الرئيسي الافتراضي","tt_first":"إلى أعلى القائمة (جعله رئيسياً)","tt_left":"خطوة للوراء","tt_right":"خطوة للأمام","tt_last":"إلى أسفل القائمة","confirm":"تأكيد","title_except":"إعادة ضبط الكل، باستثناء...","title_specific":"إعادة ضبط ملصقات محددة...","notes_label":"الملاحظات","stickers_label":"الملصقات","note_placeholder":"اكتب ملاحظة...\n(Shift+Enter للسطر الجديد)","note_saved":"تم الحفظ ✓","note_tooltip_prefix":"📜ملاحظة: ","confirm_reset_stickers_title":"إعادة ضبط جميع الملصقات؟","confirm_reset_stickers_text":"سيتم إعادة ضبط جميع الملصقات في جميع الملفات الشخصية إلى القيمة الافتراضية.\nلا يمكن التراجع عن هذا الإجراء.","confirm_reset_notes_title":"حذف جميع الملاحظات؟","confirm_reset_notes_text":"سيتم حذف جميع الملاحظات في جميع الملفات الشخصية.\nلا يمكن التراجع عن هذا الإجراء.","btn_cancel":"رجوع","btn_confirm_delete":"تأكيد","language_search_placeholder":"🔍 البحث عن لغة...","no_stickers_selected":"لم يتم تحديد ملصق على أي جهاز","nothing_selected":"لم يتم تحديد أي شيء","empty_reset_stickers":"لا توجد ملصقات مخصصة لإعادة ضبطها.\nجميع الأجهزة تستخدم بالفعل الملصق الافتراضي.","empty_reset_notes":"لا توجد ملاحظات للحذف.\nلا توجد سجلات محفوظة على أي جهاز.","edit_config":"تعديل الإعدادات","clone_profile":"نسخ","delete_profile":"حذف","confirm_delete_profile_title":"حذف الملف الشخصي؟","confirm_delete_profile_text":"هل أنت متأكد من أنك تريد حذف {name}؟\nلا يمكن التراجع عن هذا الإجراء.","select_all_btn":"تحديد الكل","deselect_all_btn":"إلغاء تحديد الكل","selected_label":"المحدد: {n}","start_selected_tooltip":"تشغيل المحدد","stop_selected_tooltip":"إيقاف المحدد","config_editor_title":"إعدادات الجهاز ID: ","invalid_json":"خطأ: JSON غير صالحة!","bulk_config_btn":"تعديل إعدادات جميع الملفات الشخصية","bulk_config_title":"إعدادات جميع الملفات الشخصية","bulk_config_hint":"الصق كود الإعدادات المطلوبة من أي ملف شخصي — سيتم تطبيقه فوراً على جميع الملفات الشخصية.","bulk_config_placeholder":"فقط الصق كود الإعدادات المطلوبة من الملف الشخصي المحدد هنا. سيتم تطبيقه فوراً على جميع الملفات الشخصية! على سبيل المثال:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"تطبيق الإعدادات على جميع الملفات الشخصية؟","bulk_config_confirm_text":"سيتم تطبيق المعلمات المحددة فوراً على {n} ملفات شخصية.\nتنبيه: سيتم إيقاف تشغيل جميع الأجهزة المشغلة تلقائياً قبل تغيير الإعدادات.","bulk_config_empty":"أضف معلمة إعدادات واحدة على الأقل.","bulk_config_result_ok":"تم! تم تطبيق الإعدادات على {n} ملف شخصي ✓","bulk_config_result_partial":"تم التطبيق: {ok}، مع وجود خطأ: {fail}","single_config_confirm_title":"حفظ التغييرات؟","single_config_confirm_text":"لتطبيق الإعدادات الجديدة، سيتم إيقاف تشغيل الجهاز المشغل تلقائياً.\nهل تريد الاستمرار؟","confirm_clone_profile_title":"نسخ الملف الشخصي؟","confirm_clone_profile_text":"الجهاز قيد التشغيل حالياً. سيتم إيقاف تشغيله تلقائياً للنسخ.\nهل تريد الاستمرار؟","add_device_tooltip":"إنشاء جهاز","create_tablet":"جهاز لوحي 2560 × 1440","create_phone":"هاتف 1440 × 2560","creating_device":"جاري إنشاء الجهاز...","create_device_error":"خطأ في إنشاء الجهاز","empty_no_profiles":"لا توجد ملفات شخصية، أضف الأول :)","sep_running":"يعمل","sep_all":"الكل","sep_running_search":"يعمل (بحث)","sep_search":"بحث","empty_mumu_not_running":"MuMuPlayer ليس قيد التشغيل"},
 "hi":{"profile_label":"प्रोफ़ाइल","sort_running_first":"पहले चालू वाले","sort_name_asc":"नाम (A → Z)","sort_name_desc":"नाम (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 खोजें (नाम, ID, नोट द्वारा)...","btn_stop_all":"सभी बंद करें","settings_tooltip":"सेटिंग्स","settings_title":"सेटिंग्स","always_on_top":"हमेशा ऊपर रखें","theme_label":"थीम","theme_dark":"डार्क","theme_light":"लाइट","language_label":"भाषा","sticker_settings_btn":"स्टिकर सेटिंग्स ▾","reset_btn":"रीसेट ▾","close_btn":"सहेजें","reset_all":"सभी स्टिकर रीसेट करें","reset_except":"इनको छोड़कर सभी रीसेट करें...","reset_specific":"विशेष रीसेट करें...","reset_notes":"सभी नोट रीसेट करें","sticker_mgr_title":"स्टिकर सेटिंग्स","sticker_mgr_placeholder":"नया प्रतीक...","sticker_mgr_add":"जोड़ें","sticker_mgr_delete":"हटाएं","sticker_mgr_save":"सहेजें","sticker_mgr_badge":"📌 डिफ़ॉल्ट मुख्य स्टिकर","tt_first":"सूची के शीर्ष पर (मुख्य बनाएं)","tt_left":"एक स्थिति पीछे","tt_right":"एक स्थिति आगे","tt_last":"सूची के अंत में","confirm":"पुष्टि करें","title_except":"इनको छोड़कर सभी रीसेट करें...","title_specific":"विशेष रीसेट करें...","notes_label":"नोट्स","stickers_label":"स्टिकर","note_placeholder":"एक नोट लिखें...\n(नई पंक्ति के लिए Shift+Enter)","note_saved":"सहेजा गया ✓","note_tooltip_prefix":"📜नोट: ","confirm_reset_stickers_title":"सभी स्टिकर रीसेट करें?","confirm_reset_stickers_text":"सभी प्रोफ़ाइलों पर सभी स्टिकर डिफ़ॉल्ट मान पर रीसेट कर दिए जाएंगे।\nइस कार्रवाई को पूर्ववत नहीं किया जा सकता है।","confirm_reset_notes_title":"सभी नोट्स हटाएं?","confirm_reset_notes_text":"सभी प्रोफ़ाइलों पर सभी नोट्स हटा दिए जाएंगे।\nइस कार्रवाई को पूर्ववत नहीं किया जा सकता है।","btn_cancel":"वापस","btn_confirm_delete":"पुष्टि करें","language_search_placeholder":"🔍 भाषा खोजें...","no_stickers_selected":"किसी भी डिवाइस पर कोई स्टिकर चुना नहीं गया है","nothing_selected":"कुछ भी चुना नहीं गया","empty_reset_stickers":"रीसेट करने के लिए कोई सेट स्टिकर नहीं है।\nसभी डिवाइस पहले से ही डिफ़ॉल्ट स्टिकर का उपयोग कर रहे हैं।","empty_reset_notes":"हटाने के लिए कोई नोट्स नहीं हैं।\nकिसी भी डिवाइस पर कोई सहेजे गए रिकॉर्ड नहीं हैं।","edit_config":"कॉन्फ़िग संपादित करें","clone_profile":"क्लोन","delete_profile":"हटाएं","confirm_delete_profile_title":"प्रोफ़ाइल हटाएं?","confirm_delete_profile_text":"क्या आप निश्चित रूप से {name} को हटाना चाहते हैं?\nइस कार्रवाई को पूर्ववत नहीं किया जा सकता है।","select_all_btn":"सभी चुनें","deselect_all_btn":"सभी का चयन रद्द करें","selected_label":"चयनित: {n}","start_selected_tooltip":"चयनित प्रारंभ करें","stop_selected_tooltip":"चयनित रोकें","config_editor_title":"डिवाइस कॉन्फ़िगरेशन ID: ","invalid_json":"त्रुटि: अमान्य JSON!","bulk_config_btn":"सभी प्रोफ़ाइलों का कॉन्फ़िग संपादित करें","bulk_config_title":"सभी प्रोफ़ाइलों का कॉन्फ़िगरेशन","bulk_config_hint":"किसी भी प्रोफ़ाइल से आवश्यक कॉन्फ़िग कोड पेस्ट करें — यह एक बार में सभी प्रोफ़ाइलों पर लागू हो जाएगा।","bulk_config_placeholder":"बस इच्छित प्रोफ़ाइल से आवश्यक कॉन्फ़िग कोड कॉपी करें और यहां पेस्ट करें। यह तुरंत सभी प्रोफ़ाइलों पर लागू होगा! उदाहरण के लिए:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"सभी प्रोफ़ाइलों पर कॉन्फ़िग लागू करें?","bulk_config_confirm_text":"निर्दिष्ट पैरामीटर एक साथ {n} प्रोफ़ाइलों पर लागू किए जाएंगे।\nचेतावनी: कॉन्फ़िग बदलने से पहले सभी चालू डिवाइस स्वचालित रूप से बंद हो जाएंगे।","bulk_config_empty":"कम से कम एक कॉन्फ़िगरेशन पैरामीटर जोड़ें।","bulk_config_result_ok":"हो गया! {n} प्रोफ़ाइलों पर कॉन्फ़िग लागू किया गया ✓","bulk_config_result_partial":"लागू किया गया: {ok}, त्रुटि के साथ: {fail}","single_config_confirm_title":"परिवर्तन सहेजें?","single_config_confirm_text":"नई कॉन्फ़िगरेशन लागू करने के लिए चालू डिवाइस स्वचालित रूप से बंद हो जाएगा।\nजारी रखें?","confirm_clone_profile_title":"प्रोफ़ाइल क्लोन करें?","confirm_clone_profile_text":"डिवाइस वर्तमान में चालू है। क्लोनिंग के लिए इसे स्वचालित रूप से बंद कर दिया जाएगा।\nजारी रखें?","add_device_tooltip":"डिवाइस बनाएं","create_tablet":"टैबलेट 2560 × 1440","create_phone":"फोन 1440 × 2560","creating_device":"डिवाइस बनाया जा रहा है...","create_device_error":"डिवाइस बनाने में त्रुटि","empty_no_profiles":"कोई प्रोफ़ाइल नहीं है, पहली प्रोफ़ाइल जोड़ें :)","sep_running":"चालू","sep_all":"सभी","sep_running_search":"चालू (खोज)","sep_search":"खोज","empty_mumu_not_running":"MuMuPlayer चालू नहीं है"},
 "nl":{"profile_label":"PROFIEL","sort_running_first":"Eerst actieve","sort_name_asc":"Naam (A → Z)","sort_name_desc":"Naam (Z → A)","sort_id_asc":"ID (0 → 9)","sort_id_desc":"ID (9 → 0)","search_placeholder":"🔍 Zoeken (op naam, ID, notitie)...","btn_stop_all":"Alles sluiten","settings_tooltip":"Instellingen","settings_title":"Instellingen","always_on_top":"Altijd bovenaan","theme_label":"Thema","theme_dark":"Donker","theme_light":"Licht","language_label":"Taal","sticker_settings_btn":"Sticker-instellingen ▾","reset_btn":"Resetten ▾","close_btn":"Opslaan","reset_all":"Alle stickers resetten","reset_except":"Alles resetten behalve...","reset_specific":"Specifieke resetten...","reset_notes":"Alle notities resetten","sticker_mgr_title":"Sticker-instellingen","sticker_mgr_placeholder":"Nieuw symbool...","sticker_mgr_add":"Toevoegen","sticker_mgr_delete":"Verwijderen","sticker_mgr_save":"Opslaan","sticker_mgr_badge":"📌 Standaard hoofd-sticker","tt_first":"Naar bovenaan de lijst (maak hoofd-sticker)","tt_left":"Eén positie terug","tt_right":"Eén positie vooruit","tt_last":"Naar onderaan de lijst","confirm":"Bevestigen","title_except":"Alles resetten, behalve...","title_specific":"Specifieke resetten...","notes_label":"NOTITIES","stickers_label":"STICKERS","note_placeholder":"Schrijf een notitie...\n(Shift+Enter voor nieuwe regel)","note_saved":"Opgeslagen ✓","note_tooltip_prefix":"📜Notitie: ","confirm_reset_stickers_title":"Alle stickers resetten?","confirm_reset_stickers_text":"Alle stickers op alle profielen worden teruggezet naar de standaardwaarde.\nDeze actie kan niet ongedaan worden gemaakt.","confirm_reset_notes_title":"Alle notities verwijderen?","confirm_reset_notes_text":"Alle notities op alle profielen worden verwijderd.\nDeze actie kan niet ongedaan worden gemaakt.","btn_cancel":"Terug","btn_confirm_delete":"Bevestigen","language_search_placeholder":"🔍 Taal zoeken...","no_stickers_selected":"Geen sticker geselecteerd op enig apparaat","nothing_selected":"Niets geselecteerd","empty_reset_stickers":"Geen ingestelde stickers om te resetten.\nAlle apparaten gebruiken al de standaardsticker.","empty_reset_notes":"Geen notities om te verwijderen.\nGeen opgeslagen records op enig apparaat.","edit_config":"Config bewerken","clone_profile":"Klonen","delete_profile":"Verwijderen","confirm_delete_profile_title":"Profiel verwijderen?","confirm_delete_profile_text":"Weet u zeker dat u {name} wilt verwijderen?\nDeze actie kan niet ongedaan worden gemaakt.","select_all_btn":"Alles selecteren","deselect_all_btn":"Alles deselecteren","selected_label":"Geselecteerd: {n}","start_selected_tooltip":"Geselecteerde starten","stop_selected_tooltip":"Geselecteerde stoppen","config_editor_title":"Apparaatconfiguratie ID: ","invalid_json":"Fout: Ongeldige JSON!","bulk_config_btn":"Config van alle profielen bewerken","bulk_config_title":"Configuratie van alle profielen","bulk_config_hint":"Plak het benodigde config-fragment van een willekeurig profiel — het wordt direct toegepast op alle profielen.","bulk_config_placeholder":"Plak gewoon het benodigde config-fragment van het gewenste profiel hier. Het wordt direct toegepast op alle profielen! Bijvoorbeeld:\n  \"resolution_mode\": \"custom\",\n  \"resolution_width.custom\": \"1280\",\n  \"resolution_height.custom\": \"720\",\n  \"resolution_dpi.custom\": \"180\",\n  \"performance_mode\": \"custom\",\n  \"performance_cpu.custom\": \"1\",\n  \"performance_mem.custom\": \"2\",","bulk_config_confirm_title":"Config toepassen op alle profielen?","bulk_config_confirm_text":"De opgegeven parameters worden direct toegepast op {n} profielen.\nLet op: alle actieve apparaten worden automatisch uitgeschakeld voordat de config wordt gewijzigd.","bulk_config_empty":"Voeg ten minste één configuratieparameter toe.","bulk_config_result_ok":"Klaar! Config toegepast op {n} profielen ✓","bulk_config_result_partial":"Toegepast: {ok}, met fout: {fail}","single_config_confirm_title":"Wijzigingen opslaan?","single_config_confirm_text":"Om de nieuwe configuratie toe te passen, wordt het actieve apparaat automatisch uitgeschakeld.\nDoorgaan?","confirm_clone_profile_title":"Profiel klonen?","confirm_clone_profile_text":"Het apparaat is momenteel actief. Het wordt automatisch uitgeschakeld om te klonen.\nDoorgaan?","add_device_tooltip":"Apparaat maken","create_tablet":"Tablet 2560 × 1440","create_phone":"Telefoon 1440 × 2560","creating_device":"Apparaat maken...","create_device_error":"Fout bij maken van apparaat","empty_no_profiles":"Nog geen profielen, voeg de eerste toe :)","sep_running":"AAN","sep_all":"ALLE","sep_running_search":"AAN (ZOEKEN)","sep_search":"ZOEKEN","empty_mumu_not_running":"MuMuPlayer is niet actief"}
}
LANGUAGES = [("ru", "🇷🇺", "Русский", "Russian"), ("uk", "🇺🇦", "Українська", "Ukrainian"), ("en", "🇬🇧", "English", "English"), ("es", "🇪🇸", "Español", "Spanish"), ("de", "🇩🇪", "Deutsch", "German"), ("zh", "🇨🇳", "中文", "Chinese"), ("fr", "🇫🇷", "Français", "French"), ("it", "🇮🇹", "Italiano", "Italian"), ("pt", "🇵🇹", "Português", "Portuguese"), ("pl", "🇵🇱", "Polski", "Polish"), ("tr", "🇹🇷", "Türkçe", "Turkish"), ("ja", "🇯🇵", "日本語", "Japanese"), ("ko", "🇰🇷", "한국어", "Korean"), ("ar", "🇸🇦", "العربية", "Arabic"), ("hi", "🇮🇳", "हिन्दी", "Hindi"), ("nl", "🇳🇱", "Nederlands", "Dutch")]
LANG_INFO = {code: (flag, native, en_name) for code, flag, native, en_name in LANGUAGES}

def tr(lang, key): return TR.get(lang, TR["en"]).get(key, TR["en"].get(key, key))
def natural_sort_key(s): return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]
def _mm_cwd():
    d = os.path.dirname(MUMU_BIN) if MUMU_BIN else ""
    return d if d and os.path.isdir(d) else None
def run_cmd(*args, timeout=1.5):
    try: return subprocess.run(list(args), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW, cwd=_mm_cwd())
    except Exception: return None
def mm_run(*args, timeout=30.0):
    # MuMuManager.exe <subcommand> ... ; все аргументы приводим к str (vm_id бывает и числом)
    return run_cmd(MUMU_BIN, *[str(a) for a in args], timeout=timeout)
def mm_spawn(*args):
    # fire-and-forget (запуск/остановка профиля) - без ожидания ответа
    try: subprocess.Popen([MUMU_BIN, *[str(a) for a in args]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, cwd=_mm_cwd())
    except Exception: pass
def mm_run_bg(*args, timeout=120.0):
    threading.Thread(target=mm_run, args=args, kwargs={"timeout": timeout}, daemon=True).start()
def _loads(text):
    try: return json.loads(text)
    except Exception: return None
def mm_result_ok(res):
    # MuMuManager печатает JSON с "errcode" (для clone/create он вложен по индексу новой машины: {"1": {"errcode": 0}})
    if res is None or res.returncode != 0: return False
    def bad(o):
        if isinstance(o, dict):
            if "errcode" in o and o["errcode"] not in (0, "0", None): return True
            return any(bad(v) for v in o.values())
        return False
    return not bad(_loads((res.stdout or "").strip()))
def parse_info(stdout):
    # "info -v all" -> {"0": {...}, "1": {...}}; "info -v N" может вернуть один плоский объект. Приводим к списку.
    # Профиль считаем запущенным, как только стартовал его процесс (is_process_started) или Android (is_android_started):
    # так кнопка Stop доступна сразу, пока Android ещё грузится.
    data = _loads((stdout or "").strip())
    if not isinstance(data, dict): return None
    entries = [data] if ("index" in data and ("name" in data or "is_android_started" in data)) else [v for v in data.values() if isinstance(v, dict) and "index" in v]
    if not entries and "errcode" in data: return None
    out = [{"index": str(e.get("index", "")), "name": e.get("name", "Unknown"), "state": "running" if (e.get("is_android_started") or e.get("is_process_started")) else "stopped"} for e in entries]
    return sorted(out, key=lambda x: int(x["index"]) if x["index"].isdigit() else 10**9)
def mm_vm_active(vm_id):
    res = mm_run("info", "-v", vm_id, timeout=5.0)
    lst = parse_info(res.stdout) if res else None
    if not lst: return None
    return any(e["state"] == "running" for e in lst if e["index"] == str(vm_id))
def mm_shutdown_and_wait(vm_id, timeout=25.0):
    # Профиль надо погасить ДО clone/delete/смены конфига - ждём, пока он реально остановится
    mm_run("control", "-v", vm_id, "shutdown", timeout=15.0)
    end = time.time() + timeout
    while time.time() < end:
        if mm_vm_active(vm_id) is False: return True
        time.sleep(0.5)
    return False
def stringify_settings(d):
    # в MuMu все значения настроек - строки ("false", "1280", ...)
    out = {}
    for k, v in d.items():
        out[k] = ("true" if v else "false") if isinstance(v, bool) else ("null" if v is None else (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)))
    return out
def is_mumu_process_alive():
    # Проверка живости процессов MuMuPlayer напрямую через tasklist, в обход MuMuManager.
    # Нужна чтобы отличить "MuMu реально закрыт" от "MuMuManager просто долго отвечает под нагрузкой".
    try:
        res = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace", timeout=3.0, creationflags=CREATE_NO_WINDOW)
        out = (res.stdout or "").lower()
        return res.returncode == 0 and any(n in out for n in ("mumunxmain.exe", "mumuplayer.exe", "mumunxdevice.exe"))
    except Exception:
        return False
def equalize_buttons(*buttons):
    # Симметричный футер диалога: обе кнопки одной ширины независимо от длины текста/языка
    w = max(b.sizeHint().width() for b in buttons)
    for b in buttons: b.setMinimumWidth(w); b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

class CustomListWidget(QListWidget):
    def __init__(self, parent=None): super().__init__(parent); self.hovered_item = None; self.setMouseTracking(True); self.viewport().setMouseTracking(True)
    def clear_hover(self):
        if self.hovered_item is not None: self.hovered_item = None; self.viewport().update()
    def mouseMoveEvent(self, e):
        m = self.window()
        if (hasattr(m, 'is_blurred') and m.is_blurred) or QApplication.activeModalWidget() is not None: self.clear_hover(); return
        item = self.itemAt(e.pos())
        if item != self.hovered_item: self.hovered_item = item; self.viewport().update()
        super().mouseMoveEvent(e)
    def leaveEvent(self, e): self.clear_hover(); super().leaveEvent(e)

class AnimatedItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None): super().__init__(parent); self._flash_alpha = 0.0; self.anim = QPropertyAnimation(self, b"flash_alpha", self); self.anim.setDuration(200)
    @pyqtProperty(float)
    def flash_alpha(self): return self._flash_alpha
    @flash_alpha.setter
    def flash_alpha(self, v): self._flash_alpha = v; self.parent() and self.parent().viewport().update()
    def trigger_flash(self): self.anim.stop(); self.anim.setStartValue(1.0); self.anim.setEndValue(0.0); self.anim.start()
    def paint(self, painter, option, index):
        if index.data(SEP_ROLE): return  # разделитель между запущенными и остальными - без карточки-подложки, только его собственный виджет
        painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2); path = QPainterPath(); path.addRoundedRect(rect, 8, 8)
        lw = self.parent(); main_win = lw.window() if lw else None
        is_hovered = not (hasattr(main_win, 'is_blurred') and main_win.is_blurred) and isinstance(lw, CustomListWidget) and (lw.item(index.row()) == lw.hovered_item)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected); theme = getattr(main_win, 'current_theme', 'dark')
        bg = (QColor(215,230,250) if is_selected else (QColor(238,238,242) if is_hovered else QColor(255,255,255))) if theme == "light" else (QColor(48,48,52) if is_selected else (QColor(40,40,42) if is_hovered else QColor(30,30,32)))
        border = (QColor(10,132,255,140) if is_selected else (QColor(0,0,0,35) if is_hovered else QColor(0,0,0,15))) if theme == "light" else (QColor(255,255,255,80) if is_selected else (QColor(255,255,255,50) if is_hovered else QColor(255,255,255,20)))
        painter.fillPath(path, bg); painter.setPen(border); painter.drawPath(path)
        if self._flash_alpha > 0 and is_selected:
            fc = QColor(10,132,255,int(50*self._flash_alpha)) if theme == "light" else QColor(255,255,255,int(10*self._flash_alpha))
            fb = QColor(10,132,255,int(120*self._flash_alpha)) if theme == "light" else QColor(255,255,255,int(50*self._flash_alpha))
            painter.fillPath(path, fc); painter.setPen(fb); painter.drawPath(path)
        painter.restore()

class RealTimeMonitorWorker(QThread):
    data_changed = pyqtSignal(list)
    status_changed = pyqtSignal(bool)  # True = MuMuManager ответил валидным JSON, False = недоступен
    INFO_TIMEOUT = 5.0    # "info all" может отвечать дольше 1.5с если запущено много профилей
    FAIL_THRESHOLD = 3    # столько подряд неудачных опросов нужно, прежде чем реально считать MuMu мёртвым
    def __init__(self): super().__init__(); self.running, self.last_data, self.last_ok = True, None, None; self.fail_streak = 0
    def run(self):
        while self.running:
            res = mm_run("info", "-v", "all", timeout=self.INFO_TIMEOUT)
            ok, data = False, None
            if res and res.stdout:
                data = parse_info(res.stdout); ok = data is not None
            if ok:
                self.fail_streak = 0
            else:
                self.fail_streak += 1
                # Один неудачный/долгий опрос ещё ничего не значит - MuMuManager мог
                # просто не успеть ответить под нагрузкой большого кол-ва запущенных
                # профилей. Пока процесс реально жив (tasklist) и лимит попыток не
                # исчерпан - не паникуем и не гасим статус, просто ждём следующий цикл.
                if self.fail_streak < self.FAIL_THRESHOLD and is_mumu_process_alive():
                    time.sleep(REALTIME_POLL_MS / 1000.0)
                    continue
            if ok != self.last_ok: self.last_ok = ok; self.status_changed.emit(ok)
            if ok and data != self.last_data: self.last_data = data; self.data_changed.emit(data)
            time.sleep(REALTIME_POLL_MS / 1000.0)
    def stop(self): self.running = False; self.wait()

class ToggleSwitch(QWidget):
    def __init__(self, parent=None, on_toggle=None, theme="dark"):
        super().__init__(parent); self.setFixedSize(32, 18); self._checked = self._hovered = False; self._circle_position = 2
        self.anim = QPropertyAnimation(self, b"circle_position", self); self.anim.setDuration(100); self.on_toggle = on_toggle; self.theme = theme
    @pyqtProperty(float)
    def circle_position(self): return self._circle_position
    @circle_position.setter
    def circle_position(self, pos): self._circle_position = pos; self.update()
    def isChecked(self): return self._checked
    def setChecked(self, c):
        if self._checked != c: self._checked = c; self.anim.stop(); self.anim.setEndValue(16 if c else 2); self.anim.start()
    def set_theme(self, theme): self.theme = theme; self.update()
    def enterEvent(self, e): self._hovered = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hovered = False; self.update(); super().leaveEvent(e)
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            if self.on_toggle: self.on_toggle(self._checked)
            else:
                p = self.parent()
                while p and not hasattr(p, 'toggle_always_on_top'): p = p.parent()
                p and p.toggle_always_on_top()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); is_light = self.theme == "light"
        off, off_h = ("#D1D1D6", "#C2C2C8") if is_light else ("#333333", "#444444")
        p.setBrush(QColor("#2292FF" if self._checked else off_h) if self._hovered else QColor("#0A84FF" if self._checked else off)); p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(0, 0, self.width(), self.height(), 9, 9)
        if self._hovered or (not self._checked and is_light): p.setPen(QColor(0,0,0,45 if is_light else 20) if self._hovered and is_light else QColor(255,255,255,60) if self._hovered else QColor(0,0,0,20)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRoundedRect(0, 0, self.width()-1, self.height()-1, 9, 9)
        p.setBrush(QColor("#FFFFFF")); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(int(self._circle_position), 2, 14, 14)

class ConfigEditorDialog(QDialog):
    def __init__(self, vm_id, initial_json, is_running=False, parent=None, theme="dark", lang="ru"):
        super().__init__(parent); self.vm_id, self.theme, self.lang, self.is_running = vm_id, theme, lang, is_running
        self.setWindowTitle(f"{tr(lang, 'config_editor_title')}{vm_id}"); self.resize(380, 440)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet(get_dlg_css(theme))
        
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(10)
        
        self.editor = QTextEdit()
        self.editor.setPlainText(initial_json)
        self.editor.setFont(QFont("Consolas", 10))
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.editor.setStyleSheet(f"QTextEdit{{background:{'#FFF' if theme=='light' else '#1C1C1E'};color:{'#1C1C1E' if theme=='light' else '#E0E0E0'};border:1px solid {'#D1D1D6' if theme=='light' else '#333'};border-radius:8px;padding:8px;}}QTextEdit:focus{{border-color:#0A84FF;}}"+get_scroll_css(theme))
        layout.addWidget(self.editor)
        
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color:#FF3B30;font-size:11px;font-weight:600;background:transparent;")
        self.lbl_error.hide()
        layout.addWidget(self.lbl_error)
        
        btn_layout = QHBoxLayout(); btn_layout.setSpacing(8)
        self.btn_cancel = QPushButton(tr(lang, "btn_cancel"))
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton(tr(lang, "close_btn"))
        self.btn_save.setStyleSheet("QPushButton{background:#0A84FF;color:#FFF;font-weight:bold;border:1px solid #0A84FF;}QPushButton:hover{background:#2292FF;}")
        self.btn_save.clicked.connect(self.save_config)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        equalize_buttons(self.btn_cancel, self.btn_save)
        layout.addLayout(btn_layout)

    def save_config(self):
        text = self.editor.toPlainText().strip()
        try:
            parsed = json.loads(text)
            
            # Проверка запущен ли девайс перед сохранением
            if self.is_running:
                mw = self.parent().window() if self.parent() else None
                hasattr(mw, 'set_blur_effect') and mw.set_blur_effect(True)
                try:
                    dlg = ConfirmDialog(
                        tr(self.lang, "single_config_confirm_title"),
                        tr(self.lang, "single_config_confirm_text"),
                        "", self, theme=self.theme, lang=self.lang, has_items=True
                    )
                    if dlg.exec() != QDialog.DialogCode.Accepted:
                        return
                finally:
                    hasattr(mw, 'set_blur_effect') and mw.set_blur_effect(False)
                
                # Выключаем девайс
                mm_shutdown_and_wait(self.vm_id)
                pass

            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
                json.dump(stringify_settings(parsed), f, indent=2, ensure_ascii=False)
                temp_path = f.name
            
            res = mm_run("setting", "-v", self.vm_id, "--path", temp_path)
            try: os.remove(temp_path)
            except Exception: pass
            
            if mm_result_ok(res):
                self.accept()
            else:
                self.lbl_error.setText(f"MuMuManager: {((res.stdout or res.stderr or '').strip() if res else 'Unknown error')}")
                self.lbl_error.show()
        except Exception as e:
            self.lbl_error.setText(f"{tr(self.lang, 'invalid_json')} ({e})")
            self.lbl_error.show()

class BulkConfigEditorDialog(QDialog):
    def __init__(self, mw, theme="dark", lang="ru"):
        super().__init__(mw); self.mw, self.theme, self.lang = mw, theme, lang
        self.setWindowTitle(tr(lang, "bulk_config_title")); self.resize(420, 460)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet(get_dlg_css(theme))

        layout = QVBoxLayout(self); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(10)

        self.hint = QLabel(tr(lang, "bulk_config_hint")); self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:{'#6E6E73' if theme=='light' else '#9A9A9E'};font-size:11px;background:transparent;")
        layout.addWidget(self.hint)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(tr(lang, "bulk_config_placeholder"))
        self.editor.setFont(QFont("Consolas", 10))
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.editor.setStyleSheet(f"QTextEdit{{background:{'#FFF' if theme=='light' else '#1C1C1E'};color:{'#1C1C1E' if theme=='light' else '#E0E0E0'};border:1px solid {'#D1D1D6' if theme=='light' else '#333'};border-radius:8px;padding:8px;}}QTextEdit:focus{{border-color:#0A84FF;}}"+get_scroll_css(theme))
        layout.addWidget(self.editor)

        self.lbl_status = QLabel(""); self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size:11px;font-weight:600;background:transparent;")
        self.lbl_status.hide()
        layout.addWidget(self.lbl_status)

        btn_layout = QHBoxLayout(); btn_layout.setSpacing(8)
        self.btn_cancel = QPushButton(tr(lang, "btn_cancel"))
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_apply = QPushButton(tr(lang, "close_btn"))
        self.btn_apply.setStyleSheet("QPushButton{background:#0A84FF;color:#FFF;font-weight:bold;border:1px solid #0A84FF;}QPushButton:hover{background:#2292FF;}")
        self.btn_apply.clicked.connect(self.confirm_and_apply)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_apply)
        equalize_buttons(self.btn_cancel, self.btn_apply)
        layout.addLayout(btn_layout)

    def _parse_fragment(self, raw_text):
        text = raw_text.strip()
        if not text:
            return None
        candidates = [text]
        if not (text.startswith("{") and text.endswith("}")):
            candidates.append("{" + text.rstrip().rstrip(",") + "}")
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        return False

    def confirm_and_apply(self):
        fragment = self._parse_fragment(self.editor.toPlainText())
        if fragment is None:
            self._show_status(tr(self.lang, "bulk_config_empty"), error=True); return
        if fragment is False or not fragment:
            self._show_status(tr(self.lang, "invalid_json"), error=True); return

        profiles = list(getattr(self.mw, "profiles", []))
        if not profiles:
            self._show_status(tr(self.lang, "bulk_config_empty"), error=True); return

        hasattr(self.mw, 'set_blur_effect') and self.mw.set_blur_effect(True)
        try:
            dlg = ConfirmDialog(
                tr(self.lang, "bulk_config_confirm_title"),
                tr(self.lang, "bulk_config_confirm_text").format(n=len(profiles)),
                "", self, theme=self.theme, lang=self.lang, has_items=True
            )
            proceed = dlg.exec() == QDialog.DialogCode.Accepted
        finally:
            hasattr(self.mw, 'set_blur_effect') and self.mw.set_blur_effect(False)
        if not proceed:
            return

        self.btn_apply.setEnabled(False); self.btn_cancel.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        ok, fail = 0, 0
        try:
            # Остановка всех работающих перед изменением общего конфига
            running_profiles = [p for p in profiles if p.get("running")]
            if running_profiles:
                for p in running_profiles:
                    mm_run("control", "-v", p["id"], "shutdown", timeout=15.0)
                for p in running_profiles: mm_shutdown_and_wait(p["id"])

            for p in profiles:
                vm_id = p.get("id")
                if not vm_id:
                    fail += 1; continue
                try:
                    merged = stringify_settings(fragment)  # setting --path меняет только перечисленные ключи, мерджить с текущим конфигом не нужно
                    temp_path = None
                    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
                        json.dump(merged, f, indent=2)
                        temp_path = f.name
                    apply_res = mm_run("setting", "-v", vm_id, "--path", temp_path)
                    try: os.remove(temp_path)
                    except Exception: pass
                    if mm_result_ok(apply_res):
                        ok += 1
                    else:
                        fail += 1
                except Exception:
                    fail += 1
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_apply.setEnabled(True); self.btn_cancel.setEnabled(True)

        if fail == 0:
            self._show_status(tr(self.lang, "bulk_config_result_ok").format(n=ok), error=False)
        else:
            self._show_status(tr(self.lang, "bulk_config_result_partial").format(ok=ok, fail=fail), error=True)

    def _show_status(self, text, error=True):
        color = "#FF3B30" if error else "#30D158"
        self.lbl_status.setStyleSheet(f"color:{color};font-size:11px;font-weight:600;background:transparent;")
        self.lbl_status.setText(text); self.lbl_status.show()

class SortMenuButton(QPushButton):
    indexChanged = pyqtSignal(int)
    runningFirstChanged = pyqtSignal(bool)
    def __init__(self, parent=None, lang="ru"):
        super().__init__(parent); self._current_index = 0; self._running_first = False; self.lang = lang; self.setFixedHeight(28)
        self.clicked.connect(self.show_sort_menu); self.update_button_text(); self.update_style("dark")
    def update_style(self, theme="dark"): self.setStyleSheet("QPushButton{background-color:#E5E5EA;border:1px solid #D1D1D6;border-radius:8px;color:#1C1C1E;font-size:12px;font-weight:500;padding:2px 8px;text-align:center;}QPushButton:hover{background-color:#D8D8DC;border:1px solid #B0B0B5;}QPushButton:pressed{background-color:#C7C7CC;}" if theme == "light" else "QPushButton{background-color:#222;border:1px solid #3B3B3B;border-radius:8px;color:#CCCCCC;font-size:12px;font-weight:500;padding:2px 8px;text-align:center;}QPushButton:hover{background-color:#222;border:1px solid #666;}QPushButton:pressed{background-color:#1A1A1C;}")
    def currentIndex(self): return self._current_index
    def setCurrentIndex(self, idx): 0 <= idx < len(SORT_OPTIONS) and (setattr(self, '_current_index', idx), self.update_button_text())
    def runningFirst(self): return self._running_first
    def setRunningFirst(self, val): self._running_first = bool(val); self.update_button_text()
    def set_lang(self, lang): self.lang = lang; self.update_button_text()
    def update_button_text(self):
        opt = SORT_OPTIONS[self._current_index]
        prefix = "⚡ " if self._running_first else ""
        self.setText(f"{prefix}{opt['icon'] + '  ' if opt['icon'] else ''}{tr(self.lang, opt['key'])}  ▾")
    def show_sort_menu(self):
        m = self.window()
        hasattr(m, 'set_blur_effect') and m.set_blur_effect(True)
        try:
            lang = getattr(m, 'current_lang', self.lang); theme = getattr(m, 'current_theme', 'dark')
            menu = QMenu(self); menu.setStyleSheet(get_menu_css(theme))
            toggle_btn = QPushButton(f"{'✓  ' if self._running_first else '    '}⚡  {tr(lang, 'sort_running_first')}")
            toggle_btn.setCheckable(True); toggle_btn.setChecked(self._running_first); toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle_btn.setStyleSheet(get_menu_toggle_css(theme))
            toggle_btn.clicked.connect(lambda checked, b=toggle_btn, lg=lang: self._on_running_first_toggled(checked, b, lg))
            wa = QWidgetAction(menu); wa.setDefaultWidget(toggle_btn); menu.addAction(wa)
            menu.addSeparator()
            for idx, opt in enumerate(SORT_OPTIONS):
                act = QAction(f"{'✓  ' if idx == self._current_index else '    '}{opt['icon'] + ' ' if opt['icon'] else ''}{tr(lang, opt['key'])}", menu)
                act.triggered.connect(lambda _, i=idx: self._select_index(i)); menu.addAction(act)
            menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        finally: hasattr(m, 'set_blur_effect') and m.set_blur_effect(False)
    def _on_running_first_toggled(self, checked, btn, lang):
        self._running_first = checked
        btn.setText(f"{'✓  ' if checked else '    '}⚡  {tr(lang, 'sort_running_first')}")
        self.update_button_text(); self.runningFirstChanged.emit(checked)
    def _select_index(self, idx): self._current_index != idx and (setattr(self, '_current_index', idx), self.update_button_text(), self.indexChanged.emit(idx))

class StickerSelectionDialog(QDialog):
    def __init__(self, title, stickers_in_use, parent=None, theme="dark", lang="ru"):
        super().__init__(parent); self.setWindowTitle(title); self.setFixedSize(300, 260); self.theme, self.lang, self.selected_stickers = theme, lang, set()
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint); self.setStyleSheet(get_dlg_css(theme))
        layout = QVBoxLayout(self); scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); scroll_area.setFrameShape(QFrame.Shape.NoFrame); scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"QScrollArea{{background:{'#FFF' if theme=='light' else '#262626'};border:1px solid {'#E5E5EA' if theme=='light' else '#333'};border-radius:8px;}}"+get_scroll_css(theme))
        grid_container = QWidget(); grid_container.setStyleSheet("background:transparent;"); self.buttons = {}
        if not stickers_in_use:
            empty_layout = QVBoxLayout(grid_container); empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.setContentsMargins(15, 15, 15, 15)
            lbl = QLabel(tr(lang, "no_stickers_selected")); lbl.setWordWrap(True); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color:{'#8E8E93' if theme=='light' else '#A0A0A5'};font-size:12px;font-weight:500;padding:12px;margin:10px;")
            empty_layout.addWidget(lbl)
        else:
            grid = QGridLayout(grid_container); grid.setContentsMargins(8, 8, 8, 8); grid.setSpacing(6); grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            for idx, s in enumerate(stickers_in_use):
                btn = QPushButton(s); btn.setFixedSize(32, 32); self.buttons[s] = btn; self._update_btn_style(s); btn.clicked.connect(lambda _, st=s: self._toggle_sticker(st)); grid.addWidget(btn, idx//6, idx%6)
        scroll_area.setWidget(grid_container); layout.addWidget(scroll_area); btn_confirm = QPushButton(tr(lang, "confirm")); btn_confirm.setStyleSheet("QPushButton{background:#0A84FF;color:#FFF;font-weight:bold;border:1px solid #0A84FF;}QPushButton:hover{background:#2292FF;}"); btn_confirm.clicked.connect(self.accept); layout.addWidget(btn_confirm)
    def _toggle_sticker(self, s): self.selected_stickers.remove(s) if s in self.selected_stickers else self.selected_stickers.add(s); self._update_btn_style(s)
    def _update_btn_style(self, s): s in self.buttons and self.buttons[s].setStyleSheet(get_btn_style(self.theme, s in self.selected_stickers))
    def get_selected(self): return list(self.selected_stickers)

class ConfirmDialog(QDialog):
    def __init__(self, title, text, empty_text, parent=None, theme="dark", lang="ru", has_items=True):
        super().__init__(parent); self.setWindowTitle(title); self.setFixedWidth(320); self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        main_layout = QVBoxLayout(self); main_layout.setContentsMargins(0, 0, 0, 0); self.container = QWidget(self)
        self.container.setStyleSheet("QWidget{background:#F6F6F9;color:#1C1C1E;border:1px solid #D1D1D6;border-radius:14px;}QLabel{font-size:12px;font-weight:500;background:transparent;}QPushButton#btnCancel{background:#E5E5EA;border:1px solid #D1D1D6;border-radius:8px;color:#1C1C1E;font-size:13px;font-weight:600;padding:7px;}QPushButton#btnCancel:hover{background:#D8D8DC;border-color:#B0B0B5;}QPushButton#btnDelete{background:#FF3B30;color:#FFF;font-size:13px;font-weight:bold;border:1px solid #FF3B30;border-radius:8px;padding:7px;}QPushButton#btnDelete:hover{background:#FF453A;border-color:#FF6961;}QPushButton#btnDelete:disabled{background:#A1A1A6;color:#E5E5EA;border-color:#A1A1A6;}" if theme == "light" else "QWidget{background:#1E1E1E;color:#FFF;border:1px solid #3A3A3C;border-radius:14px;}QLabel{font-size:12px;font-weight:500;background:transparent;}QPushButton#btnCancel{background:#2C2C2E;border:1px solid #3A3A3C;border-radius:8px;color:#FFF;font-size:13px;font-weight:600;padding:7px;}QPushButton#btnCancel:hover{background:#3A3A3C;border-color:#55555A;}QPushButton#btnDelete{background:#FF3B30;color:#FFF;font-size:13px;font-weight:bold;border:1px solid #FF3B30;border-radius:8px;padding:7px;}QPushButton#btnDelete:hover{background:#FF453A;border-color:#FF6961;}QPushButton#btnDelete:disabled{background:#3A3A3C;color:#666;border-color:#3A3A3C;}")
        layout = QVBoxLayout(self.container); layout.setContentsMargins(18, 16, 18, 16); layout.setSpacing(14)
        lbl = QLabel(text if has_items else empty_text); lbl.setWordWrap(True); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter); lbl.setStyleSheet("padding: 4px 8px;"); layout.addWidget(lbl)
        btn_box = QHBoxLayout(); btn_box.setSpacing(8); self.btn_cancel, self.btn_delete = QPushButton(tr(lang, "btn_cancel")), QPushButton(tr(lang, "btn_confirm_delete"))
        self.btn_cancel.setObjectName("btnCancel"); self.btn_cancel.clicked.connect(self.reject)
        self.btn_delete.setObjectName("btnDelete"); self.btn_delete.clicked.connect(self.accept)
        not has_items and self.btn_delete.setEnabled(False); (self.btn_cancel if not has_items else self.btn_delete).setDefault(True)
        btn_box.addWidget(self.btn_cancel); btn_box.addWidget(self.btn_delete); equalize_buttons(self.btn_cancel, self.btn_delete); layout.addLayout(btn_box); main_layout.addWidget(self.container)
        # Высота подстраивается под текст (у разных языков разная длина), чтобы фраза всегда помещалась целиком
        self.adjustSize(); self.setFixedHeight(max(140, self.height()))

class StickerManagerDialog(QDialog):
    def __init__(self, stickers, parent=None, theme="dark", lang="ru"):
        super().__init__(parent); self.stickers, self.lang, self.theme, self.selected_row = list(stickers), lang, theme, 0
        self.setWindowTitle(tr(lang, "sticker_mgr_title")); self.setFixedSize(320, 420); self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint); self.setStyleSheet(get_dlg_css(theme))
        layout = QVBoxLayout(self); self.scroll_area = QScrollArea(); self.scroll_area.setWidgetResizable(True); self.scroll_area.setFrameShape(QFrame.Shape.NoFrame); self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(f"QScrollArea{{background:{'#FFF' if theme=='light' else '#262626'};border:1px solid {'#E5E5EA' if theme=='light' else '#333'};border-radius:8px;}}"+get_scroll_css(theme))
        layout.addWidget(self.scroll_area)
        self.badge_main = QLabel(tr(lang, "sticker_mgr_badge")); self.badge_main.setAlignment(Qt.AlignmentFlag.AlignCenter); self.badge_main.setStyleSheet("QLabel{background-color:rgba(10,132,255,0.15);color:#0A84FF;border:1px solid rgba(10,132,255,0.35);border-radius:8px;padding:4px 8px;font-size:11px;font-weight:600;}"); self.badge_main.hide(); layout.addWidget(self.badge_main)
        add_box = QHBoxLayout(); self.input_sticker = QLineEdit(); self.input_sticker.setPlaceholderText(tr(lang, "sticker_mgr_placeholder")); btn_add = QPushButton(tr(lang, "sticker_mgr_add")); btn_add.clicked.connect(self.add_sticker); add_box.addWidget(self.input_sticker); add_box.addWidget(btn_add); layout.addLayout(add_box)
        ctrl_box = QHBoxLayout(); ctrl_box.setSpacing(6)
        self.btn_first, self.btn_left, self.btn_right, self.btn_last, self.btn_del = QPushButton("《"), QPushButton("〈"), QPushButton("〉"), QPushButton("》"), QPushButton(tr(lang, "sticker_mgr_delete"))
        for b, tt in zip((self.btn_first, self.btn_left, self.btn_right, self.btn_last), ("tt_first", "tt_left", "tt_right", "tt_last")):
            b.setToolTip(tr(lang, tt)); b.setFixedSize(38, 28); b.setStyleSheet("QPushButton{font-size:14px;font-weight:bold;padding:0;}")
        self.btn_del.setFixedHeight(28)
        self.btn_first.clicked.connect(self.move_to_start); self.btn_left.clicked.connect(self.move_left); self.btn_right.clicked.connect(self.move_right); self.btn_last.clicked.connect(self.move_to_end); self.btn_del.clicked.connect(self.delete_selected)
        for b in (self.btn_first, self.btn_left, self.btn_right, self.btn_last, self.btn_del): ctrl_box.addWidget(b)
        layout.addLayout(ctrl_box); btn_save = QPushButton(tr(lang, "sticker_mgr_save")); btn_save.setStyleSheet("QPushButton{background:#0A84FF;color:#FFF;font-weight:bold;border:1px solid #0A84FF;}QPushButton:hover{background:#2292FF;}"); btn_save.clicked.connect(self.accept); layout.addWidget(btn_save); self.refresh_list()
    def refresh_list(self, sel=None):
        self.selected_row = sel if sel is not None else max(0, min(self.selected_row, len(self.stickers)-1))
        grid_container = QWidget(); grid_container.setStyleSheet("background:transparent;"); grid = QGridLayout(grid_container); grid.setContentsMargins(8, 8, 8, 8); grid.setSpacing(6); grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.buttons = {}
        for idx, s in enumerate(self.stickers):
            btn = QPushButton(s); btn.setFixedSize(32, 32); self.buttons[idx] = btn; self._update_btn_style(idx); btn.clicked.connect(lambda _, i=idx: self.on_selection_changed(i)); grid.addWidget(btn, idx//6, idx%6)
        self.scroll_area.setWidget(grid_container); self.on_selection_changed(self.selected_row)
    def _update_btn_style(self, idx): self.buttons[idx].setStyleSheet(get_btn_style(self.theme, idx == self.selected_row))
    def on_selection_changed(self, row):
        old, self.selected_row = self.selected_row, row; old in self.buttons and self._update_btn_style(old); row in self.buttons and self._update_btn_style(row)
        self.badge_main.setVisible(row == 0); self.btn_first.setEnabled(row > 0); self.btn_left.setEnabled(row > 0); self.btn_right.setEnabled(row < len(self.stickers)-1); self.btn_last.setEnabled(row < len(self.stickers)-1); self.btn_del.setEnabled(len(self.stickers) > 1)
    def add_sticker(self): t = self.input_sticker.text().strip(); t and t not in self.stickers and (self.stickers.append(t), self.refresh_list(len(self.stickers)-1), self.input_sticker.clear())
    def _swap_or_move(self, new_idx, mode="swap"):
        r = self.selected_row
        if mode == "swap":
            self.stickers[r], self.stickers[new_idx] = self.stickers[new_idx], self.stickers[r]
        else:
            item = self.stickers.pop(r)
            self.stickers.insert(new_idx, item)
        self.refresh_list(new_idx)
    def move_left(self): self.selected_row > 0 and self._swap_or_move(self.selected_row-1)
    def move_right(self): self.selected_row < len(self.stickers)-1 and self._swap_or_move(self.selected_row+1)
    def move_to_start(self): self.selected_row > 0 and self._swap_or_move(0, "move")
    def move_to_end(self): self.selected_row < len(self.stickers)-1 and self._swap_or_move(len(self.stickers)-1, "move")
    def delete_selected(self): r = self.selected_row; len(self.stickers) > 1 and (self.stickers.pop(r), self.refresh_list(min(r, len(self.stickers)-1)))

class StickerPickerMenu(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None, stickers=None, note="", on_select_callback=None, on_note_save=None, theme="dark", current_sticker="", lang="ru", note_color="", on_color_save=None, profile_name=""):
        super().__init__(parent)
        self.stickers, self.on_select_callback, self.on_note_save, self.lang = stickers or DEFAULT_STICKERS, on_select_callback, on_note_save, lang
        self.theme, self.on_color_save, self.note_color, self.color_btns = theme, on_color_save, note_color or NOTE_COLORS[0], {}
        self.profile_name = profile_name
        self._app_filter_installed = False
        
        # Без WindowStaysOnTopHint: окно не должно висеть поверх ВСЕХ приложений,
        # когда пользователь переключается на другую программу. Qt.WindowType.Tool
        # уже даёт нужное поведение floating-окна относительно главного окна лаунчера.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._main_window = None
        self._main_filter_installed = False

        try: self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        except Exception: pass
        self.setObjectName("stickerPanelRoot")
        self.panel_bg, self.panel_border = ("#FFFFFF", "#E5E5EA") if theme == "light" else ("#28282C", "#3A3A3C")

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(10, 8, 10, 10)
        vbox.setSpacing(6)
        
        # === ВОТ ЭТА СТРОКА БЛОКИРУЕТ РАСТЯГИВАНИЕ МЕНЮ ===
        vbox.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)

        # Цветовые темы
        if self.theme == 'light':
            bg, fg, focus_bg = '#F2F2F7', '#1C1C1E', '#FFFFFF'
            border_col, focus_border = '#D1D1D6', '#8E8E93'
            scroll_handle = 'rgba(0, 0, 0, 0.25)'
            scroll_hover = 'rgba(0, 0, 0, 0.45)'
        else:
            bg, fg, focus_bg = '#1C1C1E', '#FFFFFF', '#2C2C2E'
            border_col, focus_border = '#3A3A3C', '#636366'
            scroll_handle = 'rgba(255, 255, 255, 0.25)'
            scroll_hover = 'rgba(255, 255, 255, 0.45)'

        # === ВЕРХНИЙ БЛОК: ПРОФИЛЬ ===
        if self.profile_name:
            prof_header = QHBoxLayout(); prof_header.setContentsMargins(0, 0, 0, 0); prof_header.setSpacing(4)
            lbl_prof_title = QLabel(tr(lang, "profile_label")); lbl_prof_title.setStyleSheet("font-size:10px;font-weight:700;letter-spacing:0.8px;color:#8E8E93;background:transparent;")

            self.btn_copy_prof = QPushButton("📋")
            self.btn_copy_prof.setToolTip(tr(lang, "copy") if 'tr' in globals() else "Скопировать имя")
            self.btn_copy_prof.clicked.connect(self._copy_profile_name)

            self.edit_prof_name = QLineEdit(self.profile_name)
            self.edit_prof_name.setReadOnly(True)

            fm = self.edit_prof_name.fontMetrics()
            text_width = fm.horizontalAdvance(self.profile_name) if hasattr(fm, 'horizontalAdvance') else fm.width(self.profile_name)
            self.edit_prof_name.setFixedWidth(text_width + 16)

            self._apply_prof_btn_style()

            prof_header.addWidget(lbl_prof_title)
            prof_header.addStretch()
            prof_header.addWidget(self.btn_copy_prof)
            prof_header.addWidget(self.edit_prof_name)
            vbox.addLayout(prof_header)

            line_prof = QFrame(); line_prof.setFrameShape(QFrame.Shape.HLine); line_prof.setFrameShadow(QFrame.Shadow.Sunken)
            line_prof.setStyleSheet("background-color:rgba(0,0,0,0.1);margin:3px 0;" if theme=="light" else "background-color:rgba(150,150,150,0.2);margin:3px 0;")
            vbox.addWidget(line_prof)

        neat_scroll_css = (
            f"QScrollBar:vertical {{"
            f"  border: none;"
            f"  background: transparent;"
            f"  width: 10px;"
            f"  margin: 4px 2px 4px 2px;"
            f"  border-radius: 5px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {scroll_handle};"
            f"  min-height: 20px;"
            f"  border-radius: 3px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{"
            f"  background: {scroll_hover};"
            f"  border-radius: 3px;"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
            f"  border: none;"
            f"  background: none;"
            f"  height: 0px;"
            f"}}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{"
            f"  border: none;"
            f"  background: transparent;"
            f"}}"
        )

        self.setStyleSheet(f"QWidget#stickerPanelRoot{{background:transparent;border:1px solid {self.panel_border};border-radius:12px;}}")

        # === ВЕРХНИЙ БЛОК: ЗАМЕТКИ И НАСТРОЙКИ ЦВЕТА ===
        note_box = QVBoxLayout(); note_box.setSpacing(4); note_header = QHBoxLayout(); note_header.setContentsMargins(0, 0, 0, 0); note_header.setSpacing(5)
        lbl_title = QLabel(tr(lang, "notes_label")); lbl_title.setStyleSheet("font-size:10px;font-weight:700;letter-spacing:0.8px;color:#8E8E93;background:transparent;")
        note_header.addWidget(lbl_title)

        for c in NOTE_COLORS:
            b = QPushButton(); b.setFixedSize(18, 18); b.setToolTip(c)
            b.clicked.connect(lambda _, col=c: self._pick_color(col)); note_header.addWidget(b); self.color_btns[c] = b

        self.lbl_saved = QLabel("")
        self.lbl_saved.setFixedSize(16, 16)
        self.lbl_saved.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_saved.setStyleSheet("font-size:13px;color:#30D158;font-weight:800;background:transparent;")
        note_header.addWidget(self.lbl_saved); note_header.addStretch(); note_box.addLayout(note_header)

        self.note_edit = QTextEdit()
        self.note_edit.setPlainText(note)
        self.note_edit.setPlaceholderText(tr(lang, "note_placeholder"))
        self.note_edit.setAcceptRichText(False)

        line_height = self.note_edit.fontMetrics().lineSpacing()
        padding_and_margins = 16
        self.note_edit.setFixedHeight(line_height * 4 + padding_and_margins)
        self.note_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.note_edit.setStyleSheet(
            f"QTextEdit{{background:{bg};border:1px solid {border_col};border-radius:8px;padding:6px;font-size:12px;color:{fg};}}"
            f"QTextEdit:focus{{border:1px solid {focus_border};background:{focus_bg};}}"
            + neat_scroll_css
        )

        self.note_edit.textChanged.connect(self._on_text_changed); note_box.addWidget(self.note_edit); vbox.addLayout(note_box)

        # === РАЗДЕЛИТЕЛЬ ===
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFrameShadow(QFrame.Shadow.Sunken); line.setStyleSheet("background-color:rgba(0,0,0,0.1);margin:3px 0;" if theme=="light" else "background-color:rgba(150,150,150,0.2);margin:3px 0;"); vbox.addWidget(line)

        # === НИЖНИЙ БЛОК: СТИКЕРЫ ===
        stickers_header = QHBoxLayout(); stickers_header.setContentsMargins(0, 0, 0, 0)
        lbl_stickers_title = QLabel(tr(lang, "stickers_label")); lbl_stickers_title.setStyleSheet("font-size:10px;font-weight:700;letter-spacing:0.8px;color:#8E8E93;background:transparent;")
        btn_sticker_gear = QPushButton("⚙️"); btn_sticker_gear.setFixedSize(18, 18); btn_sticker_gear.setToolTip(tr(lang, "sticker_mgr_title"))
        btn_sticker_gear.setStyleSheet(f"QPushButton{{background:transparent;border:none;font-size:11px;border-radius:4px;}}QPushButton:hover{{background:rgba({'0,0,0,0.08' if theme=='light' else '255,255,255,0.15'});}}")
        btn_sticker_gear.clicked.connect(self._open_sticker_settings_from_menu)
        stickers_header.addWidget(lbl_stickers_title); stickers_header.addStretch(); stickers_header.addWidget(btn_sticker_gear); vbox.addLayout(stickers_header)

        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); scroll_area.setFrameShape(QFrame.Shape.NoFrame); scroll_area.setMaximumHeight(150); scroll_area.setMinimumWidth(260); scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"QScrollArea{{background:{'#FFF' if theme=='light' else '#262626'};border:1px solid {'#E5E5EA' if theme=='light' else '#333'};border-radius:8px;}}" + neat_scroll_css)

        grid_container = QWidget(); grid_container.setStyleSheet("background:transparent;"); grid = QGridLayout(grid_container); grid.setContentsMargins(6, 6, 6, 6); grid.setSpacing(4); grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        for idx, s in enumerate(self.stickers):
            btn = QPushButton(s); btn.setFixedSize(32, 32); btn.setStyleSheet(get_btn_style(theme, s == current_sticker) + " QPushButton:hover { font-size: 19px; padding: 0; }")
            btn.clicked.connect(lambda _, st=s: (self.on_select_callback and self.on_select_callback(st), self.close())); grid.addWidget(btn, idx//6, idx%6)
        scroll_area.setWidget(grid_container); vbox.addWidget(scroll_area)

        self._refresh_color_btns()

        self.save_timer, self.hide_timer = QTimer(self), QTimer(self)
        self.save_timer.setSingleShot(True); self.save_timer.setInterval(400); self.save_timer.timeout.connect(self._save_note)
        self.hide_timer.setSingleShot(True); self.hide_timer.setInterval(1500); self.hide_timer.timeout.connect(lambda: self.lbl_saved.setText(""))

    def _apply_prof_btn_style(self):
        is_light = self.theme == 'light'
        bg = "rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.08)"
        bg_hover = "rgba(0, 0, 0, 0.10)" if is_light else "rgba(255, 255, 255, 0.16)"
        bg_pressed = "rgba(0, 0, 0, 0.15)" if is_light else "rgba(255, 255, 255, 0.24)"
        border = "rgba(0, 0, 0, 0.08)" if is_light else "rgba(255, 255, 255, 0.10)"
        fg = "#1C1C1E" if is_light else "#F2F2F7"
        sel_bg = "#007AFF" if is_light else "#0A84FF"

        base_style = (
            f"background: {bg};"
            f"border: 1px solid {border};"
            f"border-radius: 6px;"
            f"color: {fg};"
            f"font-family: 'Segoe UI', sans-serif;"
            f"font-size: 11px;"
            f"font-weight: 600;"
            f"padding: 2px 6px;"
        )

        if hasattr(self, 'btn_copy_prof'):
            self.btn_copy_prof.setStyleSheet(
                f"QPushButton {{ {base_style} }}"
                f"QPushButton:hover {{ background: {bg_hover}; color: {sel_bg}; }}"
                f"QPushButton:pressed {{ background: {bg_pressed}; }}"
            )

        if hasattr(self, 'edit_prof_name'):
            self.edit_prof_name.setStyleSheet(
                f"QLineEdit {{ {base_style} selection-background-color: {sel_bg}; selection-color: #FFFFFF; }}"
            )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(self.panel_bg))
        painter.setPen(QPen(QColor(self.panel_border), 1))
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, 12, 12)
        super().paintEvent(event)

    def show_at(self, global_pos):
        self.adjustSize()

        parent_widget = self.parentWidget()
        main_window = parent_widget.window() if parent_widget else None
        self._main_window = main_window

        cursor_offset = 10
        padding = 35

        if main_window:
            main_global_pos = main_window.mapToGlobal(QPoint(0, 0))
            main_left = main_global_pos.x()
            main_top = main_global_pos.y()
            main_right = main_left + main_window.width()
            main_bottom = main_top + main_window.height()

            x = main_left + (main_window.width() - self.width()) // 2
            y = global_pos.y() - self.height() - cursor_offset

            x = min(max(x, main_left + padding), max(main_left + padding, main_right - self.width() - padding))
            y = min(max(y, main_top + padding), max(main_top + padding, main_bottom - self.height() - padding))
        else:
            x = global_pos.x()
            y = global_pos.y() - self.height() - cursor_offset

            screen = QApplication.screenAt(QPoint(x, y)) or self.screen() or QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                x = min(max(x, avail.left() + padding), max(avail.left() + padding, avail.right() - self.width() - padding))
                y = min(max(y, avail.top() + padding), max(avail.top() + padding, avail.bottom() - self.height() - padding))

        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()

        if not self._app_filter_installed: 
            QApplication.instance().installEventFilter(self)
            self._app_filter_installed = True

        # Следим за передвижением/сворациванием/закрытием главного окна лаунчера,
        # чтобы окно заметки не оставалось висеть на старом месте, когда лаунчер двигается.
        if self._main_window is not None and not self._main_filter_installed:
            self._main_window.installEventFilter(self)
            self._main_filter_installed = True

    def eventFilter(self, obj, event):
        if obj is self._main_window and event.type() in (QEvent.Type.Move, QEvent.Type.WindowStateChange, QEvent.Type.Close):
            if self.isVisible():
                self.close()
            return False
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            gp = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            if not self.frameGeometry().contains(gp):
                self.close()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape: self.close()
        else: super().keyPressEvent(e)

    def _copy_profile_name(self):
        if hasattr(self, 'btn_copy_prof'):
            QApplication.clipboard().setText(self.profile_name)
            self.btn_copy_prof.setText("✓")
            QTimer.singleShot(250, self._reset_profile_name_btn)

    def _reset_profile_name_btn(self):
        if hasattr(self, 'btn_copy_prof'):
            self.btn_copy_prof.setText("📋")

    def _open_sticker_settings_from_menu(self):
        self.close()
        # Безопасный поиск метода open_sticker_settings вверх по иерархии родителей
        target = self.parent()
        while target is not None:
            if hasattr(target, 'open_sticker_settings') and callable(getattr(target, 'open_sticker_settings')):
                target.open_sticker_settings()
                return
            target = target.parent() if hasattr(target, 'parent') else None

    def _pick_color(self, color):
        self.note_color = color; self._refresh_color_btns(); self.on_color_save and self.on_color_save(color); self.close()

    def _refresh_color_btns(self):
        ring = "#1C1C1E" if self.theme == "light" else "#FFFFFF"
        for c, b in self.color_btns.items():
            sel = (c == self.note_color)
            border = f"border:2px solid {ring};" if sel else "border:2px solid transparent;"
            b.setStyleSheet(
                f"QPushButton{{background:{c};{border}border-radius:7px;margin:2px;}}"
                f"QPushButton:hover{{margin:0px;border-radius:9px;}}"
            )

    def _on_text_changed(self): self.save_timer.start()
    
    def _save_note(self):
        self.save_timer.isActive() and self.save_timer.stop()
        self.on_note_save and (self.on_note_save(self.note_edit.toPlainText().strip()), self.lbl_saved.setText("✓"), self.hide_timer.start())
        
    def closeEvent(self, e):
        if self._app_filter_installed: QApplication.instance().removeEventFilter(self); self._app_filter_installed = False
        if self._main_filter_installed and self._main_window is not None:
            self._main_window.removeEventFilter(self); self._main_filter_installed = False
        self.save_timer.isActive() and self._save_note()
        super().closeEvent(e); self.closed.emit()

class LanguagePickerMenu(QMenu):
    def __init__(self, parent=None, current_lang="ru", theme="dark", on_select=None):
        super().__init__(parent); self.theme, self.current_lang, self.on_select = theme, current_lang, on_select; self.setStyleSheet(get_menu_css(theme))
        cnt = QWidget(); cnt.setStyleSheet("QWidget{background:transparent;border:none;}"); vbox = QVBoxLayout(cnt); vbox.setContentsMargins(6, 6, 6, 6); vbox.setSpacing(6)
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText(tr(current_lang, "language_search_placeholder"))
        self.search_input.setStyleSheet(f"QLineEdit{{background:{'#FFF' if theme=='light' else '#1C1C1E'};border:1px solid {'#D1D1D6' if theme=='light' else '#3A3A3C'};border-radius:8px;padding:6px 8px;font-size:12px;color:{'#1C1C1E' if theme=='light' else '#FFF'};}}QLineEdit:focus{{border-color:#0A84FF;}}")
        self.search_input.textChanged.connect(self._filter); vbox.addWidget(self.search_input)
        list_container = QWidget(); list_container.setStyleSheet("background:transparent;"); self.list_layout = QVBoxLayout(list_container); self.list_layout.setContentsMargins(0, 0, 0, 0); self.list_layout.setSpacing(2)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame); scroll.setMaximumHeight(190); scroll.setMinimumWidth(220); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); scroll.setStyleSheet(get_scroll_css(theme))
        self.entries = []
        for code, flag, native, en_name in LANGUAGES:
            btn = QPushButton(f"{flag}  {native}"); btn.setFixedHeight(30); btn.setStyleSheet(self._btn_style(code == current_lang))
            btn.clicked.connect(lambda _, c=code: self._pick(c)); self.list_layout.addWidget(btn); self.entries.append((btn, code, native.lower(), en_name.lower()))
        self.list_layout.addStretch(); scroll.setWidget(list_container); vbox.addWidget(scroll); act = QWidgetAction(self); act.setDefaultWidget(cnt); self.addAction(act)
    def _btn_style(self, sel):
        if sel: return "QPushButton{background:#0A84FF;border:1px solid #0A84FF;color:#FFF;border-radius:8px;font-size:13px;text-align:left;padding:4px 10px;}QPushButton:hover{background:#2292FF;border:1px solid #4DA8FF;}"
        return "QPushButton{background:#F2F2F7;border:1px solid #E5E5EA;color:#1C1C1E;border-radius:8px;font-size:13px;text-align:left;padding:4px 10px;}QPushButton:hover{background:#E5E5EA;border:1px solid #D1D1D6;}" if self.theme == "light" else "QPushButton{background:#242426;border:1px solid #333;color:#FFF;border-radius:8px;font-size:13px;text-align:left;padding:4px 10px;}QPushButton:hover{background:#2E2E30;border:1px solid #444;}"
    def _filter(self, text):
        q = text.lower().strip()
        for btn, code, native_l, en_l in self.entries: btn.setVisible(q in native_l or q in en_l or q in code)
    def _pick(self, code): self.on_select and self.on_select(code); self.close()
    def showEvent(self, e): super().showEvent(e); QTimer.singleShot(0, self.search_input.setFocus)
    def mousePressEvent(self, e): not self.rect().contains(e.pos()) and super().mousePressEvent(e)
    def mouseReleaseEvent(self, e): not self.rect().contains(e.pos()) and super().mouseReleaseEvent(e)

class ProfileItemWidget(QWidget):
    def __init__(self, profile, current_sticker, note, on_launch, on_stop, on_sticker_change, on_note_change, get_stickers_list, on_save_stickers, show_id=True, pending=False, on_check_change=None, checked=False, note_color="", on_note_color_change=None):
        super().__init__(); self.setFixedHeight(42); self.profile, self.current_sticker, self.note, self.on_launch, self.on_stop = profile, current_sticker, note, on_launch, on_stop; self.on_sticker_change, self.on_note_change, self.get_stickers_list, self.on_save_stickers = on_sticker_change, on_note_change, get_stickers_list, on_save_stickers; self.pending, self._spinner_idx = False, 0; self.on_check_change = on_check_change; self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.note_color, self.on_note_color_change = note_color or NOTE_COLORS[0], on_note_color_change
        layout = QHBoxLayout(self); layout.setContentsMargins(8, 0, 8, 0); layout.setSpacing(6); layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.btn_check = QPushButton("✓"); self.btn_check.setCheckable(True); self.btn_check.setFixedSize(18, 18); self.btn_check.setChecked(checked); self.btn_check.toggled.connect(self._on_check_toggled)
        self.btn_sticker = QPushButton(self.current_sticker); self.btn_sticker.setFixedSize(26, 26); self.btn_sticker.clicked.connect(self.show_sticker_menu)
        self.label = QLabel(); self.label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft); self.spinner_label = QLabel(SPINNER_FRAMES[0]); self.spinner_label.setFixedSize(26, 26); self.spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.spinner_label.setStyleSheet("color:#FFD60A;font-size:14px;background:transparent;padding:0;margin:0;"); self.spinner_label.hide()
        self.spinner_timer = QTimer(self); self.spinner_timer.setInterval(80); self.spinner_timer.timeout.connect(self._tick_spinner); bstyle = "border-radius:8px;font-size:14px;font-weight:bold;font-family:'Segoe UI',sans-serif;padding:0;margin:0;"
        self.btn_open = QPushButton("↗"); self.btn_open.setFixedSize(26, 26); self.btn_open.setStyleSheet(f"QPushButton{{background:rgba(48,209,88,0.25);color:#30D158;border:1px solid rgba(48,209,88,0.6);{bstyle}}}QPushButton:hover{{background:rgba(48,209,88,0.45);color:#34C759;border:1px solid rgba(48,209,88,0.8);}}"); self.btn_open.clicked.connect(lambda: self.on_launch(self.profile["id"]))
        self.btn_action = QPushButton(); self.btn_action.setFixedSize(26, 26); self.btn_action.clicked.connect(lambda: self.on_stop(self.profile["id"]) if self.profile["running"] else self.on_launch(self.profile["id"]))
        
        self.btn_more = QPushButton("⋮")
        self.btn_more.setFixedSize(26, 26)
        self.btn_more.clicked.connect(self.show_more_menu)

        for w, flag in ((self.btn_check, 0), (self.btn_sticker, 0), (self.label, 1), (self.spinner_label, 0), (self.btn_open, 0), (self.btn_action, 0), (self.btn_more, 0)): layout.addWidget(w, flag, Qt.AlignmentFlag.AlignVCenter)
        self.update_data(profile, current_sticker, note, show_id, pending)
    def _on_check_toggled(self, checked): self.on_check_change and self.on_check_change(self.profile["id"], checked)
    def set_checked_silent(self, checked):
        self.btn_check.blockSignals(True); self.btn_check.setChecked(checked); self.btn_check.blockSignals(False)
    def mousePressEvent(self, e):
        m = self.window()
        if hasattr(m, 'list_widget'):
            for i in range(m.list_widget.count()):
                item = m.list_widget.item(i)
                if m.list_widget.itemWidget(item) == self: m.list_widget.setCurrentItem(item); break
        super().mousePressEvent(e)
    def _tick_spinner(self): self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER_FRAMES); self.spinner_label.setText(SPINNER_FRAMES[self._spinner_idx])
    def update_data(self, profile, current_sticker, note, show_id=True, pending=False, note_color=""):
        self.profile, self.note = profile, note
        note_color and setattr(self, 'note_color', note_color)
        self.current_sticker != current_sticker and (setattr(self, 'current_sticker', current_sticker), self.btn_sticker.setText(current_sticker))
        show_sp = pending and not profile["running"]; self.pending = show_sp
        show_sp and not self.spinner_timer.isActive() and (setattr(self, '_spinner_idx', 0), self.spinner_timer.start())
        not show_sp and self.spinner_timer.isActive() and self.spinner_timer.stop()
        self.spinner_label.setVisible(show_sp); self.btn_action.setVisible(not show_sp)
        m = self.window(); is_light = getattr(m, 'current_theme', 'dark') == 'light' if m and hasattr(m, 'current_theme') else False; lang = getattr(m, 'current_lang', 'ru') if m else 'ru'
        self.btn_check.setStyleSheet(get_checkbox_css('light' if is_light else 'dark'))
        if self.note:
            base_color = QColor(self.note_color or NOTE_COLORS[0])
            r, g, b = base_color.red(), base_color.green(), base_color.blue()

            if is_light:
                bg = f"rgba({r}, {g}, {b}, 0.35)"
                br = f"rgba({r}, {g}, {b}, 0.82)"
                hov = f"rgba({r}, {g}, {b}, 0.51)"
            else:
                bg = f"rgba({r}, {g}, {b}, 0.23)"
                br = f"rgba({r}, {g}, {b}, 0.78)"
                hov = f"rgba({r}, {g}, {b}, 0.39)"

            self.btn_sticker.setStyleSheet(f"QPushButton{{background:{bg};border:1px solid {br};border-radius:8px;font-size:14px;padding:0;margin:0;}}QPushButton:hover{{background:{hov};border-color:{br};}}"); self.btn_sticker.setToolTip(f"{tr(lang, 'note_tooltip_prefix')}{self.note}")
        else: self.btn_sticker.setStyleSheet(f"QPushButton{{background:transparent;border:none;font-size:14px;padding:0;margin:0;}}QPushButton:hover{{background:{'rgba(0,0,0,0.08)' if is_light else 'rgba(255,255,255,0.15)'};border-radius:8px;}}"); self.btn_sticker.setToolTip("")
        self.label.setText(f"[ID: {profile['id']}]  {profile['name']}" if show_id else profile['name']); self.label.setStyleSheet(f"color:{'#1C1C1E' if is_light else '#FFF'};font-size:13px;background:transparent;padding:0;margin:0;border:none;")
        run = profile["running"]; self.btn_open.setVisible(run); self.btn_action.setText("⏹" if run else "▶")
        c1, c2, b1 = ("255,59,48", "#FF3B30", "#FF453A") if run else ("48,209,88", "#30D158", "#34C759")
        self.btn_action.setStyleSheet(f"QPushButton{{background:rgba({c1},0.25);color:{c2};border:1px solid rgba({c1},0.6);border-radius:8px;font-size:13px;font-weight:bold;font-family:'Segoe UI',sans-serif;padding:0;margin:0;}}QPushButton:hover{{background:rgba({c1},0.45);color:{b1};border:1px solid rgba({c1},0.8);}}")
        self.btn_more.setStyleSheet(f"QPushButton{{background:transparent;border:none;color:{'#8E8E93' if is_light else '#A0A0A5'};font-size:16px;font-weight:bold;padding:0;margin:0;}}QPushButton:hover{{color:{'#1C1C1E' if is_light else '#FFF'};background:{'rgba(0,0,0,0.06)' if is_light else 'rgba(255,255,255,0.1)'};border-radius:8px;}}")
    def show_sticker_menu(self):
        m = self.window(); hasattr(m, 'set_blur_effect') and m.set_blur_effect(True)
        # Если заметки нет, берем последний глобальный цвет (или дефолтный)
        eff_color = self.note_color if self.note else getattr(m, 'global_note_color', NOTE_COLORS[0])

        def handle_color(c):
            # Всегда сохраняем цвет как последний выбранный (глобально)
            m.global_note_color = c
            if hasattr(m, 'config') and hasattr(m, 'save_config'):
                m.config['global_note_color'] = c
                m.save_config()

            # Если заметка есть, также применяем цвет для этого профиля
            if self.note:
                self.note_color = c
                self.on_note_color_change and self.on_note_color_change(self.profile["id"], c)

        def handle_note(n):
            self.note = n
            if n:
                # Как только появилась заметка - сохраняем текущий цвет меню для этого профиля
                self.note_color = menu.note_color 
                self.on_note_color_change and self.on_note_color_change(self.profile["id"], self.note_color)
            else:
                # Если заметку стерли - сбрасываем персональный цвет
                self.note_color = ""
                self.on_note_color_change and self.on_note_color_change(self.profile["id"], "")
            self.on_note_change(self.profile["id"], n)

        def handle_sticker(s):
            # Пока меню открыто, filter_list() (вызывается из handle_note) может пересоздать список
            # и уничтожить этот виджет строки вместе с кнопкой. Тогда трогать btn_sticker нельзя -
            # иначе RuntimeError: wrapped C/C++ object ... has been deleted.
            self.current_sticker = s
            if not sip.isdeleted(self) and not sip.isdeleted(self.btn_sticker): self.btn_sticker.setText(s)
            self.on_sticker_change(self.profile["id"], s)

        menu = StickerPickerMenu(m, self.get_stickers_list(), self.note, handle_sticker, handle_note, theme=getattr(m, 'current_theme', 'dark'), current_sticker=self.current_sticker, lang=getattr(m, 'current_lang', 'ru'), note_color=eff_color, on_color_save=handle_color, profile_name=self.profile.get("name", ""))
        # Окно не модальное (чтобы не закрываться при переключении приложений),
        # поэтому блюр главного окна снимаем по сигналу закрытия, а не в finally.
        menu.closed.connect(lambda: not QApplication.activeModalWidget() and hasattr(m, 'set_blur_effect') and m.set_blur_effect(False))
        menu.show_at(self.btn_sticker.mapToGlobal(self.btn_sticker.rect().bottomLeft()))
    def show_more_menu(self):
        m = self.window(); hasattr(m, 'set_blur_effect') and m.set_blur_effect(True)
        try:
            menu = QMenu(self); menu.setStyleSheet(get_menu_css(getattr(m, 'current_theme', 'dark')))
            lang = getattr(m, 'current_lang', 'ru')
            is_running = self.profile.get("running", False)
            
            # 1. Изменить конфиг
            act_edit = menu.addAction(f"⚙️  {tr(lang, 'edit_config')}")
            act_edit.triggered.connect(self._open_config_editor)
            
            # 2. Клон (доступен и на запущенном устройстве — перед клонированием оно будет выключено)
            act_clone = menu.addAction(f"📋  {tr(lang, 'clone_profile')}")
            act_clone.triggered.connect(self._clone_profile)
            
            menu.addSeparator()
            
            # 3. Удалить (доступен и на запущенном устройстве — перед удалением оно будет выключено)
            act_delete = menu.addAction(f"🗑️  {tr(lang, 'delete_profile')}")
            act_delete.triggered.connect(self._delete_profile)
            
            top_right = self.btn_more.mapToGlobal(QPoint(self.btn_more.width(), self.btn_more.height()))
            pos = top_right + QPoint(-menu.sizeHint().width(), 0)
            menu.exec(pos)
        finally: hasattr(m, 'set_blur_effect') and m.set_blur_effect(False)

    def _clone_profile(self):
        m = self.window()
        vm_id = self.profile["id"]
        is_running = self.profile.get("running", False)
        lang = getattr(m, 'current_lang', 'ru')
        theme = getattr(m, 'current_theme', 'dark')

        if is_running:
            # Устройство запущено — предупреждаем, что для клонирования оно будет выключено автоматически
            hasattr(m, 'set_blur_effect') and m.set_blur_effect(True)
            try:
                dlg = ConfirmDialog(
                    tr(lang, "confirm_clone_profile_title"),
                    tr(lang, "confirm_clone_profile_text"),
                    "",
                    m, theme=theme, lang=lang, has_items=True
                )
                proceed = dlg.exec() == QDialog.DialogCode.Accepted
            finally:
                not QApplication.activeModalWidget() and hasattr(m, 'set_blur_effect') and m.set_blur_effect(False)
            if not proceed:
                return

            mm_shutdown_and_wait(vm_id)

        mm_run_bg("clone", "-v", vm_id)

    def _delete_profile(self):
        m = self.window()
        vm_id = self.profile["id"]
        is_running = self.profile.get("running", False)
        hasattr(m, 'set_blur_effect') and m.set_blur_effect(True)
        try:
            lang = getattr(m, 'current_lang', 'ru')
            theme = getattr(m, 'current_theme', 'dark')
            dlg = ConfirmDialog(
                tr(lang, "confirm_delete_profile_title"),
                tr(lang, "confirm_delete_profile_text").format(name=self.profile.get("name", vm_id)),
                "",
                m, theme=theme, lang=lang, has_items=True
            )
            proceed = dlg.exec() == QDialog.DialogCode.Accepted
        finally:
            not QApplication.activeModalWidget() and hasattr(m, 'set_blur_effect') and m.set_blur_effect(False)

        if not proceed:
            return

        if is_running:
            mm_shutdown_and_wait(vm_id)

        res = mm_run("delete", "-v", vm_id, timeout=60.0)
        if mm_result_ok(res):
            vm_id_s = str(vm_id)
            if hasattr(m, 'stickers_map'): m.stickers_map.pop(vm_id_s, None)
            if hasattr(m, 'notes_map'): m.notes_map.pop(vm_id_s, None)
            if hasattr(m, 'notes_colors_map'): m.notes_colors_map.pop(vm_id_s, None)
            if hasattr(m, 'launching_ids'): m.launching_ids.pop(vm_id_s, None)
            if hasattr(m, 'profiles'): m.profiles = [p for p in m.profiles if p["id"] != vm_id_s]
            hasattr(m, 'save_config') and m.save_config()
            hasattr(m, 'filter_list') and m.filter_list()

    def _open_config_editor(self):
        m = self.window()
        res = mm_run("setting", "-v", self.profile["id"], "--all_writable")
        if res and res.stdout:
            try:
                data = json.loads(res.stdout)
                config_json = data
                formatted = json.dumps(config_json, indent=2, ensure_ascii=False)
                hasattr(m, 'set_blur_effect') and m.set_blur_effect(True)
                try:
                    dlg = ConfigEditorDialog(self.profile["id"], formatted, is_running=self.profile.get("running", False), parent=m, theme=getattr(m, 'current_theme', 'dark'), lang=getattr(m, 'current_lang', 'ru'))
                    dlg.exec()
                finally: hasattr(m, 'set_blur_effect') and m.set_blur_effect(False)
            except Exception as e: QMessageBox.warning(m, "MuMuManager", f"Config parsing error: {e}\n\n{(res.stdout or '')[:500]}")
    def mouseDoubleClickEvent(self, e): e.button() == Qt.MouseButton.LeftButton and self.childAt(e.pos()) not in (self.btn_sticker, self.btn_open, self.btn_action, self.btn_more, self.btn_check) and self.on_launch(self.profile["id"]); super().mouseDoubleClickEvent(e)

class SettingsDialog(QDialog):
    def __init__(self, mw, theme="dark", lang="ru"):
        super().__init__(mw); self.mw, self.theme, self.lang = mw, theme, lang; self._pending_pin = mw.always_on_top; self.setWindowTitle(tr(lang, "settings_title")); self.setFixedSize(300, 260)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint); layout = QVBoxLayout(self); layout.setSpacing(12)
        row_pin = QHBoxLayout(); self.lbl_pin = QLabel(tr(lang, "always_on_top")); self.toggle_pin = ToggleSwitch(self, on_toggle=self._on_pin_toggle, theme=theme); self.toggle_pin.setChecked(mw.always_on_top); row_pin.addWidget(self.lbl_pin); row_pin.addStretch(); row_pin.addWidget(self.toggle_pin); layout.addLayout(row_pin)
        row_theme = QHBoxLayout(); self.lbl_theme = QLabel(tr(lang, "theme_label")); self.btn_theme = QPushButton(); self.btn_theme.setMinimumHeight(30); self.btn_theme.clicked.connect(self._toggle_theme); row_theme.addWidget(self.lbl_theme); row_theme.addStretch(); row_theme.addWidget(self.btn_theme); layout.addLayout(row_theme)
        row_lang = QHBoxLayout(); self.lbl_lang = QLabel(tr(lang, "language_label")); self.btn_lang = QPushButton(); self.btn_lang.setFixedHeight(30); self.btn_lang.clicked.connect(self._open_language_menu); row_lang.addWidget(self.lbl_lang); row_lang.addStretch(); row_lang.addWidget(self.btn_lang)
        layout.addLayout(row_lang); self.line = QFrame(); self.line.setFrameShape(QFrame.Shape.HLine); self.line.setFrameShadow(QFrame.Shadow.Sunken); layout.addWidget(self.line)
        self.btn_bulk_config = QPushButton(); self.btn_bulk_config.clicked.connect(self._open_bulk_config); layout.addWidget(self.btn_bulk_config)
        layout.addStretch(); self.btn_close = QPushButton(); self.btn_close.setObjectName("btnClose"); self.btn_close.clicked.connect(self.accept); layout.addWidget(self.btn_close)
        self.lbl_credit = QLabel("• MuMu LaunheR v3.6 | Made by @clickrisk •"); self.lbl_credit.setAlignment(Qt.AlignmentFlag.AlignCenter); self.lbl_credit.setStyleSheet("color:#8E8E93;font-size:11px;font-weight:500;background:transparent;"); layout.addWidget(self.lbl_credit)
        self.finished.connect(self._apply_pending_pin); self._apply_theme_style(); self._refresh_texts()
    def showEvent(self, e): super().showEvent(e); self._apply_theme_style(); self._refresh_texts(); self.layout().invalidate(); self.layout().activate()
    def _apply_theme_style(self):
        sb = "QPushButton#btnClose{background:#0A84FF;color:#FFF;font-weight:bold;border:1px solid #0A84FF;}QPushButton#btnClose:hover{background:#2292FF;border-color:#4DA8FF;}"
        self.setStyleSheet(("QDialog{background:#F6F6F9;color:#1C1C1E;border-radius:10px;}QLabel{background:transparent;}QPushButton{background:#E5E5EA;border:1px solid #D1D1D6;border-radius:8px;color:#1C1C1E;padding:6px;}QPushButton:hover{background:#D8D8DC;border-color:#B0B0B5;}" if self.theme == "light" else "QDialog{background:#1E1E1E;color:#FFF;border-radius:10px;}QLabel{background:transparent;}QPushButton{background:#2C2C2C;border:1px solid #3A3A3A;border-radius:8px;color:#FFF;padding:6px;}QPushButton:hover{background:#3A3A3A;border-color:#55555A;}")+sb+get_scroll_css(self.theme))
        self.line.setStyleSheet("background-color:rgba(0,0,0,0.1);margin:2px 0;" if self.theme == "light" else "background-color:rgba(150,150,150,0.2);margin:2px 0;"); self.toggle_pin.set_theme(self.theme)
    def _refresh_texts(self):
        self.setWindowTitle(tr(self.lang, "settings_title")); self.lbl_pin.setText(tr(self.lang, "always_on_top")); self.lbl_theme.setText(tr(self.lang, "theme_label"))
        self.btn_theme.setText(("🌙 " + tr(self.lang, "theme_dark")) if self.theme == "dark" else ("☀️ " + tr(self.lang, "theme_light")))
        self.lbl_lang.setText(tr(self.lang, "language_label")); flag, native, _ = LANG_INFO.get(self.lang, LANG_INFO["en"]); self.btn_lang.setText(f"{flag} {native} ▾"); self.btn_close.setText(tr(self.lang, "close_btn"))
        self.btn_bulk_config.setText(f"⚙️  {tr(self.lang, 'bulk_config_btn')}")
    def _on_pin_toggle(self, checked): self._pending_pin = checked
    def _apply_pending_pin(self, *_): self._pending_pin != self.mw.always_on_top and self.mw.set_always_on_top(self._pending_pin)
    def _toggle_theme(self): self.mw.toggle_theme(); self.theme = self.mw.current_theme; self._apply_theme_style(); self._refresh_texts()
    def _open_language_menu(self): LanguagePickerMenu(self, current_lang=self.lang, theme=self.theme, on_select=self._set_lang).exec(self.btn_lang.mapToGlobal(self.btn_lang.rect().bottomLeft()))
    def _open_bulk_config(self):
        dlg = BulkConfigEditorDialog(self.mw, theme=self.theme, lang=self.lang)
        dlg.exec()
    def _set_lang(self, code): code != self.lang and (self.mw.set_lang(code), setattr(self, 'lang', self.mw.current_lang), self._apply_theme_style(), self._refresh_texts())

class MuMU(QWidget):
    def __init__(self):
        super().__init__(); self.config = self.load_config()
        # Мгновенно показываем профили из локального кеша; монитор фоново
        # обновит их через MuMuManager.
        self.profiles = [{"name": p.get("name", "Unknown"), "id": p.get("id", ""), "running": False} for p in (self.config.get("cached_profiles", []) or [])]
        self.current_theme = self.config.get("theme", "dark"); self.current_lang = self.config.get("lang", "ru") if self.config.get("lang", "ru") in TR else "ru"
        self.always_on_top = self.config.get("always_on_top", False)
        # Всё про профиль лежит в одной записи: {"name","id","checked","sticker","note","note_color"}.
        # Старые отдельные словари stickers/notes/notes_colors читаем только для миграции.
        self.stickers_map, self.notes_map, self.notes_colors_map = dict(self.config.get("stickers", {}) or {}), dict(self.config.get("notes", {}) or {}), dict(self.config.get("notes_colors", {}) or {})
        _checked = set()
        for _p in (self.config.get("cached_profiles", []) or []):
            _id = str(_p.get("id", ""))
            _p.get("checked") and _checked.add(_id)
            _p.get("sticker") and self.stickers_map.__setitem__(_id, _p["sticker"])
            _p.get("note") and self.notes_map.__setitem__(_id, _p["note"])
            _p.get("note_color") and self.notes_colors_map.__setitem__(_id, _p["note_color"])
        self.last_note_color = self.config.get("last_note_color", NOTE_COLORS[0])
        self.available_stickers = self.config.get("available_stickers", list(DEFAULT_STICKERS)) or ["∙"]
        _old_idx = self.config.get("sort_index", 1)
        if "running_first" not in self.config and "sort_index" in self.config:
            # миграция со старой схемы (0=было "сначала запущенные"+имя, 1..4=имя/ID)
            self.saved_running_first, self.saved_sort_index = (_old_idx == 0), max(0, _old_idx - 1)
        else:
            self.saved_running_first, self.saved_sort_index = self.config.get("running_first", False), _old_idx
        self.launching_ids, self.is_blurred = {}, False; self.selected_ids, self._visible_ids = _checked, []; self._hover_btn = None
        self.mumu_reachable = False  # ещё не было ни одного успешного ответа от MuMuManager
        # Очередь запуска (dict сохраняет порядок): vm_id -> время постановки. Профили уходят в MuMuManager
        # по одному, строго не чаще чем раз в LAUNCH_STAGGER_SEC, и только когда MuMu полностью готов.
        self.pending_boot_ids = {}
        self.mumu_ready = False       # MuMu поднялся: MuMuManager ответил валидным JSON
        self._ready_at = 0.0          # когда MuMu стал "готов" (от этого момента отсчитываем LAUNCH_STAGGER_SEC)
        self._last_open_ts = 0.0      # когда последний раз ушла команда open
        self._last_wake_ts = 0.0      # когда последний раз будили приложение MuMu
        self._cold_ids = set()        # профили, поставленные в очередь пока MuMu не был готов (проверяем, что реально стартовали)
        self._open_attempts = {}      # vm_id -> сколько повторных open уже было
        self.open_verify = {}         # vm_id -> время отправки open (для проверки "холодных" запусков)
        self._kill_guard = {}         # vm_id -> до какого времени гасим профиль, если он всё-таки поднялся после Stop
        self._kill_last = {}          # vm_id -> когда последний раз слали close из-за kill_guard
        self.initUI()
        self.always_on_top and self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True); self.apply_theme()
        self.monitor = RealTimeMonitorWorker(); self.monitor.data_changed.connect(self._on_profiles_fetched); self.monitor.status_changed.connect(self._on_mumu_status_changed); self.monitor.start()
        self.launch_dispatch_timer = QTimer(self); self.launch_dispatch_timer.setInterval(50); self.launch_dispatch_timer.timeout.connect(self._dispatch_launch_queue); self.launch_dispatch_timer.start()
        self.mouse_poll_timer = QTimer(self); self.mouse_poll_timer.setInterval(30); self.mouse_poll_timer.timeout.connect(self._track_global_mouse); self.mouse_poll_timer.start()
        # Отдельный сторож для "зависшего" спиннера: _on_profiles_fetched вызывается
        # только когда монитор реально увидел ИЗМЕНЕНИЕ данных от MuMuManager. Если
        # профиль не стартовал и список процессов не поменялся, этот сигнал может
        # вообще не прийти - и тогда таймаут внутри _on_profiles_fetched никогда не
        # сработает, а спиннер будет крутиться вечно. Этот таймер не зависит от
        # событий monitor'а и сам гарантированно снимает "pending" по истечении
        # LAUNCH_PENDING_TIMEOUT, независимо от того, что говорит MuMuManager.
        self.launch_watchdog_timer = QTimer(self); self.launch_watchdog_timer.setInterval(500); self.launch_watchdog_timer.timeout.connect(self._check_launch_timeouts); self.launch_watchdog_timer.start()
    def _wake_mumu(self):
        now = time.time()
        if now - self._last_wake_ts > 2.0: self._last_wake_ts = now; _open_mumu_hidden()
    def _profile_by_id(self, vm_id): return next((x for x in self.profiles if x["id"] == vm_id), None)
    def _dispatch_launch_queue(self):
        # Единственное место, откуда уходят команды open. За тик отправляется максимум ОДИН профиль.
        if not self.pending_boot_ids: return
        now = time.time()
        if not self.mumu_ready:
            # MuMu ещё поднимается - просто ждём (спиннер у профилей в очереди остаётся). Но не вечно.
            expired = [v for v, st in self.pending_boot_ids.items() if now - st > MUMU_BOOT_WAIT_TIMEOUT]
            for v in expired: self.pending_boot_ids.pop(v, None); self.launching_ids.pop(v, None); self._cold_ids.discard(v)
            expired and self.filter_list()
            return
        # пауза LAUNCH_STAGGER_SEC считается и от готовности MuMu, и от предыдущего open
        if now - max(self._last_open_ts, self._ready_at) < LAUNCH_STAGGER_SEC - 0.001: return
        vm_id = next(iter(self.pending_boot_ids)); self.pending_boot_ids.pop(vm_id, None)
        p = self._profile_by_id(vm_id)
        if p is None or p["running"]:
            # профиль удалён или уже запущен - пропускаем без траты паузы
            self.launching_ids.pop(vm_id, None); self._cold_ids.discard(vm_id); self.filter_list(); return
        self._send_open(vm_id)
    def _verify_cold_opens(self):
        # Если MuMu подтвердил готовность, а профиль после open всё равно не стал running (команда потерялась) - повторяем через общую очередь.
        if not self.open_verify or not self.mumu_ready: return
        now = time.time(); changed = False
        for vm_id, ts in list(self.open_verify.items()):
            p = self._profile_by_id(vm_id)
            if p is None or p["running"]: self.open_verify.pop(vm_id, None); self._open_attempts.pop(vm_id, None); continue
            if now - ts < OPEN_VERIFY_AFTER: continue
            self.open_verify.pop(vm_id, None)
            att = self._open_attempts.get(vm_id, 0)
            if att >= OPEN_MAX_RETRIES: self._open_attempts.pop(vm_id, None); continue
            self._open_attempts[vm_id] = att + 1; self._cold_ids.add(vm_id)
            self.pending_boot_ids[vm_id] = now; self.launching_ids[vm_id] = now; changed = True
        changed and self.filter_list()
    def _check_launch_timeouts(self):
        self._verify_cold_opens()
        if not self.launching_ids: return
        now = time.time()
        # Профили, ожидающие поднятия MuMuPlayer, не трогаем по короткому
        # LAUNCH_PENDING_TIMEOUT - у них свой тайаут MUMU_BOOT_WAIT_TIMEOUT.
        expired = [vm_id for vm_id, st in self.launching_ids.items() if vm_id not in self.pending_boot_ids and now - st > LAUNCH_PENDING_TIMEOUT]
        if expired:
            for vm_id in expired: self.launching_ids.pop(vm_id, None)
            self.filter_list()
    def _track_global_mouse(self):
        if not self.isVisible() or self.is_blurred or QApplication.activeModalWidget() is not None: self.list_widget.clear_hover(); return
        lp = self.list_widget.viewport().mapFromGlobal(QCursor.pos())
        if self.list_widget.viewport().rect().contains(lp):
            item = self.list_widget.itemAt(lp)
            item != self.list_widget.hovered_item and (setattr(self.list_widget, 'hovered_item', item), self.list_widget.viewport().update())
        else: self.list_widget.clear_hover()
    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f: return json.load(f)
            except Exception: pass
        return {}
    def _set_hover_button(self, btn):
        if btn is self._hover_btn: return
        old, self._hover_btn = self._hover_btn, btn
        if old is not None:
            try: QApplication.sendEvent(old, QEvent(QEvent.Type.Leave))
            except RuntimeError: pass
        if btn is not None:
            try: QApplication.sendEvent(btn, QEvent(QEvent.Type.Enter))
            except RuntimeError: pass
    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f: return json.load(f)
            except Exception: pass
        return {}
    def save_config(self):
        try:
            self.config["cached_profiles"] = [{"name": p.get("name", "Unknown"), "id": p.get("id", ""), "checked": p.get("id", "") in self.selected_ids, "sticker": self.stickers_map.get(p.get("id", ""), ""), "note": self.notes_map.get(p.get("id", ""), ""), "note_color": self.notes_colors_map.get(p.get("id", ""), "")} for p in self.profiles]
            for _k in ("stickers", "notes", "notes_colors"): self.config.pop(_k, None)  # теперь всё живёт внутри cached_profiles
            self.config.update({"last_note_color": self.last_note_color, "available_stickers": self.available_stickers, "sort_index": self.sort_combo.currentIndex() if hasattr(self, 'sort_combo') else self.saved_sort_index, "running_first": self.sort_combo.runningFirst() if hasattr(self, 'sort_combo') else self.saved_running_first, "theme": self.current_theme, "lang": self.current_lang, "always_on_top": self.always_on_top, "mumu_manager_path": MUMU_BIN})
            with open(CONFIG_PATH, "w", encoding="utf-8") as f: json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception: pass
    def toggle_theme(self): self.current_theme = "light" if self.current_theme == "dark" else "dark"; self.apply_theme(); self.save_config()
    def set_lang(self, lang): lang in TR and lang != self.current_lang and (setattr(self, 'current_lang', lang), self.apply_language(), self.save_config())
    def apply_language(self):
        self.search_input.setPlaceholderText(tr(self.current_lang, "search_placeholder")); self.btn_settings.setToolTip(tr(self.current_lang, "settings_tooltip")); self.btn_add_device.setToolTip(tr(self.current_lang, "add_device_tooltip"))
        hasattr(self, 'sort_combo') and self.sort_combo.set_lang(self.current_lang)
        hasattr(self, 'btn_reset_main') and self.btn_reset_main.setText(tr(self.current_lang, "reset_btn"))
        hasattr(self, 'btn_select_all') and self.btn_select_all.setText(tr(self.current_lang, "deselect_all_btn" if self.btn_select_all.isChecked() else "select_all_btn"))
        hasattr(self, 'btn_start_sel') and self.btn_start_sel.setToolTip(tr(self.current_lang, "start_selected_tooltip"))
        hasattr(self, 'btn_stop_sel') and self.btn_stop_sel.setToolTip(tr(self.current_lang, "stop_selected_tooltip"))
        hasattr(self, 'lbl_selected') and self.update_selected_label()
        self.filter_list()
    def set_always_on_top(self, checked): self.always_on_top = checked; self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked); self.setVisible(True); self.save_config()
    def apply_theme(self):
        is_dark = (self.current_theme == "dark"); self.header_label.setStyleSheet("color:#666;letter-spacing:1px;" if is_dark else "color:#8E8E93;letter-spacing:1px;")
        if is_dark: self.setStyleSheet("QWidget{background-color:#141414;color:#FFF;font-family:'Segoe UI',sans-serif;}QLineEdit{background:#222;border:1px solid #333;border-radius:8px;padding:6px 10px;color:#FFF;}QLineEdit:focus{border-color:#0A84FF;}QListWidget{background:#1A1A1A;border:1px solid #2B2B2B;border-radius:10px;padding:6px;outline:0;}QListWidget::item{margin-bottom:4px;border-radius:8px;background:transparent;}QPushButton#btnResetMain{background:#222;border:1px solid #3B3B3B;border-radius:8px;color:#CCCCCC;font-size:12px;font-weight:500;}QPushButton#btnResetMain:hover{background:#2A2A2D;border-color:#666;}QPushButton#btnSelectAll{background:#222;border:1px solid #3B3B3B;border-radius:8px;color:#CCCCCC;font-size:12px;font-weight:500;padding:0 10px;}QPushButton#btnSelectAll:hover{background:#2A2A2D;border-color:#666;}QPushButton#btnSelectAll:checked{background:#3A3A3C;border:1px solid #636366;color:#EEEEEE;}QPushButton#btnSelectAll:checked:hover{background:#454548;border-color:#6E6E73;}QLabel#lblSelected{color:#8E8E93;font-size:11px;font-weight:500;}QPushButton#btnStartSel{background:rgba(48,209,88,0.15);border:1px solid rgba(48,209,88,0.5);border-radius:8px;color:#30D158;font-size:13px;font-weight:bold;}QPushButton#btnStartSel:hover{background:rgba(48,209,88,0.3);color:#34C759;border:1px solid rgba(48,209,88,0.7);}QPushButton#btnStartSel:disabled{background:#1E1E1E;border:1px solid #2A2A2A;color:#555;}QPushButton#btnStopSel{background:rgba(255,59,48,0.15);border:1px solid rgba(255,59,48,0.5);border-radius:8px;color:#FF3B30;font-size:12px;font-weight:bold;}QPushButton#btnStopSel:hover{background:rgba(255,59,48,0.3);color:#FF453A;border:1px solid rgba(255,59,48,0.7);}QPushButton#btnStopSel:disabled{background:#1E1E1E;border:1px solid #2A2A2A;color:#555;}QLabel#emptyStateLabel{background:#1A1A1A;border:1px solid #2B2B2B;border-radius:10px;color:#8E8E93;font-size:13px;font-weight:500;padding:20px;}"+get_scroll_css("dark")); self.btn_settings.setStyleSheet("QPushButton{background:#222;border:1px solid #3B3B3B;border-radius:8px;font-size:13px;}QPushButton:hover{background:#2A2A2D;border-color:#666;}"); self.btn_add_device.setStyleSheet("QPushButton{background:#222;border:1px solid #3B3B3B;border-radius:8px;font-size:16px;font-weight:bold;color:#0A84FF;}QPushButton:hover{background:#2A2A2D;border-color:#666;}")
        else: self.setStyleSheet("QWidget{background-color:#F2F2F7;color:#1C1C1E;font-family:'Segoe UI',sans-serif;}QLineEdit{background:#FFF;border:1px solid #D1D1D6;border-radius:8px;padding:6px 10px;color:#1C1C1E;}QLineEdit:focus{border-color:#007AFF;}QListWidget{background:#FFF;border:1px solid #E5E5EA;border-radius:10px;padding:6px;outline:0;}QListWidget::item{margin-bottom:4px;border-radius:8px;background:transparent;}QPushButton#btnResetMain{background:#E5E5EA;border:1px solid #D1D1D6;border-radius:8px;color:#1C1C1E;font-size:12px;font-weight:500;}QPushButton#btnResetMain:hover{background:#D8D8DC;border-color:#B0B0B5;}QPushButton#btnSelectAll{background:#E5E5EA;border:1px solid #D1D1D6;border-radius:8px;color:#1C1C1E;font-size:12px;font-weight:500;padding:0 10px;}QPushButton#btnSelectAll:hover{background:#D8D8DC;border-color:#B0B0B5;}QPushButton#btnSelectAll:checked{background:#D1D1D6;border:1px solid #AEAEB2;color:#1C1C1E;}QPushButton#btnSelectAll:checked:hover{background:#C7C7CC;border-color:#98989D;}QLabel#lblSelected{color:#8E8E93;font-size:11px;font-weight:500;}QPushButton#btnStartSel{background:rgba(48,209,88,0.12);border:1px solid rgba(48,209,88,0.4);border-radius:8px;color:#248A3D;font-size:13px;font-weight:bold;}QPushButton#btnStartSel:hover{background:rgba(48,209,88,0.25);color:#248A3D;border:1px solid rgba(48,209,88,0.6);}QPushButton#btnStartSel:disabled{background:#EDEDF0;border:1px solid #E5E5EA;color:#B0B0B5;}QPushButton#btnStopSel{background:rgba(255,59,48,0.12);border:1px solid rgba(255,59,48,0.4);border-radius:8px;color:#FF3B30;font-size:12px;font-weight:bold;}QPushButton#btnStopSel:hover{background:rgba(255,59,48,0.25);color:#FF3B30;border:1px solid rgba(255,59,48,0.6);}QPushButton#btnStopSel:disabled{background:#EDEDF0;border:1px solid #E5E5EA;color:#B0B0B5;}QLabel#emptyStateLabel{background:#FFF;border:1px solid #E5E5EA;border-radius:10px;color:#8E8E93;font-size:13px;font-weight:500;padding:20px;}"+get_scroll_css("light")); self.btn_settings.setStyleSheet("QPushButton{background:#E5E5EA;border:1px solid #D1D1D6;border-radius:8px;font-size:13px;}QPushButton:hover{background:#D8D8DC;border-color:#B0B0B5;}"); self.btn_add_device.setStyleSheet("QPushButton{background:#E5E5EA;border:1px solid #D1D1D6;border-radius:8px;font-size:16px;font-weight:bold;color:#007AFF;}QPushButton:hover{background:#D8D8DC;border-color:#B0B0B5;}")
        hasattr(self, 'sort_combo') and self.sort_combo.update_style(self.current_theme); self.filter_list()
    def on_sticker_change(self, vm_id, s):
        def_stk = self.available_stickers[0] if self.available_stickers else "∙"
        self.stickers_map.pop(vm_id, None) if s == def_stk else self.stickers_map.update({vm_id: s}); self.save_config(); self.filter_list()
    def on_note_change(self, vm_id, note):
        self.notes_map.pop(vm_id, None) if not note else self.notes_map.update({vm_id: note}); self.save_config(); self.filter_list()
    def on_note_color_change(self, vm_id, color):
        self.notes_colors_map[vm_id] = color; self.last_note_color = color; self.save_config(); self.filter_list()
    def save_available_stickers(self, lst): self.available_stickers = lst if lst else ["∙"]; self.save_config(); self.filter_list()
    def _confirm_reset_action(self, title_key, text_key, empty_key, target_dict):
        self.set_blur_effect(True)
        try:
            has_items = len(target_dict) > 0
            dlg = ConfirmDialog(tr(self.current_lang, title_key), tr(self.current_lang, text_key), tr(self.current_lang, empty_key), self, theme=self.current_theme, lang=self.current_lang, has_items=has_items)
            if has_items and dlg.exec() == QDialog.DialogCode.Accepted: target_dict.clear(); self.save_config(); self.filter_list()
            elif not has_items: dlg.exec()
        finally: not QApplication.activeModalWidget() and self.set_blur_effect(False)
    def reset_all_stickers(self): self._confirm_reset_action("confirm_reset_stickers_title", "confirm_reset_stickers_text", "empty_reset_stickers", self.stickers_map)
    def reset_all_notes(self): self._confirm_reset_action("confirm_reset_notes_title", "confirm_reset_notes_text", "empty_reset_notes", self.notes_map)
    def open_sticker_settings(self):
        self.set_blur_effect(True)
        try:
            d = StickerManagerDialog(list(self.available_stickers), self, theme=self.current_theme, lang=self.current_lang)
            d.exec() == QDialog.DialogCode.Accepted and self.save_available_stickers(d.stickers)
        finally: not QApplication.activeModalWidget() and self.set_blur_effect(False)
    def _get_ordered_used_stickers(self):
        used_set = set(self.stickers_map.values())
        return [s for s in self.available_stickers if s in used_set] + [s for s in used_set if s not in self.available_stickers]
    def _reset_stickers_filtered(self, title_key, filter_fn):
        used = self._get_ordered_used_stickers(); self.set_blur_effect(True)
        try:
            has_items = len(used) > 0 and len(self.stickers_map) > 0
            dlg = StickerSelectionDialog(tr(self.current_lang, title_key), used, self, theme=self.current_theme, lang=self.current_lang) if has_items else ConfirmDialog(tr(self.current_lang, title_key), "", tr(self.current_lang, "empty_reset_stickers"), self, theme=self.current_theme, lang=self.current_lang, has_items=False)
            if has_items and dlg.exec() == QDialog.DialogCode.Accepted: filter_fn(set(dlg.get_selected())); self.save_config(); self.filter_list()
            elif not has_items: dlg.exec()
        finally: not QApplication.activeModalWidget() and self.set_blur_effect(False)
    def reset_stickers_except(self): self._reset_stickers_filtered("title_except", lambda keep: setattr(self, 'stickers_map', {k: v for k, v in self.stickers_map.items() if v in keep}))
    def reset_specific_stickers(self):
        def_stk = self.available_stickers[0] if self.available_stickers else "∙"
        self._reset_stickers_filtered("title_specific", lambda remove: setattr(self, 'stickers_map', {k: v for k, v in self.stickers_map.items() if v not in remove and v != def_stk}))
    def show_reset_menu(self, anchor):
        self.set_blur_effect(True)
        try:
            menu = QMenu(self); menu.setStyleSheet(get_menu_css(self.current_theme))
            for text, fn in ((tr(self.current_lang, "reset_all"), self.reset_all_stickers), (tr(self.current_lang, "reset_except"), self.reset_stickers_except), (tr(self.current_lang, "reset_specific"), self.reset_specific_stickers)): menu.addAction(text).triggered.connect(fn)
            menu.addSeparator(); menu.addAction(tr(self.current_lang, "reset_notes")).triggered.connect(self.reset_all_notes)
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        finally: not QApplication.activeModalWidget() and self.set_blur_effect(False)
    def show_settings_dialog(self):
        self.set_blur_effect(True)
        try: SettingsDialog(self, theme=self.current_theme, lang=self.current_lang).exec()
        finally: not QApplication.activeModalWidget() and self.set_blur_effect(False)
    def show_add_device_menu(self, anchor):
        self.set_blur_effect(True)
        try:
            menu = QMenu(self); menu.setStyleSheet(get_menu_css(self.current_theme))
            menu.addAction(tr(self.current_lang, "create_tablet")).triggered.connect(lambda: self.create_device("tablet"))
            menu.addAction(tr(self.current_lang, "create_phone")).triggered.connect(lambda: self.create_device("phone"))
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        finally: not QApplication.activeModalWidget() and self.set_blur_effect(False)
    def create_device(self, device_type):
        preset = {"tablet": (2560, 1440, 360), "phone": (1440, 2560, 480)}.get(device_type)
        if not preset: return
        w, h, dpi = preset
        def _indices():
            r = mm_run("info", "-v", "all", timeout=10.0); lst = parse_info(r.stdout) if r else None
            return {e["index"] for e in (lst or [])}
        def worker():
            before = _indices()
            res = mm_run("create", "-n", "1", timeout=180.0)
            if res is None: return
            data = _loads((res.stdout or "").strip())
            new = [k for k in (data.keys() if isinstance(data, dict) else []) if str(k).isdigit()]
            if not new: new = sorted(_indices() - before, key=lambda x: int(x) if x.isdigit() else 0)  # fallback: берём индекс, которого не было до create
            for idx in new:
                mm_run("setting", "-v", idx, "-k", "resolution_mode", "-val", "custom", "-k", "resolution_width.custom", "-val", w, "-k", "resolution_height.custom", "-val", h, "-k", "resolution_dpi.custom", "-val", dpi, timeout=30.0)
        threading.Thread(target=worker, daemon=True).start()
    def initUI(self):
        self.setWindowTitle("MuMU LauncheR"); self.resize(400, 560); self.setMinimumSize(360, 450); self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        rl = QVBoxLayout(self); rl.setContentsMargins(0, 0, 0, 0); self.main_container = QWidget(self); layout = QVBoxLayout(self.main_container); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(8); rl.addWidget(self.main_container)
        self.blur_effect = QGraphicsBlurEffect(self); self.blur_effect.setBlurRadius(18); self.blur_effect.setEnabled(False); self.main_container.setGraphicsEffect(self.blur_effect)
        self.dim_overlay = QWidget(self); self.dim_overlay.setStyleSheet("background-color:rgba(0,0,0,0.35);"); self.dim_overlay.hide()
        h_layout = QHBoxLayout(); self.header_label = QLabel("MuMU LauncheR"); self.header_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.btn_add_device = QPushButton("+"); self.btn_add_device.setFixedSize(26, 26); self.btn_add_device.setToolTip(tr(self.current_lang, "add_device_tooltip")); self.btn_add_device.clicked.connect(lambda: self.show_add_device_menu(self.btn_add_device))
        self.btn_settings = QPushButton("⚙️"); self.btn_settings.setFixedSize(26, 26); self.btn_settings.setToolTip(tr(self.current_lang, "settings_tooltip")); self.btn_settings.clicked.connect(self.show_settings_dialog)
        h_layout.addWidget(self.header_label); h_layout.addStretch(); h_layout.addWidget(self.btn_add_device); h_layout.addWidget(self.btn_settings); layout.addLayout(h_layout)
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText(tr(self.current_lang, "search_placeholder")); self.search_input.textChanged.connect(self.filter_list); layout.addWidget(self.search_input)
        ctrl = QHBoxLayout(); ctrl.setSpacing(8); self.sort_combo = SortMenuButton(lang=self.current_lang)
        0 <= self.saved_sort_index < len(SORT_OPTIONS) and self.sort_combo.setCurrentIndex(self.saved_sort_index)
        self.sort_combo.setRunningFirst(self.saved_running_first)
        self.sort_combo.indexChanged.connect(lambda idx: (self.save_config(), self.filter_list()))
        self.sort_combo.runningFirstChanged.connect(lambda checked: (self.save_config(), self.filter_list()))
        self.sort_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_reset_main = QPushButton(tr(self.current_lang, "reset_btn")); self.btn_reset_main.setObjectName("btnResetMain"); self.btn_reset_main.setFixedHeight(28); self.btn_reset_main.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed); self.btn_reset_main.clicked.connect(lambda: self.show_reset_menu(self.btn_reset_main))
        ctrl.addWidget(self.sort_combo); ctrl.addWidget(self.btn_reset_main); layout.addLayout(ctrl)
        sel_bar = QHBoxLayout(); sel_bar.setSpacing(8)
        self.btn_select_all = QPushButton(tr(self.current_lang, "select_all_btn")); self.btn_select_all.setObjectName("btnSelectAll"); self.btn_select_all.setCheckable(True); self.btn_select_all.setFixedHeight(28); self.btn_select_all.clicked.connect(self.toggle_select_all)
        self.lbl_selected = QLabel(); self.lbl_selected.setObjectName("lblSelected")
        self.btn_start_sel = QPushButton("▶"); self.btn_start_sel.setObjectName("btnStartSel"); self.btn_start_sel.setFixedSize(28, 28); self.btn_start_sel.setToolTip(tr(self.current_lang, "start_selected_tooltip")); self.btn_start_sel.clicked.connect(self.start_selected_profiles)
        self.btn_stop_sel = QPushButton("⏹"); self.btn_stop_sel.setObjectName("btnStopSel"); self.btn_stop_sel.setFixedSize(28, 28); self.btn_stop_sel.setToolTip(tr(self.current_lang, "stop_selected_tooltip")); self.btn_stop_sel.clicked.connect(self.stop_selected_profiles)
        sel_bar.addWidget(self.btn_select_all); sel_bar.addWidget(self.lbl_selected); sel_bar.addStretch(); sel_bar.addWidget(self.btn_start_sel); sel_bar.addWidget(self.btn_stop_sel); layout.addLayout(sel_bar)
        self.list_widget = CustomListWidget(); self.item_delegate = AnimatedItemDelegate(self.list_widget); self.list_widget.setItemDelegate(self.item_delegate)
        self.empty_state_label = QLabel(); self.empty_state_label.setObjectName("emptyStateLabel"); self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.empty_state_label.setWordWrap(True)
        self.list_stack = QStackedWidget(); self.list_stack.addWidget(self.list_widget); self.list_stack.addWidget(self.empty_state_label); layout.addWidget(self.list_stack)
        self.update_selected_label()
        QShortcut(QKeySequence(Qt.Key.Key_Return), self).activated.connect(self.launch_selected); QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.showMinimized)
    def resizeEvent(self, e): super().resizeEvent(e); hasattr(self, 'dim_overlay') and self.dim_overlay.setGeometry(self.rect())
    def set_blur_effect(self, en):
        self.is_blurred = en; self.blur_effect.setEnabled(en)
        if en: self.list_widget.clear_hover(); self.dim_overlay.setGeometry(self.rect()); self.dim_overlay.show(); self.dim_overlay.raise_()
        else: self.dim_overlay.hide(); self.list_widget.viewport().update()
    def _on_profiles_fetched(self, data):
        np = [{"name": x.get("name", "Unknown"), "id": str(x.get("index", "")), "running": (x.get("state") == "running")} for x in data]
        # Защита от вылета/перезапуска/закрытия MuMu: пустой ответ от MuMuManager
        # НИКОГДА не считаем достоверным снимком реальных профилей (даже если
        # это самый первый опрос после запуска лаунчера, и даже если сейчас в
        # self.profiles ничего нет). Пустой список почти всегда значит "MuMu не
        # отвечает", а не "все устройства удалены" - поэтому просто выходим,
        # ничего не трогая: ни self.profiles, ни стикеры, ни заметки.
        if not np:
            return
        current_ids = {p["id"] for p in np}
        # Список непустой (крах уже отфильтрован выше) - значит это честный
        # снимок реальных профилей, и пропавшего id можно чистить сразу же,
        # синхронно с этим же опросом, без искусственной задержки.
        to_delete = [i for i in set(self.stickers_map) | set(self.notes_map) | set(self.notes_colors_map) if i not in current_ids]
        if to_delete:
            for i in to_delete:
                self.stickers_map.pop(i, None); self.notes_map.pop(i, None); self.notes_colors_map.pop(i, None)
        if self.launching_ids:
            now = time.time()
            for p in np: p["id"] in self.launching_ids and p["id"] not in self.pending_boot_ids and p["running"] and self.launching_ids.pop(p["id"], None)
            for vm_id, st in list(self.launching_ids.items()): vm_id not in self.pending_boot_ids and now - st > LAUNCH_PENDING_TIMEOUT and self.launching_ids.pop(vm_id, None)
        self._enforce_kill_guard(np)
        if np != self.profiles:
            self.selected_ids &= current_ids; setattr(self, 'profiles', np); self.filter_list()
        # Ответ валидный и непустой — сохраняем актуальный снимок в локальный кеш.
        self.save_config()
    def _on_mumu_status_changed(self, ok):
        was_reachable, self.mumu_reachable = self.mumu_reachable, ok
        # MuMu готов с первого же валидного ответа MuMuManager (без доп. подтверждений)
        self.mumu_ready = ok
        if ok and not was_reachable: self._ready_at = time.time()
        if not ok and was_reachable:
            # MuMuPlayer закрылся (пользователь вышел / процесс убит) - MuMuManager
            # больше не отвечает, поэтому data_changed уже не придёт и статусы
            # "running" в self.profiles иначе замёрзли бы навсегда как включенные.
            # Сбрасываем все статусы вручную. Очередь запуска НЕ сохраняем -
            # после падения MuMu устройства не перезапускаются автоматически.
            if any(p["running"] for p in self.profiles):
                for p in self.profiles: p["running"] = False
                self.filter_list()
            # Профили, ожидающие в очереди запуска, не трогаем - они стартуют, когда MuMu снова будет готов.
            self.launching_ids = {k: v for k, v in self.launching_ids.items() if k in self.pending_boot_ids}
            self.open_verify.clear()
        self.filter_list()
    def update_empty_state(self):
        if self.profiles:
            self.list_stack.setCurrentWidget(self.list_widget); return False
        key = "empty_no_profiles" if self.mumu_reachable else "empty_mumu_not_running"
        self.empty_state_label.setText(tr(self.current_lang, key)); self.list_stack.setCurrentWidget(self.empty_state_label)
        return True
    def _sep_colors(self):
        light = self.current_theme == "light"
        return ("rgba(0,0,0,0.1)" if light else "rgba(150,150,150,0.2)"), ("#8E8E93" if light else "#8E8E93")
    def _style_list_separator(self, w, key):
        # линия - подпись по центру - линия; подпись и цвета обновляются при смене языка/темы
        line_c, text_c = self._sep_colors()
        for fr in w.findChildren(QFrame): fr.setStyleSheet(f"background-color:{line_c};")
        lbl = w.findChild(QLabel)
        if lbl:
            lbl.setText(tr(self.current_lang, key))
            spacing = "0px" if self.current_lang in ("ar", "hi") else "0.8px"  # в арабском/хинди разрядка ломает слитное написание
            lbl.setStyleSheet(f"font-size:9px;font-weight:700;letter-spacing:{spacing};color:{text_c};background:transparent;padding:0 2px;")
    def _make_list_separator(self, key="sep_running"):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w); lay.setContentsMargins(6, 0, 6, 0); lay.setSpacing(8)
        l1, l2 = QFrame(), QFrame()
        for ln in (l1, l2): ln.setFrameShape(QFrame.Shape.HLine); ln.setFrameShadow(QFrame.Shadow.Sunken); ln.setFixedHeight(1)
        lbl = QLabel(); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(l1, 1); lay.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter); lay.addWidget(l2, 1)
        self._style_list_separator(w, key); return w
    def filter_list(self):
        if self.update_empty_state():
            self._visible_ids = []; hasattr(self, 'lbl_selected') and self.update_selected_label(); return
        self.list_widget.setUpdatesEnabled(False); scroll = self.list_widget.verticalScrollBar().value(); sel_id = self.list_widget.currentItem().data(Qt.ItemDataRole.UserRole) if self.list_widget.currentItem() else None
        q, sm, rf = self.search_input.text().lower().strip(), self.sort_combo.currentIndex(), self.sort_combo.runningFirst()
        tokens = q.split()  # поиск по словам: каждое слово запроса должно встретиться, порядок и соседство не важны
        sc = {0:(lambda x:natural_sort_key(x["name"]), False), 1:(lambda x:natural_sort_key(x["name"]), True), 2:(lambda x:int(x["id"]) if x["id"].isdigit() else x["id"], False), 3:(lambda x:int(x["id"]) if x["id"].isdigit() else x["id"], True)}
        kf, rev = sc.get(sm, sc[0])
        sorted_profiles = sorted(self.profiles, key=kf, reverse=rev)
        # "Сначала запущенные" - это отдельный тумблер, а не режим сортировки: если включен, запущенные
        # девайсы всегда остаются сверху (стабильная досортировка сохраняет порядок внутри групп),
        # независимо от выбранного поля сортировки и направления (имя/ID, А-Я/Я-А)
        rf and (sorted_profiles := sorted(sorted_profiles, key=lambda x: not x["running"]))
        show_id = sm in (2, 3)
        # каждое слово запроса должно найтись хотя бы в одном из полей: имя / id / заметка
        def_stk = self.available_stickers[0] if self.available_stickers else "visor"
        match = lambda p: (lambda fields: all(any(t in f for f in fields) for t in tokens))((p["name"].lower(), p["id"].lower(), self.notes_map.get(p["id"], "").lower(), self.stickers_map.get(p["id"], def_stk).lower()))
        sp = [p for p in sorted_profiles if (rf and p["running"]) or match(p)]
        # блоки списка: при включённом rf и непустом поиске -> [запущенные вне фильтра], [запущенные по фильтру], [выключенные по фильтру];
        # без поиска -> [запущенные], [выключенные]; без rf -> один общий блок. Между непустыми блоками ставится разделитель
        # у каждой группы - свой ключ подписи-разделителя, который рисуется прямо над ней (а не "между" группами),
        # чтобы при трёх группах сразу было понятно что именно означает каждый блок: ВКЛ / ВКЛ (ПОИСК) / ПОИСК
        if rf and q:
            groups = [("sep_running", [p for p in sp if p["running"] and not match(p)]), ("sep_running_search", [p for p in sp if p["running"] and match(p)]), ("sep_search", [p for p in sp if not p["running"]])]
        elif rf:
            groups = [("sep_running", [p for p in sp if p["running"]]), ("sep_all", [p for p in sp if not p["running"]])]
        else:
            groups = [(None, sp)]
        groups = [(key, g) for key, g in groups if g]
        sp = [p for _, g in groups for p in g]
        self._visible_ids = [p["id"] for p in sp]
        plan = []
        for gi, (key, g) in enumerate(groups):
            key and plan.append(("sep", key))
            plan.extend(("p", p) for p in g)
        shape = tuple((t, p if t == "sep" else None) for t, p in plan)
        if self.list_widget.count() == len(plan) and getattr(self, "_last_list_shape", None) == shape:
            for i, (t, p) in enumerate(plan):
                item = self.list_widget.item(i)
                if t == "sep":
                    sw = self.list_widget.itemWidget(item)
                    sw and self._style_list_separator(sw, p)
                    continue
                item.setData(Qt.ItemDataRole.UserRole, p["id"]); w = self.list_widget.itemWidget(item)
                w and (w.update_data(p, self.stickers_map.get(p["id"], def_stk), self.notes_map.get(p["id"], ""), show_id=show_id, pending=(p["id"] in self.launching_ids), note_color=self.notes_colors_map.get(p["id"], self.last_note_color)), w.set_checked_silent(p["id"] in self.selected_ids))
        else:
            self.list_widget.clear(); self._hover_btn = None  # старые виджеты кнопок будут уничтожены - забываем ссылку без отправки события
            for t, p in plan:
                if t == "sep":
                    item = QListWidgetItem(self.list_widget); item.setFlags(Qt.ItemFlag.NoItemFlags); item.setData(SEP_ROLE, True); item.setSizeHint(QSize(0, 18))
                    self.list_widget.addItem(item); self.list_widget.setItemWidget(item, self._make_list_separator(p)); continue
                item = QListWidgetItem(self.list_widget); item.setData(Qt.ItemDataRole.UserRole, p["id"]); item.setSizeHint(QSize(0, 42))
                w = ProfileItemWidget(p, self.stickers_map.get(p["id"], def_stk), self.notes_map.get(p["id"], ""), self.launch_profile_by_id, self.stop_profile_by_id, self.on_sticker_change, self.on_note_change, lambda: self.available_stickers, self.save_available_stickers, show_id=show_id, pending=(p["id"] in self.launching_ids), on_check_change=self.on_profile_check_change, checked=(p["id"] in self.selected_ids), note_color=self.notes_colors_map.get(p["id"], self.last_note_color), on_note_color_change=self.on_note_color_change)
                self.list_widget.addItem(item); self.list_widget.setItemWidget(item, w); w.update_data(p, self.stickers_map.get(p["id"], def_stk), self.notes_map.get(p["id"], ""), show_id=show_id, pending=(p["id"] in self.launching_ids), note_color=self.notes_colors_map.get(p["id"], self.last_note_color))
                sel_id and p["id"] == sel_id and self.list_widget.setCurrentItem(item)
            self._last_list_shape = shape
            self.list_widget.doItemsLayout()  # без этого диапазон скролла ещё старый и setValue ниже обрезается -> список прыгает
        self.list_widget.verticalScrollBar().setValue(scroll); self.list_widget.setUpdatesEnabled(True); self.list_widget.viewport().update()
        hasattr(self, 'lbl_selected') and self.update_selected_label()
    def launch_profile_by_id(self, vm_id):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == vm_id:
                sb = self.list_widget.verticalScrollBar(); pos = sb.value()
                self.list_widget.setCurrentItem(item); sb.setValue(pos)  # setCurrentItem сам скроллит к строке - возвращаем позицию
                break
        _p = self._profile_by_id(vm_id)
        if _p is not None and _p["running"] and self.mumu_ready:
            self._kill_guard.pop(vm_id, None)
            mm_spawn("control", "-v", vm_id, "show_window")
            return
        if vm_id in self.pending_boot_ids: return  # уже в очереди
        self._kill_guard.pop(vm_id, None)
        self.launching_ids[vm_id] = time.time(); self.pending_boot_ids[vm_id] = time.time(); self._open_attempts.pop(vm_id, None)
        if not self.mumu_ready:
            # MuMuPlayer выключен / ещё поднимается. Open сейчас потеряется, поэтому только будим приложение;
            # сам open уйдёт из _dispatch_launch_queue, когда MuMu будет 100% готов (+ LAUNCH_STAGGER_SEC).
            self._cold_ids.add(vm_id); self._wake_mumu()
        self.filter_list(); self.item_delegate.trigger_flash()
    def _send_open(self, vm_id):
        mm_spawn("control", "-v", vm_id, "launch")
        now = time.time(); self._last_open_ts = now; self.launching_ids[vm_id] = now
        if vm_id in self._cold_ids: self._cold_ids.discard(vm_id); self.open_verify[vm_id] = now
        self.filter_list()
    def _cancel_launch(self, vm_id):
        # Полностью выкидываем профиль из очереди запуска и гасим все связанные повторы (retry/verify).
        self.launching_ids.pop(vm_id, None); self.pending_boot_ids.pop(vm_id, None); self._cold_ids.discard(vm_id); self.open_verify.pop(vm_id, None); self._open_attempts.pop(vm_id, None)
    def stop_profile_by_id(self, vm_id, redraw=True):
        was_launching = vm_id in self.launching_ids or vm_id in self.open_verify
        self._cancel_launch(vm_id)
        # Если open уже улетел в MuMuManager, но профиль ещё не успел стать running, он поднимется уже ПОСЛЕ нашего close.
        # Поэтому на KILL_GUARD_SEC секунд ставим "охрану": если он всё-таки вылезет в running - закроем повторно.
        was_launching and self._kill_guard.__setitem__(vm_id, time.time() + KILL_GUARD_SEC)
        mm_spawn("control", "-v", vm_id, "shutdown")
        redraw and self.filter_list()
    def _enforce_kill_guard(self, profiles):
        if not self._kill_guard: return
        now = time.time()
        for vm_id in [v for v, t in self._kill_guard.items() if t < now]: self._kill_guard.pop(vm_id, None); self._kill_last.pop(vm_id, None)
        for p in profiles:
            if p["running"] and p["id"] in self._kill_guard and now - self._kill_last.get(p["id"], 0) > 1.0:
                self._kill_last[p["id"]] = now
                mm_spawn("control", "-v", p["id"], "shutdown")
    def on_profile_check_change(self, vm_id, checked):
        self.selected_ids.add(vm_id) if checked else self.selected_ids.discard(vm_id)
        self.update_selected_label(); self.save_config()
    def update_selected_label(self):
        n = len(self.selected_ids)
        hasattr(self, 'lbl_selected') and self.lbl_selected.setText(tr(self.current_lang, "selected_label").format(n=n))
        if hasattr(self, 'btn_select_all'):
            all_selected = bool(self._visible_ids) and all(i in self.selected_ids for i in self._visible_ids)
            self.btn_select_all.blockSignals(True); self.btn_select_all.setChecked(all_selected); self.btn_select_all.blockSignals(False)
            self.btn_select_all.setText(tr(self.current_lang, "deselect_all_btn" if all_selected else "select_all_btn"))
        if hasattr(self, 'btn_start_sel'): self.btn_start_sel.setEnabled(n > 0)
        if hasattr(self, 'btn_stop_sel'): self.btn_stop_sel.setEnabled(n > 0)
    def toggle_select_all(self):
        if self.btn_select_all.isChecked(): self.selected_ids.update(self._visible_ids)
        else: self.selected_ids.difference_update(self._visible_ids)
        self.update_selected_label(); self.filter_list(); self.save_config()
    def start_selected_profiles(self):
        # в порядке отображения в списке; задержку между ними держит очередь запуска
        order = [i for i in self._visible_ids if i in self.selected_ids] + [i for i in self.selected_ids if i not in self._visible_ids]
        for vm_id in order:
            p = self._profile_by_id(vm_id)
            p and not p["running"] and self.launch_profile_by_id(vm_id)
    def stop_selected_profiles(self):
        # Stop = погасить отмеченные профили И сбросить их очередь запуска (в т.ч. тех, что ещё не стартовали).
        for vm_id in list(self.selected_ids):
            p = self._profile_by_id(vm_id)
            if p is None: continue
            if p["running"] or vm_id in self.launching_ids or vm_id in self.pending_boot_ids or vm_id in self.open_verify: self.stop_profile_by_id(vm_id, redraw=False)
            else: self._cancel_launch(vm_id)
        self.filter_list()
    def launch_selected(self): self.list_widget.currentItem() and self.launch_profile_by_id(self.list_widget.currentItem().data(Qt.ItemDataRole.UserRole))
    def closeEvent(self, e): self.mouse_poll_timer.stop(); self.launch_watchdog_timer.stop(); self.launch_dispatch_timer.stop(); self.monitor.stop(); super().closeEvent(e)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))  # на Windows 1pt = 1.33px, поэтому базовый размер ниже, чем на macOS
    _saved = ""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as _f: _saved = json.load(_f).get("mumu_manager_path", "")
    except Exception: pass
    MUMU_BIN = find_mumu_manager(_saved)
    if not MUMU_BIN:
        _p, _ = QFileDialog.getOpenFileName(None, "MuMuManager.exe", r"C:\Program Files\Netease", "MuMuManager (MuMuManager.exe)")
        if not _p: sys.exit(1)
        MUMU_BIN = os.path.normpath(_p)
    win = MuMU()
    win.show()
    sys.exit(app.exec())
