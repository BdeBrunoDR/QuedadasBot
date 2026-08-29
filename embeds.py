"""
Construcción de los Embeds públicos de las quedadas.
"""
from datetime import datetime

import discord
from zoneinfo import ZoneInfo

import config

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def format_fecha_larga(event_date: str) -> str:
    """'DD/MM/AAAA' -> 'Domingo, 30 de agosto de 2026'"""
    dt = datetime.strptime(event_date, "%d/%m/%Y")
    dia = DIAS[dt.weekday()].capitalize()
    mes = MESES[dt.month - 1]
    return f"{dia}, {dt.day} de {mes} de {dt.year}"


def event_datetime(event: dict) -> datetime:
    """Devuelve un datetime consciente de la zona horaria configurada."""
    tz = ZoneInfo(config.TIMEZONE)
    naive = datetime.strptime(f"{event['event_date']} {event['event_time']}", "%d/%m/%Y %H:%M")
    return naive.replace(tzinfo=tz)


def build_event_embed(event: dict, counts: dict, total_members: int,
                       creator_name: str) -> discord.Embed:
    attending = counts.get("attending", 0)
    not_attending = counts.get("not_attending", 0)
    no_response = max(total_members - attending - not_attending, 0)

    status = event["status"]

    if status == "cancelled":
        embed = discord.Embed(
            title="❌ QUEDADA CANCELADA",
            description=f"**{event['name']}**\n\nEsta quedada ha sido cancelada.",
            color=discord.Color.red(),
        )
        embed.set_footer(text=f"Quedada #{event['id']} · Creada por {creator_name}")
        return embed

    color = discord.Color.blurple() if status == "active" else discord.Color.greyple()
    embed = discord.Embed(title=f"🎮 {event['name']}", color=color)

    try:
        fecha_larga = format_fecha_larga(event["event_date"])
    except ValueError:
        fecha_larga = event["event_date"]

    embed.add_field(name="📅 Fecha", value=fecha_larga, inline=True)
    embed.add_field(name="🕒 Hora", value=event["event_time"], inline=True)

    try:
        dt = event_datetime(event)
        embed.add_field(name="⏳", value=f"<t:{int(dt.timestamp())}:R>", inline=True)
    except ValueError:
        pass

    embed.add_field(name="📝 Descripción", value=event["description"], inline=False)
    embed.add_field(name="\u200b", value="━━━━━━━━━━━━━━━━━━━━", inline=False)

    asistencia_titulo = "🔒 ASISTENCIA CERRADA" if status == "closed" else "👥 ASISTENCIA"
    embed.add_field(
        name=asistencia_titulo,
        value=(
            f"🟢 **{attending}** asistirán\n"
            f"🔴 **{not_attending}** no asistirán\n"
            f"⚪ **{no_response}** sin responder"
        ),
        inline=False,
    )

    embed.set_footer(text=f"Quedada #{event['id']} · Creada por {creator_name}")
    return embed
