"""
Configuración del bot, cargada desde variables de entorno (.env).

Nunca importar el token directamente en otros módulos salvo aquí: este es el
único punto donde se lee de disco, y bot.py es el único módulo que lo usa
para autenticarse contra la API de Discord.
"""
import os
import sys
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("quedadas.config")


def _get_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.critical(f"Falta la variable de entorno obligatoria: {name}. Revisa tu archivo .env.")
        sys.exit(1)
    return value


def _get_required_int(name: str) -> int:
    value = _get_required(name)
    try:
        return int(value)
    except ValueError:
        logger.critical(f"La variable de entorno {name} debe ser un número entero (valor actual: {value!r}).")
        sys.exit(1)


def _get_optional_int(name: str) -> Optional[int]:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        logger.critical(f"La variable de entorno {name} debe ser un número entero (valor actual: {value!r}).")
        sys.exit(1)


# Token del bot (obligatorio). Nunca se debe imprimir, loguear ni exponer.
DISCORD_TOKEN: str = _get_required("DISCORD_TOKEN")

# Servidor donde se sincronizan los comandos durante el desarrollo.
GUILD_ID: int = _get_required_int("GUILD_ID")

# Canal exclusivo donde se publican las quedadas.
EVENT_CHANNEL_ID: int = _get_required_int("EVENT_CHANNEL_ID")

# Rol autorizado a gestionar quedadas. Si es None, solo administradores.
EVENT_MANAGER_ROLE_ID: Optional[int] = _get_optional_int("EVENT_MANAGER_ROLE_ID")

# Zona horaria para interpretar y mostrar fechas/horas.
TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Madrid")

# Nivel de logging.
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
