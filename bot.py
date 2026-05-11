#!/usr/bin/env python3
"""
Bot de Telegram para recordatorios diarios.
Compatible con Python 3.13+
Incluye selección de días y rango de horario (hora inicio - hora fin).
"""

import json
import logging
import os
from datetime import datetime

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.background import BackgroundScheduler

# ── Configuración ──────────────────────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_TOKEN", "TU_TOKEN_AQUI")
DATA_FILE = "tasks.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)

CATEGORIES = {
    "trabajo":   "💼 Trabajo / Reuniones",
    "ejercicio": "🏃 Ejercicio / Salud",
    "habitos":   "🌱 Hábitos Personales",
}

DAYS = {
    "lun": "Lunes",
    "mar": "Martes",
    "mie": "Miércoles",
    "jue": "Jueves",
    "vie": "Viernes",
    "sab": "Sábado",
    "dom": "Domingo",
}

DAY_INDEX = {
    "lun": 0, "mar": 1, "mie": 2,
    "jue": 3, "vie": 4, "sab": 5, "dom": 6,
}

user_state = {}  # user_id -> {"step": ..., "data": {...}}

# ── Persistencia ───────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_tasks(user_id):
    return load_data().get(str(user_id), [])

def save_tasks(user_id, tasks):
    data = load_data()
    data[str(user_id)] = tasks
    save_data(data)

# ── Helpers ────────────────────────────────────────────────────────────────────

def days_label(days_list):
    if sorted(days_list) == sorted(DAY_INDEX.keys()):
        return "Todos los días"
    return ", ".join(DAYS[d] for d in ["lun","mar","mie","jue","vie","sab","dom"] if d in days_list)

def build_days_kb(selected):
    kb = InlineKeyboardMarkup()
    row = []
    for key, label in DAYS.items():
        check = "✅" if key in selected else "⬜"
        row.append(InlineKeyboardButton(f"{check} {label[:3]}", callback_data=f"day_{key}"))
        if len(row) == 4:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    kb.row(
        InlineKeyboardButton("☑️ Todos", callback_data="day_all"),
        InlineKeyboardButton("✅ Confirmar", callback_data="day_confirm")
    )
    return kb

def valid_time(t):
    try:
        datetime.strptime(t, "%H:%M")
        return True
    except ValueError:
        return False

# ── /start ─────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "ayuda", "help"])
def cmd_start(message):
    bot.send_message(message.chat.id,
        "👋 *¡Hola! Soy tu bot de recordatorios.*\n\n"
        "📋 *Comandos:*\n"
        "/agregar — Agregar una actividad\n"
        "/listar — Ver tus actividades\n"
        "/eliminar — Eliminar una actividad\n"
        "/completadas — Marcar tareas del día\n"
        "/ayuda — Mostrar esta ayuda\n\n"
        "⏰ Recibirás un recordatorio cada mañana con las tareas del día.",
        parse_mode="Markdown"
    )

# ── /listar ────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["listar"])
def cmd_listar(message):
    tasks = get_tasks(message.from_user.id)
    if not tasks:
        bot.send_message(message.chat.id, "📭 No tenés actividades. Usá /agregar para crear una.")
        return

    msg = "📋 *Tus actividades:*\n\n"
    for cat_key, cat_label in CATEGORIES.items():
        cat_tasks = [t for t in tasks if t["categoria"] == cat_key]
        if cat_tasks:
            msg += f"*{cat_label}*\n"
            for t in cat_tasks:
                done = "✅" if t.get("completada_hoy") else "⬜"
                dias = days_label(t.get("dias", list(DAY_INDEX.keys())))
                hora_fin = f" → {t['hora_fin']}" if t.get("hora_fin") else ""
                msg += f"  {done} {t['nombre']}\n"
                msg += f"       ⏰ {t['hora']}{hora_fin}\n"
                msg += f"       📅 {dias}\n"
            msg += "\n"
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

# ── /agregar ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["agregar"])
def cmd_agregar(message):
    user_state[message.from_user.id] = {"step": "nombre", "data": {}}
    bot.send_message(message.chat.id,
        "📝 *¿Cómo se llama la actividad?*\n_(Ej: Reunión de equipo, Salir a correr)_",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id]["step"] == "nombre")
def recibir_nombre(message):
    user_state[message.from_user.id]["data"]["nombre"] = message.text.strip()
    user_state[message.from_user.id]["step"] = "hora_inicio"
    bot.send_message(message.chat.id,
        "⏰ *¿A qué hora empieza?*\n_(Formato 24hs, ej: 08:30)_",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id]["step"] == "hora_inicio")
def recibir_hora_inicio(message):
    hora = message.text.strip()
    if not valid_time(hora):
        bot.send_message(message.chat.id, "❌ Formato inválido. Usá HH:MM (ej: 08:30)")
        return
    user_state[message.from_user.id]["data"]["hora"] = hora
    user_state[message.from_user.id]["step"] = "hora_fin"
    bot.send_message(message.chat.id,
        "⏰ *¿A qué hora termina?*\n_(Formato 24hs, ej: 09:30 — o escribí *no* si no tiene hora de fin)_",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id]["step"] == "hora_fin")
def recibir_hora_fin(message):
    texto = message.text.strip().lower()
    if texto == "no":
        user_state[message.from_user.id]["data"]["hora_fin"] = None
    else:
        if not valid_time(texto):
            bot.send_message(message.chat.id, "❌ Formato inválido. Usá HH:MM (ej: 09:30) o escribí *no*", parse_mode="Markdown")
            return
        user_state[message.from_user.id]["data"]["hora_fin"] = texto

    user_state[message.from_user.id]["data"]["dias_sel"] = []
    user_state[message.from_user.id]["step"] = "dias"
    bot.send_message(message.chat.id,
        "📅 *¿Qué días aplica esta actividad?*\nSeleccioná los días y tocá *Confirmar*.",
        reply_markup=build_days_kb([]),
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("day_"))
def manejar_dias(call):
    uid = call.from_user.id
    if uid not in user_state or user_state[uid]["step"] != "dias":
        bot.answer_callback_query(call.id)
        return

    selected = user_state[uid]["data"].get("dias_sel", [])
    action = call.data.replace("day_", "")

    if action == "all":
        selected = list(DAY_INDEX.keys())
    elif action == "confirm":
        if not selected:
            bot.answer_callback_query(call.id, "⚠️ Seleccioná al menos un día.", show_alert=True)
            return
        user_state[uid]["data"]["dias"] = selected
        user_state[uid]["step"] = "categoria"
        kb = InlineKeyboardMarkup()
        for key, label in CATEGORIES.items():
            kb.add(InlineKeyboardButton(label, callback_data=f"cat_{key}"))
        bot.edit_message_text("📂 *¿En qué categoría?*",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=kb, parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        return
    else:
        if action in selected:
            selected.remove(action)
        else:
            selected.append(action)

    user_state[uid]["data"]["dias_sel"] = selected
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                   reply_markup=build_days_kb(selected))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cat_"))
def recibir_categoria(call):
    uid = call.from_user.id
    if uid not in user_state or user_state[uid]["step"] != "categoria":
        bot.answer_callback_query(call.id)
        return

    cat_key = call.data.replace("cat_", "")
    tarea = user_state[uid]["data"]
    tarea["categoria"] = cat_key
    tarea["completada_hoy"] = False
    tarea.pop("dias_sel", None)

    tasks = get_tasks(uid)
    tasks.append(tarea)
    save_tasks(uid, tasks)
    del user_state[uid]

    dias_str = days_label(tarea.get("dias", list(DAY_INDEX.keys())))
    hora_fin_str = f" → {tarea['hora_fin']}" if tarea.get("hora_fin") else ""

    bot.edit_message_text(
        f"✅ *¡Actividad guardada!*\n\n"
        f"📌 {tarea['nombre']}\n"
        f"⏰ {tarea['hora']}{hora_fin_str}\n"
        f"📅 {dias_str}\n"
        f"📂 {CATEGORIES[cat_key]}",
        call.message.chat.id, call.message.message_id, parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id)

# ── /eliminar ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["eliminar"])
def cmd_eliminar(message):
    tasks = get_tasks(message.from_user.id)
    if not tasks:
        bot.send_message(message.chat.id, "📭 No tenés actividades para eliminar.")
        return

    kb = InlineKeyboardMarkup()
    for i, t in enumerate(tasks):
        hora_fin_str = f" → {t['hora_fin']}" if t.get("hora_fin") else ""
        kb.add(InlineKeyboardButton(
            f"🗑 {t['nombre']} ({t['hora']}{hora_fin_str})",
            callback_data=f"del_{i}"
        ))
    kb.add(InlineKeyboardButton("❌ Cancelar", callback_data="del_cancel"))
    bot.send_message(message.chat.id, "¿Qué actividad querés eliminar?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def confirmar_eliminacion(call):
    if call.data == "del_cancel":
        bot.edit_message_text("❌ Cancelado.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    uid = call.from_user.id
    idx = int(call.data.replace("del_", ""))
    tasks = get_tasks(uid)

    if 0 <= idx < len(tasks):
        eliminada = tasks.pop(idx)
        save_tasks(uid, tasks)
        bot.edit_message_text(
            f"🗑 Eliminada: *{eliminada['nombre']}*",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown"
        )
    bot.answer_callback_query(call.id)

# ── /completadas ───────────────────────────────────────────────────────────────

def build_completadas_kb(tasks):
    kb = InlineKeyboardMarkup()
    for i, t in enumerate(tasks):
        estado = "✅" if t.get("completada_hoy") else "⬜"
        hora_fin_str = f" → {t['hora_fin']}" if t.get("hora_fin") else ""
        kb.add(InlineKeyboardButton(
            f"{estado} {t['nombre']} ({t['hora']}{hora_fin_str})",
            callback_data=f"toggle_{i}"
        ))
    kb.add(InlineKeyboardButton("🔄 Resetear todas", callback_data="reset_all"))
    kb.add(InlineKeyboardButton("✖ Cerrar", callback_data="close"))
    return kb

@bot.message_handler(commands=["completadas"])
def cmd_completadas(message):
    tasks = get_tasks(message.from_user.id)
    if not tasks:
        bot.send_message(message.chat.id, "📭 No tenés actividades registradas.")
        return
    bot.send_message(message.chat.id, "📋 *Marcá tus tareas de hoy:*",
                     reply_markup=build_completadas_kb(tasks), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("toggle_") or c.data in ["reset_all", "close"])
def toggle_completada(call):
    uid = call.from_user.id
    tasks = get_tasks(uid)

    if call.data == "close":
        bot.edit_message_text("👍 ¡Listo!", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    if call.data == "reset_all":
        for t in tasks:
            t["completada_hoy"] = False
    else:
        idx = int(call.data.replace("toggle_", ""))
        if 0 <= idx < len(tasks):
            tasks[idx]["completada_hoy"] = not tasks[idx].get("completada_hoy", False)

    save_tasks(uid, tasks)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                   reply_markup=build_completadas_kb(tasks))
    bot.answer_callback_query(call.id)

# ── Recordatorio diario ────────────────────────────────────────────────────────

def enviar_recordatorio_diario():
    hoy = datetime.now().weekday()
    dia_key = ["lun","mar","mie","jue","vie","sab","dom"][hoy]

    data = load_data()
    for user_id, tasks in data.items():
        tareas_hoy = [t for t in tasks if dia_key in t.get("dias", list(DAY_INDEX.keys()))]
        if not tareas_hoy:
            continue

        msg = f"☀️ *¡Buenos días! Tus actividades de hoy ({DAYS[dia_key]}):*\n\n"
        for cat_key, cat_label in CATEGORIES.items():
            cat_tasks = [t for t in tareas_hoy if t["categoria"] == cat_key]
            if cat_tasks:
                msg += f"*{cat_label}*\n"
                for t in cat_tasks:
                    hora_fin_str = f" → {t['hora_fin']}" if t.get("hora_fin") else ""
                    msg += f"  ⬜ {t['nombre']} — {t['hora']}{hora_fin_str}\n"
                msg += "\n"
        msg += "Usá /completadas para marcar lo que vayas haciendo 💪"

        for t in tasks:
            t["completada_hoy"] = False
        save_tasks(user_id, tasks)

        try:
            bot.send_message(int(user_id), msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"No se pudo enviar a {user_id}: {e}")

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")
    scheduler.add_job(enviar_recordatorio_diario, trigger="cron", hour=7, minute=0)
    scheduler.start()

    logger.info("✅ Bot iniciado. Esperando mensajes...")
    bot.infinity_polling()
