"""
Componentes de interfaz (Modals y Views) para las quedadas.

EventView es persistente (timeout=None, custom_id fijo por evento) para que
los botones sigan funcionando después de reiniciar el bot; bot.py se encarga
de volver a registrar una instancia por cada evento activo/cerrado en su
setup_hook.
"""
import logging
from datetime import datetime
from typing import Optional

import discord

from embeds import build_event_embed

logger = logging.getLogger("quedadas.views")

MAX_DESCRIPTION_LENGTH = 1000  # margen bajo el límite de 1024 de un field de Embed


def parse_fecha(value: str) -> str:
    """Valida DD/MM/AAAA. Lanza ValueError si el formato no es válido."""
    dt = datetime.strptime(value.strip(), "%d/%m/%Y")
    return dt.strftime("%d/%m/%Y")


def parse_hora(value: str) -> str:
    """Valida HH:MM (24h). Lanza ValueError si el formato no es válido."""
    dt = datetime.strptime(value.strip(), "%H:%M")
    return dt.strftime("%H:%M")


async def count_total_members(guild: Optional[discord.Guild]) -> int:
    """Aproxima cuántas personas podrían responder a una quedada.

    Limitación conocida: Discord no expone directamente cuántas personas
    pueden ver un canal concreto sin iterar sus permisos, y hacerlo con
    precisión requeriría el intent privilegiado de miembros (que este bot
    NO solicita a propósito, para mantener la configuración simple). Como
    alternativa razonable, usamos el número total de miembros del servidor
    (excluyendo bots) como aproximación de "sin responder". Si tu servidor
    tiene canales de quedadas restringidos a un rol concreto, este número
    será una sobreestimación; puedes ignorar el conteo "sin responder" o
    ajustar esta función a tu caso si lo necesitas.
    """
    if guild is None:
        return 0
    if guild.members and len(guild.members) >= (guild.member_count or 0):
        bots = sum(1 for m in guild.members if m.bot)
        return max((guild.member_count or 0) - bots, 0)
    # Sin caché de miembros disponible (no se activó el intent de miembros):
    # aproximamos restando únicamente al propio bot.
    return max((guild.member_count or 0) - 1, 0)


async def refresh_event_message(bot: discord.Client, event_id: int) -> None:
    """Reconstruye el Embed de una quedada y edita el mensaje original."""
    db = bot.db
    event = await db.get_event(event_id)
    if not event or not event["message_id"]:
        return

    channel = bot.get_channel(event["channel_id"])
    if channel is None:
        try:
            channel = await bot.fetch_channel(event["channel_id"])
        except discord.HTTPException:
            logger.warning(f"No se pudo obtener el canal {event['channel_id']} de la quedada {event_id}")
            return

    try:
        message = await channel.fetch_message(event["message_id"])
    except discord.NotFound:
        logger.warning(f"Mensaje de la quedada {event_id} no encontrado (¿se borró manualmente?)")
        return
    except discord.HTTPException as e:
        logger.error(f"Error al obtener el mensaje de la quedada {event_id}: {e}")
        return

    counts = await db.get_attendance_counts(event_id)
    guild = getattr(channel, "guild", None)
    total_members = await count_total_members(guild)

    creator = bot.get_user(event["creator_id"])
    creator_name = creator.display_name if creator else f"Usuario {event['creator_id']}"

    embed = build_event_embed(event, counts, total_members, creator_name)
    disabled = event["status"] in ("closed", "cancelled")
    view = EventView(event_id, disabled=disabled)

    try:
        await message.edit(embed=embed, view=view)
    except discord.HTTPException as e:
        logger.error(f"Error al actualizar el mensaje de la quedada {event_id}: {e}")


class EventView(discord.ui.View):
    """Vista persistente con los botones públicos de una quedada."""

    def __init__(self, event_id: int, disabled: bool = False):
        super().__init__(timeout=None)
        self.event_id = event_id

        # custom_id fijo y determinista -> permite reconstruir la vista tras un reinicio.
        self.attend_button.custom_id = f"quedada:attend:{event_id}"
        self.decline_button.custom_id = f"quedada:decline:{event_id}"
        self.attendees_button.custom_id = f"quedada:attendees:{event_id}"
        self.responses_button.custom_id = f"quedada:responses:{event_id}"

        if disabled:
            for item in self.children:
                item.disabled = True

    async def _set_status(self, interaction: discord.Interaction, status: str, label: str) -> None:
        db = interaction.client.db
        event = await db.get_event(self.event_id)
        if not event or event["status"] != "active":
            await interaction.response.send_message(
                "❌ Esta quedada ya no acepta respuestas.", ephemeral=True
            )
            return

        try:
            await db.set_attendance(self.event_id, interaction.user.id, status)
        except Exception as e:
            logger.error(f"Error al registrar asistencia en la quedada {self.event_id}: {e}")
            await interaction.response.send_message(
                "❌ No se pudo registrar tu respuesta. Inténtalo de nuevo.", ephemeral=True
            )
            return

        await interaction.response.send_message(label, ephemeral=True)
        await refresh_event_message(interaction.client, self.event_id)

    @discord.ui.button(label="Asistiré", style=discord.ButtonStyle.success, emoji="🟢")
    async def attend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_status(interaction, "attending", "✅ Tu asistencia ha sido registrada.")

    @discord.ui.button(label="No asistiré", style=discord.ButtonStyle.danger, emoji="🔴")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_status(interaction, "not_attending", "🔴 Has indicado que no asistirás.")

    @discord.ui.button(label="Ver asistentes", style=discord.ButtonStyle.secondary, emoji="👥", row=1)
    async def attendees_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        user_ids = await db.get_attendees(self.event_id, "attending")
        if not user_ids:
            await interaction.response.send_message("Todavía no hay nadie apuntado. 🙁", ephemeral=True)
            return

        lines = []
        for uid in user_ids:
            member = interaction.guild.get_member(uid) if interaction.guild else None
            name = member.display_name if member else f"<@{uid}>"
            lines.append(f"🟢 {name}")

        text = "\n".join(lines)
        if len(text) > 3800:
            text = text[:3800] + f"\n… y más ({len(user_ids)} en total)"

        embed = discord.Embed(
            title="👥 Personas que asistirán",
            description=text,
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Total: {len(user_ids)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Ver respuestas", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def responses_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        counts = await db.get_attendance_counts(self.event_id)
        attending = counts.get("attending", 0)
        not_attending = counts.get("not_attending", 0)
        total_members = await count_total_members(interaction.guild)
        no_response = max(total_members - attending - not_attending, 0)

        embed = discord.Embed(title="📋 Resumen de respuestas", color=discord.Color.blurple())
        embed.add_field(name="🟢 Asistirán", value=f"{attending} personas", inline=False)
        embed.add_field(name="🔴 No asistirán", value=f"{not_attending} personas", inline=False)
        embed.add_field(name="⚪ Sin respuesta", value=f"{no_response} personas (aprox.)", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EventFormModal(discord.ui.Modal):
    """Formulario reutilizado tanto para crear como para editar una quedada."""

    def __init__(self, *, title: str, on_submit_callback, defaults: Optional[dict] = None):
        super().__init__(title=title)
        defaults = defaults or {}
        self.on_submit_callback = on_submit_callback

        self.nombre = discord.ui.TextInput(
            label="Nombre de la quedada",
            placeholder="Tarde de Among Us",
            max_length=100,
            default=defaults.get("name", ""),
        )
        self.fecha = discord.ui.TextInput(
            label="Fecha (DD/MM/AAAA)",
            placeholder="30/08/2026",
            max_length=10,
            default=defaults.get("event_date", ""),
        )
        self.hora = discord.ui.TextInput(
            label="Hora (HH:MM, 24h)",
            placeholder="18:00",
            max_length=5,
            default=defaults.get("event_time", ""),
        )
        self.descripcion = discord.ui.TextInput(
            label="Descripción",
            style=discord.TextStyle.paragraph,
            placeholder="Vamos a jugar unas partidas de Among Us y después Minecraft.",
            max_length=MAX_DESCRIPTION_LENGTH,
            required=False,
            default=defaults.get("description", ""),
        )

        for item in (self.nombre, self.fecha, self.hora, self.descripcion):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        nombre = str(self.nombre.value).strip()
        descripcion = str(self.descripcion.value).strip() or "Sin descripción."

        if not nombre:
            await interaction.response.send_message("❌ El nombre no puede estar vacío.", ephemeral=True)
            return

        try:
            fecha = parse_fecha(str(self.fecha.value))
        except ValueError:
            await interaction.response.send_message(
                "❌ La fecha no es válida. Usa el formato DD/MM/AAAA, por ejemplo 30/08/2026.",
                ephemeral=True,
            )
            return

        try:
            hora = parse_hora(str(self.hora.value))
        except ValueError:
            await interaction.response.send_message(
                "❌ La hora no es válida. Usa el formato HH:MM en 24 horas, por ejemplo 18:00.",
                ephemeral=True,
            )
            return

        await self.on_submit_callback(interaction, nombre, descripcion, fecha, hora)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"Error en el formulario de quedada: {error}")
        message = "❌ Ocurrió un error al procesar el formulario."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class ConfirmCancelView(discord.ui.View):
    """Confirmación explícita antes de cancelar una quedada. No es persistente
    (solo vive mientras el administrador responde), por eso lleva timeout."""

    def __init__(self, event_id: int, *, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.event_id = event_id
        self.confirmed: Optional[bool] = None

    @discord.ui.button(label="Sí, cancelar quedada", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="⏳ Cancelando quedada…", view=self)
        self.stop()

    @discord.ui.button(label="No, mantener quedada", style=discord.ButtonStyle.secondary)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Cancelación abortada.", view=self)
        self.stop()
