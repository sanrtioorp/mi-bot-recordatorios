#!/usr/bin/env python3
"""
Bot de Telegram para recordatorios diarios.
Compatible con Python 3.13+
Usa pyTelegramBotAPI + APScheduler
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

# Estado temporal para el flujo de agregar tarea
user_state = {}   # user_id -> {"step": ..., "data": {...}}

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
        "⏰ Recibirás un resumen cada mañana a las 7:00 AM.",
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
                msg += f"  {done} {t['nombre']} — {t['hora']}\n"
            msg += "\n"
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

# ── /agregar (flujo por pasos) ─────────────────────────────────────────────────

@bot.message_handler(commands=["agregar"])
def cmd_agregar(message):
    user_state[message.from_user.id] = {"step": "nombre", "data": {}}
    bot.send_message(message.chat.id,
        "📝 ¿Cómo se llama la actividad?\n_(Ej: Reunión de equipo, Salir a correr)_",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id]["step"] == "nombre")
def recibir_nombre(message):
    user_state[message.from_user.id]["data"]["nombre"] = message.text.strip()
    user_state[message.from_user.id]["step"] = "hora"
    bot.send_message(message.chat.id,
        "⏰ ¿A qué hora? _(Formato 24hs, ej: 08:30 o 20:00)_",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id]["step"] == "hora")
def recibir_hora(message):
    hora = message.text.strip()
    try:
        datetime.strptime(hora, "%H:%M")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Formato inválido. Usá HH:MM (ej: 08:30)")
        return

    user_state[message.from_user.id]["data"]["hora"] = hora
    user_state[message.from_user.id]["step"] = "categoria"

    kb = InlineKeyboardMarkup()
    for key, label in CATEGORIES.items():
        kb.add(InlineKeyboardButton(label, callback_data=f"cat_{key}"))
    bot.send_message(message.chat.id, "📂 ¿En qué categoría?", reply_markup=kb)

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

    tasks = get_tasks(uid)
    tasks.append(tarea)
    save_tasks(uid, tasks)
    del user_state[uid]

    bot.edit_message_text(
        f"✅ *Guardado:*\n📌 {tarea['nombre']}\n⏰ {tarea['hora']}\n📂 {CATEGORIES[cat_key]}",
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
        kb.add(InlineKeyboardButton(f"🗑 {t['nombre']} ({t['hora']})", callback_data=f"del_{i}"))
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
        kb.add(InlineKeyboardButton(f"{estado} {t['nombre']} ({t['hora']})", callback_data=f"toggle_{i}"))
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
    data = load_data()
    for user_id, tasks in data.items():
        if not tasks:
            continue
        msg = "☀️ *¡Buenos días! Tus actividades de hoy:*\n\n"
        for cat_key, cat_label in CATEGORIES.items():
            cat_tasks = [t for t in tasks if t["categoria"] == cat_key]
            if cat_tasks:
                msg += f"*{cat_label}*\n"
                for t in cat_tasks:
                    msg += f"  ⬜ {t['nombre']} — {t['hora']}\n"
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
