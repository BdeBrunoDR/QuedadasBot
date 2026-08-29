"""
Punto de entrada del bot de quedadas.
"""
import asyncio
import logging

import discord
from discord.ext import commands

import config
from database import Database
from views import EventView

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("quedadas.bot")

# No se solicita ningún intent privilegiado (ni contenido de mensajes, ni
# miembros): el bot solo usa slash commands, modals y botones, y nunca lee
# el contenido de los mensajes que escriben los usuarios.
intents = discord.Intents.default()


class QuedadasBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database()

    async def setup_hook(self) -> None:
        await self.db.init()
        await self.load_extension("cogs.quedadas")

        # Vuelve a registrar las vistas persistentes de las quedadas activas/cerradas
        # para que los botones sigan funcionando después de reiniciar el bot.
        events = await self.db.list_events_for_startup()
        for event in events:
            disabled = event["status"] == "closed"
            self.add_view(EventView(event["id"], disabled=disabled))
        logger.info(f"Vistas persistentes registradas para {len(events)} quedada(s).")

        # Sincronización rápida en un único servidor (ideal durante el desarrollo).
        # Para pasar a comandos globales (todos los servidores), sustituye este
        # bloque por: await self.tree.sync()  -- ver README para más detalles.
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info(f"Sincronizados {len(synced)} comando(s) en el servidor {config.GUILD_ID}.")

    async def on_ready(self) -> None:
        logger.info(f"Sesión iniciada como {self.user} (ID: {self.user.id})")


async def main():
    bot = QuedadasBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot detenido manualmente.")
