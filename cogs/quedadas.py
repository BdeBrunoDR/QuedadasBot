"""
Cog principal: comandos /quedada (crear, editar, cancelar, cerrar, lista, info).
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import views as views_module
from views import EventFormModal, EventView, ConfirmCancelView, refresh_event_message
from embeds import build_event_embed

logger = logging.getLogger("quedadas.cog")


def user_can_manage_events(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    if config.EVENT_MANAGER_ROLE_ID is None:
        return False
    return any(role.id == config.EVENT_MANAGER_ROLE_ID for role in interaction.user.roles)


def require_event_manager():
    async def predicate(interaction: discord.Interaction) -> bool:
        if user_can_manage_events(interaction):
            return True
        raise app_commands.CheckFailure("no_permission")
    return app_commands.check(predicate)


class QuedadasCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    quedada_group = app_commands.Group(name="quedada", description="Gestiona las quedadas del servidor")

    # ---------------- autocompletado ----------------

    async def _event_autocomplete(self, interaction: discord.Interaction, current: str, statuses):
        if not interaction.guild_id:
            return []
        events = await self.db.list_events(interaction.guild_id, statuses=statuses, limit=25)
        current_lower = current.lower()
        choices = []
        for event in events:
            label = f"{event['name']} · {event['event_date']} {event['event_time']}"
            if current_lower in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=event["id"]))
        return choices[:25]

    async def autocomplete_active(self, interaction: discord.Interaction, current: str):
        return await self._event_autocomplete(interaction, current, ["active"])

    async def autocomplete_active_or_closed(self, interaction: discord.Interaction, current: str):
        return await self._event_autocomplete(interaction, current, ["active", "closed"])

    async def autocomplete_any(self, interaction: discord.Interaction, current: str):
        return await self._event_autocomplete(interaction, current, None)

    # ---------------- /quedada crear ----------------

    @quedada_group.command(name="crear", description="Crea una nueva quedada")
    @require_event_manager()
    async def crear(self, interaction: discord.Interaction):
        async def on_submit(inter: discord.Interaction, nombre, descripcion, fecha, hora):
            channel = self.bot.get_channel(config.EVENT_CHANNEL_ID)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(config.EVENT_CHANNEL_ID)
                except discord.HTTPException:
                    await inter.response.send_message(
                        "❌ No se pudo encontrar el canal de quedadas configurado.", ephemeral=True
                    )
                    return

            try:
                event_id = await self.db.create_event(
                    guild_id=inter.guild_id,
                    channel_id=channel.id,
                    name=nombre,
                    description=descripcion,
                    event_date=fecha,
                    event_time=hora,
                    creator_id=inter.user.id,
                )
            except Exception as e:
                logger.error(f"Error al crear la quedada en la base de datos: {e}")
                await inter.response.send_message("❌ No se pudo crear la quedada.", ephemeral=True)
                return

            event = await self.db.get_event(event_id)
            counts = await self.db.get_attendance_counts(event_id)
            total_members = await views_module.count_total_members(inter.guild)
            embed = build_event_embed(event, counts, total_members, inter.user.display_name)
            view = EventView(event_id)

            try:
                message = await channel.send(embed=embed, view=view)
            except discord.Forbidden:
                await inter.response.send_message(
                    "❌ No tengo permisos para publicar en el canal de quedadas.", ephemeral=True
                )
                return
            except discord.HTTPException as e:
                logger.error(f"Error al publicar la quedada {event_id}: {e}")
                await inter.response.send_message("❌ No se pudo publicar la quedada.", ephemeral=True)
                return

            await self.db.set_message_id(event_id, message.id)
            await inter.response.send_message(f"✅ Quedada creada en {channel.mention}.", ephemeral=True)

        modal = EventFormModal(title="Crear quedada", on_submit_callback=on_submit)
        await interaction.response.send_modal(modal)

    # ---------------- /quedada editar ----------------

    @quedada_group.command(name="editar", description="Edita una quedada existente")
    @app_commands.describe(quedada="Quedada a editar")
    @app_commands.autocomplete(quedada=autocomplete_active)
    @require_event_manager()
    async def editar(self, interaction: discord.Interaction, quedada: int):
        event = await self.db.get_event(quedada)
        if not event or event["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("❌ No se encontró esa quedada.", ephemeral=True)
            return
        if event["status"] != "active":
            await interaction.response.send_message("❌ Solo se pueden editar quedadas activas.", ephemeral=True)
            return

        async def on_submit(inter: discord.Interaction, nombre, descripcion, fecha, hora):
            try:
                await self.db.update_event(
                    quedada, name=nombre, description=descripcion, event_date=fecha, event_time=hora
                )
            except Exception as e:
                logger.error(f"Error al actualizar la quedada {quedada}: {e}")
                await inter.response.send_message("❌ No se pudo actualizar la quedada.", ephemeral=True)
                return

            await inter.response.send_message("✅ Quedada actualizada.", ephemeral=True)
            await refresh_event_message(self.bot, quedada)

        modal = EventFormModal(title="Editar quedada", on_submit_callback=on_submit, defaults=event)
        await interaction.response.send_modal(modal)

    # ---------------- /quedada cancelar ----------------

    @quedada_group.command(name="cancelar", description="Cancela una quedada existente")
    @app_commands.describe(quedada="Quedada a cancelar")
    @app_commands.autocomplete(quedada=autocomplete_active_or_closed)
    @require_event_manager()
    async def cancelar(self, interaction: discord.Interaction, quedada: int):
        event = await self.db.get_event(quedada)
        if not event or event["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("❌ No se encontró esa quedada.", ephemeral=True)
            return
        if event["status"] == "cancelled":
            await interaction.response.send_message("❌ Esa quedada ya está cancelada.", ephemeral=True)
            return

        confirm_view = ConfirmCancelView(quedada)
        await interaction.response.send_message(
            f"¿Seguro que quieres cancelar **{event['name']}**? Esta acción no se puede deshacer.",
            view=confirm_view,
            ephemeral=True,
        )
        await confirm_view.wait()

        if confirm_view.confirmed:
            await self.db.set_event_status(quedada, "cancelled")
            await refresh_event_message(self.bot, quedada)

    # ---------------- /quedada cerrar ----------------

    @quedada_group.command(name="cerrar", description="Cierra la asistencia de una quedada")
    @app_commands.describe(quedada="Quedada a cerrar")
    @app_commands.autocomplete(quedada=autocomplete_active)
    @require_event_manager()
    async def cerrar(self, interaction: discord.Interaction, quedada: int):
        event = await self.db.get_event(quedada)
        if not event or event["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("❌ No se encontró esa quedada.", ephemeral=True)
            return
        if event["status"] != "active":
            await interaction.response.send_message("❌ Solo se pueden cerrar quedadas activas.", ephemeral=True)
            return

        await self.db.set_event_status(quedada, "closed")
        await refresh_event_message(self.bot, quedada)
        await interaction.response.send_message("🔒 Asistencia cerrada.", ephemeral=True)

    # ---------------- /quedada lista ----------------

    @quedada_group.command(name="lista", description="Muestra las próximas quedadas")
    async def lista(self, interaction: discord.Interaction):
        events = await self.db.list_events(interaction.guild_id, statuses=["active", "closed"], limit=10)
        if not events:
            await interaction.response.send_message("No hay quedadas próximas.", ephemeral=True)
            return

        lines = []
        for event in events:
            estado = "🔒" if event["status"] == "closed" else "🎮"
            lines.append(f"{estado} **{event['name']}**\n{event['event_date']} · {event['event_time']}")

        embed = discord.Embed(
            title="📅 Próximas quedadas",
            description="\n\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- /quedada info ----------------

    @quedada_group.command(name="info", description="Muestra los detalles de una quedada")
    @app_commands.describe(quedada="Quedada a consultar")
    @app_commands.autocomplete(quedada=autocomplete_any)
    async def info(self, interaction: discord.Interaction, quedada: int):
        event = await self.db.get_event(quedada)
        if not event or event["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("❌ No se encontró esa quedada.", ephemeral=True)
            return

        counts = await self.db.get_attendance_counts(quedada)
        total_members = await views_module.count_total_members(interaction.guild)
        creator = self.bot.get_user(event["creator_id"])
        creator_name = creator.display_name if creator else f"Usuario {event['creator_id']}"
        embed = build_event_embed(event, counts, total_members, creator_name)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- manejo de errores ----------------
    # cog_app_command_error es el hook que discord.py llama automáticamente
    # para cualquier error no controlado en los comandos de este Cog.

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            message = "❌ No tienes permiso para crear quedadas."
        else:
            logger.error(f"Error inesperado en un comando de quedada: {error}")
            message = "❌ Ocurrió un error inesperado. Inténtalo de nuevo más tarde."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(QuedadasCog(bot))
