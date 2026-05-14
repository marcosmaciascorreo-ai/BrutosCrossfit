import os
import logging

from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
    PicklePersistence,
)
from openai import AsyncOpenAI
from system_prompt import SYSTEM_PROMPT, estilo_aleatorio

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- STATES ---
(
    WOD_TIPO,
    WOD_TIEMPO,
    WOD_TIEMPO_CUSTOM,
    WOD_INTENSIDAD,
    WOD_ENFOQUE,
    WOD_NIVELES,
    WOD_CONFIRMAR,
    WOD_AJUSTE,
    WOD_CAMBIAR_MOV,
    SEM_ENFOQUE,
    SEM_DURACION,
    SEM_DURACION_CUSTOM,
    SEM_EXTRAS,
    SEM_NIVELES,
    SEM_CONFIRMAR,
    SKILL_SELECCION,
) = range(16)

# --- SKILL NAMES MAP ---
SKILL_NOMBRES = {
    "skill_mup_barra":  "Muscle-up en barra",
    "skill_mup_ring":   "Muscle-up en argolla",
    "skill_hspu":       "Handstand Push-up (HSPU)",
    "skill_hsw":        "Handstand Walk",
    "skill_pistol":     "Pistol Squat",
    "skill_legless":    "Rope Climb Legless (sin piernas)",
    "skill_t2b":        "Toes-to-Bar",
    "skill_du":         "Double Unders",
    "skill_ringdip":    "Strict Ring Dip",
    "skill_lsit":       "L-sit",
    "skill_snatch":     "Snatch",
    "skill_cj":         "Clean & Jerk",
    "skill_ohs":        "Overhead Squat",
    "skill_jerk":       "Split Jerk",
    "skill_fs":         "Front Squat",
    "skill_bear":       "Bear Complex",
    "skill_sled":       "Sled Push/Drag",
    "skill_farmer":     "Farmer Carry pesado",
    "skill_row":        "Remo ergómetro — técnica y potencia",
    "skill_ski":        "Ski Erg — técnica y potencia",
}

# --- HELPERS ---
def extraer_movimientos(wod_text: str) -> tuple:
    lines = wod_text.strip().split('\n')
    movimientos = ""
    wod_limpio = []
    for line in lines:
        if line.strip().startswith("MOVIMIENTOS_USADOS:"):
            movimientos = line.replace("MOVIMIENTOS_USADOS:", "").strip()
        else:
            wod_limpio.append(line)
    return '\n'.join(wod_limpio).strip(), movimientos

def get_semana_key() -> str:
    year, week, _ = datetime.now().isocalendar()
    return f"{year}_w{week}"

def get_movimientos_semana(user_data: dict) -> list:
    return user_data.get('semana_wods', {}).get(get_semana_key(), [])

def guardar_movimientos_semana(user_data: dict, movimientos_str: str) -> None:
    key = get_semana_key()
    user_data.setdefault('semana_wods', {})
    for old in [k for k in user_data['semana_wods'] if k != key]:
        del user_data['semana_wods'][old]
    dia = datetime.now().strftime('%A')
    user_data['semana_wods'].setdefault(key, [])
    if movimientos_str:
        user_data['semana_wods'][key].append(f"{dia}: {movimientos_str}")

# --- KEYBOARDS ---
def teclado_menu_inicio() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💀 GENERAR WOD DE HOY",     callback_data="menu_wod")],
        [InlineKeyboardButton("📅 PROGRAMAR LA SEMANA",    callback_data="menu_semana")],
        [InlineKeyboardButton("🎯 SKILL DAY",              callback_data="menu_skill")],
        [InlineKeyboardButton("🏆 BENCHMARK CLÁSICO",     callback_data="menu_benchmark")],
        [InlineKeyboardButton("💡 TIP DE MOVIMIENTO",      callback_data="menu_tip")],
    ])

def teclado_tipo_wod():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("AMRAP",    callback_data="tipo_amrap"),
            InlineKeyboardButton("FOR TIME", callback_data="tipo_fortime"),
            InlineKeyboardButton("EMOM",     callback_data="tipo_emom"),
        ],
        [
            InlineKeyboardButton("CHIPPER",  callback_data="tipo_chipper"),
            InlineKeyboardButton("LADDER",   callback_data="tipo_ladder"),
            InlineKeyboardButton("TABATA",   callback_data="tipo_tabata"),
        ],
        [InlineKeyboardButton("💀 SORPRÉNDEME CABRÓN", callback_data="tipo_random")],
    ])

def teclado_tiempo():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("10 min", callback_data="tiempo_10"),
            InlineKeyboardButton("15 min", callback_data="tiempo_15"),
            InlineKeyboardButton("20 min", callback_data="tiempo_20"),
        ],
        [
            InlineKeyboardButton("25 min", callback_data="tiempo_25"),
            InlineKeyboardButton("30 min", callback_data="tiempo_30"),
            InlineKeyboardButton("35 min", callback_data="tiempo_35"),
        ],
        [InlineKeyboardButton("✏️ ESCRIBIR MINUTOS", callback_data="tiempo_custom")],
    ])

def teclado_intensidad():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 LIGERO — Casi un spa",                    callback_data="int_ligero")],
        [InlineKeyboardButton("🟡 MODERADO — Sale destruido pero funcional", callback_data="int_moderado")],
        [InlineKeyboardButton("🔴 INTENSO — Duda de sus decisiones",        callback_data="int_intenso")],
        [InlineKeyboardButton("💀 BESTIA — Ya no tiene sentimientos",       callback_data="int_bestia")],
    ])

def teclado_enfoque():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("MIXTO",          callback_data="enf_mixto"),
            InlineKeyboardButton("PIERNAS",        callback_data="enf_piernas"),
        ],
        [
            InlineKeyboardButton("HOMBROS / JALÓN", callback_data="enf_hombros"),
            InlineKeyboardButton("CARDIO PURO",    callback_data="enf_cardio"),
        ],
        [
            InlineKeyboardButton("OLÍMPICO",       callback_data="enf_olimpico"),
            InlineKeyboardButton("KETTLEBELL",     callback_data="enf_kb"),
        ],
    ])

def teclado_niveles():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 LOS 3 NIVELES (recomendado)", callback_data="niv_todos")],
        [
            InlineKeyboardButton("🔥 SOLO RX",     callback_data="niv_rx"),
            InlineKeyboardButton("⚡ SOLO SCALED", callback_data="niv_scaled"),
        ],
        [InlineKeyboardButton("🌱 SOLO MASTERS/BEGINNER", callback_data="niv_masters")],
    ])

def teclado_confirmar_wod():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ GENERAR WOD",   callback_data="confirmar_wod")],
        [InlineKeyboardButton("🔄 CAMBIAR ALGO", callback_data="reiniciar_wod")],
    ])

def teclado_ajuste_wod():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏱ Más corto",  callback_data="ajuste_corto"),
            InlineKeyboardButton("⏱ Más largo",  callback_data="ajuste_largo"),
        ],
        [
            InlineKeyboardButton("⬆️ Más pesado", callback_data="ajuste_pesado"),
            InlineKeyboardButton("❤️ Más cardio", callback_data="ajuste_cardio"),
        ],
        [InlineKeyboardButton("⚙️ Cambiar un movimiento", callback_data="ajuste_cambiar")],
        [InlineKeyboardButton("✅ Perfecto, lo uso",       callback_data="ajuste_ok")],
    ])

# SEMANA KEYBOARDS
def teclado_semana_enfoque():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PROGRAMA GENERAL — Todo balanceado",         callback_data="sem_enf_general")],
        [InlineKeyboardButton("FUERZA — Levantamos pesado",                callback_data="sem_enf_fuerza")],
        [InlineKeyboardButton("CARDIO Y RESISTENCIA — Pulmones de acero",  callback_data="sem_enf_cardio")],
        [InlineKeyboardButton("TÉCNICA — Menos peso, más cerebro",         callback_data="sem_enf_tecnica")],
        [InlineKeyboardButton("COMPETENCIA — Programación de atleta serio", callback_data="sem_enf_competencia")],
        [InlineKeyboardButton("SORPRÉNDEME — BRUTUS decide todo",          callback_data="sem_enf_sorpresa")],
    ])

def teclado_semana_duracion():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("45 min", callback_data="sem_dur_45"),
            InlineKeyboardButton("60 min", callback_data="sem_dur_60"),
        ],
        [
            InlineKeyboardButton("75 min", callback_data="sem_dur_75"),
            InlineKeyboardButton("90 min", callback_data="sem_dur_90"),
        ],
        [InlineKeyboardButton("✏️ ESCRIBIR MINUTOS", callback_data="sem_dur_custom")],
    ])

def teclado_semana_extras(extras_seleccionados):
    def check(key):
        return "✅" if key in extras_seleccionados else "❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{check('calentamiento')} CALENTAMIENTO ESPECÍFICO",  callback_data="sem_ext_calentamiento")],
        [InlineKeyboardButton(f"{check('fuerza')} BLOQUE DE FUERZA ANTES DEL WOD",  callback_data="sem_ext_fuerza")],
        [InlineKeyboardButton(f"{check('enfriamiento')} ENFRIAMIENTO / MOVILIDAD",  callback_data="sem_ext_enfriamiento")],
        [InlineKeyboardButton("➡️ CONTINUAR", callback_data="sem_ext_continuar")],
    ])

def teclado_semana_niveles():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 LOS 3 NIVELES",  callback_data="sem_niv_todos")],
        [InlineKeyboardButton("🔥 SOLO RX",        callback_data="sem_niv_rx")],
        [InlineKeyboardButton("⚡ SOLO SCALED",    callback_data="sem_niv_scaled")],
    ])

def teclado_confirmar_semana():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ GENERAR SEMANA COMPLETA", callback_data="confirmar_semana")],
        [InlineKeyboardButton("🔄 CAMBIAR ALGO",           callback_data="reiniciar_semana")],
    ])

# SKILL KEYBOARDS
def teclado_skill_categoria():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤸 GIMNASIA",                    callback_data="skill_cat_gimnasia")],
        [InlineKeyboardButton("🏋️ HALTEROFILIA",               callback_data="skill_cat_halterofilia")],
        [InlineKeyboardButton("🏃 MONOSTRUCTURAL / CARGAMENTOS", callback_data="skill_cat_mono")],
    ])

def teclado_skill_gimnasia():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Muscle-up barra",     callback_data="skill_mup_barra"),
            InlineKeyboardButton("Muscle-up argolla",   callback_data="skill_mup_ring"),
        ],
        [
            InlineKeyboardButton("HSPU",                callback_data="skill_hspu"),
            InlineKeyboardButton("Handstand Walk",      callback_data="skill_hsw"),
        ],
        [
            InlineKeyboardButton("Pistol Squat",        callback_data="skill_pistol"),
            InlineKeyboardButton("Rope Climb Legless",  callback_data="skill_legless"),
        ],
        [
            InlineKeyboardButton("Toes-to-Bar",         callback_data="skill_t2b"),
            InlineKeyboardButton("Double Unders",       callback_data="skill_du"),
        ],
        [
            InlineKeyboardButton("Ring Dip",            callback_data="skill_ringdip"),
            InlineKeyboardButton("L-sit",               callback_data="skill_lsit"),
        ],
        [InlineKeyboardButton("◀️ Volver", callback_data="skill_cat_volver")],
    ])

def teclado_skill_halterofilia():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Snatch",          callback_data="skill_snatch"),
            InlineKeyboardButton("Clean & Jerk",    callback_data="skill_cj"),
        ],
        [
            InlineKeyboardButton("Overhead Squat",  callback_data="skill_ohs"),
            InlineKeyboardButton("Split Jerk",      callback_data="skill_jerk"),
        ],
        [
            InlineKeyboardButton("Front Squat",     callback_data="skill_fs"),
            InlineKeyboardButton("Bear Complex",    callback_data="skill_bear"),
        ],
        [InlineKeyboardButton("◀️ Volver", callback_data="skill_cat_volver")],
    ])

def teclado_skill_mono():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Sled Push/Drag",  callback_data="skill_sled"),
            InlineKeyboardButton("Farmer Carry",    callback_data="skill_farmer"),
        ],
        [
            InlineKeyboardButton("Remo Técnico",    callback_data="skill_row"),
            InlineKeyboardButton("Ski Erg",         callback_data="skill_ski"),
        ],
        [InlineKeyboardButton("◀️ Volver", callback_data="skill_cat_volver")],
    ])

# --- START / MENU ---
async def cmd_start(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    nombre = update.effective_user.first_name or "Atleta"
    bienvenida = (
        f"💀 *BRUTUS — Head Coach del Box*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Bienvenido, *{nombre}*. Aquí no hay días fáciles.\n\n"
        f"*¿Qué puedo hacer por ti?*\n\n"
        f"💀 */wod* — Genera el WOD de hoy\n"
        f"   Elige tipo, tiempo, intensidad y enfoque muscular.\n\n"
        f"📅 */semana* — Programa toda la semana\n"
        f"   6 días de programación completa.\n\n"
        f"🎯 */skill* — Skill Day\n"
        f"   Selecciona una habilidad y BRUTUS arma la sesión completa.\n\n"
        f"🏆 */benchmark* — WOD clásico directo\n"
        f"   Fran, Cindy, Helen, Murph o versión BRUTUS.\n\n"
        f"💡 */tip [movimiento]* — Tip técnico inmediato\n"
        f"   Ejemplo: `/tip rope climb` · `/tip snatch`\n\n"
        f"✏️ */nombre* — Genera 5 nombres de WOD estilo BRUTUS\n\n"
        f"❓ */ayuda* — Ver esta pantalla\n"
        f"🚫 */cancel* — Cancela cualquier flujo activo\n"
        f"🔄 */reset* — Limpia estado atascado\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Equipo:* Barras · Discos · Mancuernas · KB · Cajones · Rings · "
        f"Rope climb · Rower · Air bike · Ski erg · Med balls · Sand bags · GHD · Sled\n\n"
        f"Elige o usa un comando directo:"
    )
    await update.message.reply_text(
        bienvenida,
        parse_mode="Markdown",
        reply_markup=teclado_menu_inicio(),
    )

async def handle_menu_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "menu_benchmark":
        await cmd_benchmark_from_query(query, context)
    elif query.data == "menu_tip":
        await query.message.reply_text(
            "Escríbeme el movimiento:\n`/tip rope climb`\n`/tip double under`\n`/tip snatch`",
            parse_mode="Markdown",
        )

async def cmd_benchmark_from_query(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await query.message.reply_text("Generando Benchmark WOD... 🔨")
    await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
    prompt = "Genera un WOD Benchmark clásico de CrossFit (Fran, Cindy, Helen, Murph, etc.) o una versión BRUTUS de uno de ellos. Aplica el formato WOD DEL DÍA con calentamiento."
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.85,
            max_tokens=1800,
        )
        wod_text, _ = extraer_movimientos(response.choices[0].message.content)
        await query.message.reply_text(wod_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error benchmark: {e}")
        await query.message.reply_text("Error de red. Intenta con /benchmark")

# --- WOD FLOW ---
async def start_wod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.setdefault('wods_generados', [])
    msg = "Empecemos. ¿Cómo quieres sufrir hoy?"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg, reply_markup=teclado_tipo_wod())
    else:
        await update.message.reply_text(msg, reply_markup=teclado_tipo_wod())
    return WOD_TIPO

async def handle_wod_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "reiniciar_wod":
        return await start_wod(update, context)
    tipo = query.data.replace("tipo_", "").upper()
    context.user_data['wod_tipo'] = tipo
    await query.edit_message_text(
        f"Tipo: {tipo}\n\n¿Cuántos minutos?",
        reply_markup=teclado_tiempo()
    )
    return WOD_TIEMPO

async def handle_wod_tiempo_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "tiempo_custom":
        await query.edit_message_text("⌨️ Escribe cuántos minutos (entre 5 y 60):")
        return WOD_TIEMPO_CUSTOM
    mins = query.data.replace("tiempo_", "")
    context.user_data['wod_tiempo'] = mins
    await query.edit_message_text(
        f"Tiempo: {mins} min.\n\n¿Qué tan arrepentido quieres salir?",
        reply_markup=teclado_intensidad()
    )
    return WOD_INTENSIDAD

async def handle_wod_tiempo_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.message.text.strip()
    if texto.isdigit() and 5 <= int(texto) <= 60:
        context.user_data['wod_tiempo'] = texto
        await update.message.reply_text(
            f"Tiempo: {texto} min.\n\n¿Qué tan arrepentido quieres salir?",
            reply_markup=teclado_intensidad()
        )
        return WOD_INTENSIDAD
    await update.message.reply_text("Escribe un número entre 5 y 60.")
    return WOD_TIEMPO_CUSTOM

async def handle_wod_intensidad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    int_map = {
        "int_ligero":   "LIGERO",
        "int_moderado": "MODERADO",
        "int_intenso":  "INTENSO",
        "int_bestia":   "BESTIA",
    }
    intensidad = int_map[query.data]
    context.user_data['wod_intensidad'] = intensidad
    prefix = "💀 ...está bien. Tú lo pediste.\n\n" if query.data == "int_bestia" else ""
    await query.edit_message_text(
        f"{prefix}Intensidad: {intensidad}\n\n¿Qué parte del cuerpo quieres odiar mañana?",
        reply_markup=teclado_enfoque()
    )
    return WOD_ENFOQUE

async def handle_wod_enfoque(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    enf_map = {
        "enf_mixto":    "MIXTO",
        "enf_piernas":  "PIERNAS",
        "enf_hombros":  "HOMBROS Y JALÓN",
        "enf_cardio":   "CARDIO PURO",
        "enf_olimpico": "OLÍMPICO",
        "enf_kb":       "KETTLEBELL",
    }
    context.user_data['wod_enfoque'] = enf_map[query.data]
    await query.edit_message_text(
        f"Enfoque: {context.user_data['wod_enfoque']}\n\n¿Para quién genero las escalas?",
        reply_markup=teclado_niveles()
    )
    return WOD_NIVELES

async def handle_wod_niveles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    niv_map = {
        "niv_todos":   "LOS 3 NIVELES",
        "niv_rx":      "SOLO RX",
        "niv_scaled":  "SOLO SCALED",
        "niv_masters": "SOLO MASTERS/BEGINNER",
    }
    context.user_data['wod_niveles'] = niv_map[query.data]
    ud = context.user_data
    summary = (
        "Confirmando tu tortura:\n"
        f"• Tipo: {ud['wod_tipo']}\n"
        f"• Tiempo: {ud['wod_tiempo']} minutos\n"
        f"• Intensidad: {ud['wod_intensidad']}\n"
        f"• Enfoque: {ud['wod_enfoque']}\n"
        f"• Niveles: {ud['wod_niveles']}\n\n"
        "¿Le metemos?"
    )
    await query.edit_message_text(summary, reply_markup=teclado_confirmar_wod())
    return WOD_CONFIRMAR

async def _llamar_openai_wod(prompt: str, max_tokens: int = 1800) -> str:
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.85,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content

async def generate_wod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "reiniciar_wod":
        return await start_wod(update, context)

    await query.edit_message_text("Construyendo tu sufrimiento... 🔨")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    ud = context.user_data
    estilo = estilo_aleatorio()

    tipo_raw = ud['wod_tipo']
    tipo_definiciones = {
        'AMRAP':    'AMRAP — As Many Rounds/Reps As Possible. Lista de movimientos con reps por ronda.',
        'FORTIME':  'FOR TIME — Completar X rondas o total de reps lo más rápido posible.',
        'EMOM':     'EMOM — Every Minute On the Minute. Cada minuto un movimiento o secuencia.',
        'CHIPPER':  'CHIPPER — Lista larga de ejercicios, una sola ronda, en orden.',
        'LADDER':   'LADDER — Reps suben o bajan cada ronda (ej. 2-4-6-8 o 21-15-9).',
        'TABATA':   'TABATA — 20s trabajo / 10s descanso × 8 intervalos por movimiento.',
        'RANDOM':   'RANDOM — Tú eliges el tipo más apropiado y lo especificas en el output.',
    }
    tipo_instruccion = tipo_definiciones.get(tipo_raw, tipo_raw)

    movimientos_semana = get_movimientos_semana(ud)
    semana_info = '\n'.join(movimientos_semana) if movimientos_semana else 'Primera sesión de la semana — libertad total.'

    prompt = f"""
Genera un WOD de CrossFit con estos parámetros. El TIPO es OBLIGATORIO — no lo cambies:

▶ TIPO (NO CAMBIAR): {tipo_instruccion}
▶ Duración del WOD: {ud['wod_tiempo']} minutos
▶ Intensidad: {ud['wod_intensidad']}
▶ Enfoque muscular: {ud['wod_enfoque']}
▶ Niveles a mostrar: {ud['wod_niveles']}

MOVIMIENTOS USADOS ESTA SEMANA (no repitas los principales):
{semana_info}

Incluye calentamiento específico de 8-10 min para los movimientos del día.
Sigue el formato WOD DEL DÍA de tu sistema (con sección CALENTAMIENTO).
El nombre del WOD debe ser estilo [{estilo}].

Al final de toda la respuesta, en una línea aparte sin formato:
MOVIMIENTOS_USADOS: [lista los 5-8 movimientos principales separados por coma]
"""
    try:
        wod_text = await _llamar_openai_wod(prompt)
        wod_limpio, movimientos = extraer_movimientos(wod_text)

        guardar_movimientos_semana(ud, movimientos)
        ud['wod_actual'] = wod_limpio

        await query.message.reply_text(wod_limpio, parse_mode="Markdown", reply_markup=teclado_ajuste_wod())

    except Exception as e:
        logger.error(f"Error WOD: {e}")
        await query.message.reply_text("Error de red. Usa /wod para intentar de nuevo.")
        return ConversationHandler.END

    return WOD_AJUSTE

async def handle_ajuste_wod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "ajuste_ok":
        await query.edit_message_reply_markup(reply_markup=None)
        return ConversationHandler.END

    if query.data == "ajuste_cambiar":
        await query.message.reply_text(
            "¿Qué movimiento cambias?\nEscríbelo en texto:\n"
            "_ej: 'no tenemos rower hoy' / 'cambia el rope climb por algo equivalente'_",
            parse_mode="Markdown"
        )
        return WOD_CAMBIAR_MOV

    ajuste_map = {
        "ajuste_corto":  "Acorta el WOD — reduce el tiempo o las reps manteniendo la estructura y el tipo.",
        "ajuste_largo":  "Alarga el WOD — aumenta el tiempo o agrega una ronda o movimiento extra.",
        "ajuste_pesado": "Sube los pesos en todos los movimientos que lo permitan. Mantén movimientos y estructura.",
        "ajuste_cardio": "Refuerza el componente cardiovascular — agrega o aumenta el monostructural (calories, reps de DU, etc.).",
    }
    instruccion = ajuste_map.get(query.data, "")
    wod_original = context.user_data.get('wod_actual', '')

    await query.edit_message_reply_markup(reply_markup=None)
    msg = await query.message.reply_text("Ajustando... 🔨")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    prompt = f"""
Este es el WOD generado:

{wod_original}

AJUSTE SOLICITADO: {instruccion}

Aplica solo ese ajuste. Mantén el nombre, el tipo, la estructura y el calentamiento.
Devuelve el WOD completo en el mismo formato.
Al final agrega: MOVIMIENTOS_USADOS: [movimientos principales]
"""
    try:
        wod_text = await _llamar_openai_wod(prompt)
        wod_limpio, movimientos = extraer_movimientos(wod_text)
        context.user_data['wod_actual'] = wod_limpio
        guardar_movimientos_semana(context.user_data, movimientos)

        await msg.delete()
        await query.message.reply_text(wod_limpio, parse_mode="Markdown", reply_markup=teclado_ajuste_wod())

    except Exception as e:
        logger.error(f"Error ajuste: {e}")
        await msg.edit_text("Error al ajustar. Intenta de nuevo.")

    return WOD_AJUSTE

async def handle_cambiar_movimiento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    instruccion = update.message.text.strip()
    wod_original = context.user_data.get('wod_actual', '')

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    prompt = f"""
Este es el WOD generado:

{wod_original}

El coach pide este cambio específico: "{instruccion}"

Aplica solo ese cambio. Mantén todo lo demás exactamente igual.
Devuelve el WOD completo en el mismo formato.
Al final agrega: MOVIMIENTOS_USADOS: [movimientos principales]
"""
    try:
        wod_text = await _llamar_openai_wod(prompt)
        wod_limpio, movimientos = extraer_movimientos(wod_text)
        context.user_data['wod_actual'] = wod_limpio
        guardar_movimientos_semana(context.user_data, movimientos)

        await update.message.reply_text(wod_limpio, parse_mode="Markdown", reply_markup=teclado_ajuste_wod())

    except Exception as e:
        logger.error(f"Error cambio movimiento: {e}")
        await update.message.reply_text("Error al cambiar. Intenta de nuevo.")

    return WOD_AJUSTE

# --- SEMANA FLOW ---
async def start_semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.setdefault('wods_generados', [])
    context.user_data['sem_extras'] = set()
    text = "¿Qué trabajamos esta semana?"
    if update.message:
        await update.message.reply_text(text, reply_markup=teclado_semana_enfoque())
    else:
        await update.callback_query.message.reply_text(text, reply_markup=teclado_semana_enfoque())
    return SEM_ENFOQUE

async def handle_sem_enfoque(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "reiniciar_semana":
        return await start_semana(update, context)
    enf_map = {
        "sem_enf_general":     "PROGRAMA GENERAL",
        "sem_enf_fuerza":      "FUERZA",
        "sem_enf_cardio":      "CARDIO Y RESISTENCIA",
        "sem_enf_tecnica":     "TÉCNICA",
        "sem_enf_competencia": "COMPETENCIA",
        "sem_enf_sorpresa":    "SORPRÉNDEME",
    }
    context.user_data['sem_enfoque'] = enf_map[query.data]
    await query.edit_message_text(
        f"Enfoque: {context.user_data['sem_enfoque']}\n\n¿Cuánto dura cada clase?",
        reply_markup=teclado_semana_duracion()
    )
    return SEM_DURACION

async def handle_sem_duracion_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "sem_dur_custom":
        await query.edit_message_text("⌨️ Escribe cuántos minutos por clase:")
        return SEM_DURACION_CUSTOM
    mins = query.data.replace("sem_dur_", "")
    context.user_data['sem_duracion'] = mins
    await query.edit_message_text(
        f"Duración: {mins} min\n\n¿Qué incluyo en cada día?",
        reply_markup=teclado_semana_extras(context.user_data['sem_extras'])
    )
    return SEM_EXTRAS

async def handle_sem_duracion_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.message.text.strip()
    if texto.isdigit():
        context.user_data['sem_duracion'] = texto
        await update.message.reply_text(
            f"Duración: {texto} min\n\n¿Qué incluyo en cada día?",
            reply_markup=teclado_semana_extras(context.user_data['sem_extras'])
        )
        return SEM_EXTRAS
    await update.message.reply_text("Escribe un número.")
    return SEM_DURACION_CUSTOM

async def handle_sem_extras(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "sem_ext_continuar":
        await query.edit_message_text(
            "Extras seleccionados.\n\n¿Para quién genero las escalas?",
            reply_markup=teclado_semana_niveles()
        )
        return SEM_NIVELES
    ext_val = query.data.replace("sem_ext_", "")
    if ext_val in context.user_data['sem_extras']:
        context.user_data['sem_extras'].remove(ext_val)
    else:
        context.user_data['sem_extras'].add(ext_val)
    await query.edit_message_reply_markup(
        reply_markup=teclado_semana_extras(context.user_data['sem_extras'])
    )
    return SEM_EXTRAS

async def handle_sem_niveles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    niv_map = {
        "sem_niv_todos":  "LOS 3 NIVELES",
        "sem_niv_rx":     "SOLO RX",
        "sem_niv_scaled": "SOLO SCALED",
    }
    context.user_data['sem_niveles'] = niv_map[query.data]
    ud = context.user_data
    extras = list(ud['sem_extras']) if ud['sem_extras'] else ["Ninguno"]
    summary = (
        "Semana configurada:\n"
        f"• Enfoque: {ud['sem_enfoque']}\n"
        f"• Duración/clase: {ud['sem_duracion']} min\n"
        f"• Extras: {', '.join(extras)}\n"
        f"• Niveles: {ud['sem_niveles']}\n\n"
        "Confirmar:"
    )
    await query.edit_message_text(summary, reply_markup=teclado_confirmar_semana())
    return SEM_CONFIRMAR

async def generate_semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "reiniciar_semana":
        return await start_semana(update, context)

    await query.edit_message_text("Construyendo tu semana de sufrimiento... 🔨 Esto puede tardar.")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    ud = context.user_data
    extras = list(ud['sem_extras']) if ud['sem_extras'] else ["Solo el WOD"]

    prompt = f"""
Genera una SEMANA COMPLETA de CrossFit (Lunes a Domingo) con estos parámetros:
- Enfoque: {ud['sem_enfoque']}
- Duración por sesión: {ud['sem_duracion']} minutos
- Elementos por día: {', '.join(extras)}
- Niveles: {ud['sem_niveles']}

REGLA CRÍTICA: No repitas los mismos movimientos principales entre días. Rota modalidades cada día.
Sigue el formato WOD SEMANAL de tu sistema.
"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.85,
            max_tokens=3500,
        )
        wod_text = response.choices[0].message.content

        if len(wod_text) > 4000:
            lines = wod_text.split('\n')
            chunks, current = [], ""
            for line in lines:
                if len(current) + len(line) + 1 > 4000:
                    if current:
                        chunks.append(current)
                    current = line
                else:
                    current = current + '\n' + line if current else line
            if current:
                chunks.append(current)
            for chunk in chunks:
                await query.message.reply_text(chunk, parse_mode="Markdown")
        else:
            await query.message.reply_text(wod_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error SEMANA: {e}")
        await query.message.reply_text("Error de red. Usa /semana para intentar de nuevo.")

    return ConversationHandler.END

# --- SKILL DAY FLOW ---
async def start_skill(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = "¿Qué habilidad trabajamos hoy?"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg, reply_markup=teclado_skill_categoria())
    else:
        await update.message.reply_text(msg, reply_markup=teclado_skill_categoria())
    return SKILL_SELECCION

async def handle_skill_seleccion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "skill_cat_volver":
        await query.edit_message_text("¿Qué habilidad trabajamos hoy?", reply_markup=teclado_skill_categoria())
        return SKILL_SELECCION

    if query.data == "skill_cat_gimnasia":
        await query.edit_message_text("Elige el skill de GIMNASIA:", reply_markup=teclado_skill_gimnasia())
        return SKILL_SELECCION

    if query.data == "skill_cat_halterofilia":
        await query.edit_message_text("Elige el skill de HALTEROFILIA:", reply_markup=teclado_skill_halterofilia())
        return SKILL_SELECCION

    if query.data == "skill_cat_mono":
        await query.edit_message_text("Elige el skill de MONOSTRUCTURAL:", reply_markup=teclado_skill_mono())
        return SKILL_SELECCION

    # Es un skill real
    skill_nombre = SKILL_NOMBRES.get(query.data)
    if not skill_nombre:
        return SKILL_SELECCION

    await query.edit_message_text(f"Generando Skill Day: *{skill_nombre}*... 🔨", parse_mode="Markdown")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    prompt = f"""
Genera una sesión completa de SKILL DAY para desarrollar: {skill_nombre}

La sesión debe seguir el formato SKILL DAY de tu sistema con:
1. PROGRESIÓN TÉCNICA (15-20 min): 4 drills desde lo básico hasta el movimiento RX. Cada drill con sets/reps y cue técnico clave.
2. FUERZA ACCESORIA (10 min): 2-3 movimientos que fortalecen los músculos críticos para dominar este skill. Pesos en lbs.
3. METCON DE TRANSFERENCIA (8-12 min): WOD corto que incluye el skill o su variante más avanzada posible bajo fatiga. Con RX y SCALED.

Sé específico, técnico y con actitud BRUTUS. Todos los pesos en lbs.
"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.85,
            max_tokens=1800,
        )
        await query.message.reply_text(response.choices[0].message.content, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error Skill Day: {e}")
        await query.message.reply_text("Error de red. Intenta de nuevo con /skill")

    return ConversationHandler.END

# --- STANDALONE COMMANDS ---
async def cmd_benchmark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Generando Benchmark WOD... 🔨")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    prompt = "Genera un WOD Benchmark clásico de CrossFit o versión BRUTUS. Aplica el formato WOD DEL DÍA con calentamiento."
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.85,
            max_tokens=1800,
        )
        wod_limpio, _ = extraer_movimientos(response.choices[0].message.content)
        await update.message.reply_text(wod_limpio, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error benchmark: {e}")
        await update.message.reply_text("Error de red.")

async def cmd_tip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Dime el movimiento. Ejemplo: /tip rope climb")
        return
    movimiento = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    prompt = f"Dame un tip de coaching avanzado, brutal y directo para mejorar en: {movimiento}. Solo biomecánica, eficiencia y actitud BRUTUS."
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.85,
            max_tokens=500,
        )
        await update.message.reply_text(response.choices[0].message.content, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error tip: {e}")
        await update.message.reply_text("Error de red.")

async def cmd_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    prompt = "Genera 5 nombres de WODs usando diferentes estilos de tu banco. Lista con viñetas indicando el estilo."
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,
            max_tokens=500,
        )
        await update.message.reply_text(response.choices[0].message.content, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error nombre: {e}")
        await update.message.reply_text("Error de red.")

async def cmd_ayuda(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, _context)

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(
        "Estado reiniciado. Usa /wod o /semana para empezar de nuevo."
    )

async def cancel(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Sesión cancelada.")
    return ConversationHandler.END


# --- APP WIRING ---
def main() -> None:
    if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
        print("ERROR: Configura TELEGRAM_TOKEN y OPENAI_API_KEY")
        return

    persistence = PicklePersistence(filepath="bot_persistence.pkl")
    app = Application.builder().token(TELEGRAM_TOKEN).persistence(persistence).build()

    wod_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("wod", start_wod),
            CallbackQueryHandler(start_wod, pattern="^menu_wod$"),
        ],
        states={
            WOD_TIPO:         [CallbackQueryHandler(handle_wod_tipo,          pattern="^(tipo_|reiniciar_wod)")],
            WOD_TIEMPO:       [CallbackQueryHandler(handle_wod_tiempo_btn,    pattern="^tiempo_")],
            WOD_TIEMPO_CUSTOM:[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wod_tiempo_custom)],
            WOD_INTENSIDAD:   [CallbackQueryHandler(handle_wod_intensidad,    pattern="^int_")],
            WOD_ENFOQUE:      [CallbackQueryHandler(handle_wod_enfoque,       pattern="^enf_")],
            WOD_NIVELES:      [CallbackQueryHandler(handle_wod_niveles,       pattern="^niv_")],
            WOD_CONFIRMAR:    [CallbackQueryHandler(generate_wod,             pattern="^(confirmar_wod|reiniciar_wod)")],
            WOD_AJUSTE:       [CallbackQueryHandler(handle_ajuste_wod,        pattern="^ajuste_")],
            WOD_CAMBIAR_MOV:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cambiar_movimiento)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="wod_conv",
        persistent=True,
    )

    semana_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("semana", start_semana),
            CallbackQueryHandler(start_semana, pattern="^menu_semana$"),
        ],
        states={
            SEM_ENFOQUE:       [CallbackQueryHandler(handle_sem_enfoque,       pattern="^(sem_enf_|reiniciar_semana)")],
            SEM_DURACION:      [CallbackQueryHandler(handle_sem_duracion_btn,  pattern="^sem_dur_")],
            SEM_DURACION_CUSTOM:[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sem_duracion_custom)],
            SEM_EXTRAS:        [CallbackQueryHandler(handle_sem_extras,        pattern="^sem_ext_")],
            SEM_NIVELES:       [CallbackQueryHandler(handle_sem_niveles,       pattern="^sem_niv_")],
            SEM_CONFIRMAR:     [CallbackQueryHandler(generate_semana,          pattern="^(confirmar_semana|reiniciar_semana)")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="semana_conv",
        persistent=True,
    )

    skill_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("skill", start_skill),
            CallbackQueryHandler(start_skill, pattern="^menu_skill$"),
        ],
        states={
            SKILL_SELECCION: [CallbackQueryHandler(handle_skill_seleccion, pattern="^skill_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="skill_conv",
        persistent=True,
    )

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("ayuda",     cmd_ayuda))
    app.add_handler(CommandHandler("reset",     cmd_reset))
    app.add_handler(wod_conv_handler)
    app.add_handler(semana_conv_handler)
    app.add_handler(skill_conv_handler)
    app.add_handler(CallbackQueryHandler(handle_menu_inicio, pattern="^menu_(benchmark|tip)$"))
    app.add_handler(CommandHandler("benchmark", cmd_benchmark))
    app.add_handler(CommandHandler("tip",       cmd_tip))
    app.add_handler(CommandHandler("nombre",    cmd_nombre))
    app.add_handler(CommandHandler("skill",     start_skill))

    print("🌪️ BRUTUS Bot v3.0 — En línea. Esperando víctimas...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
