# Bot de Discord para gestionar quedadas

Bot completo en `discord.py` para crear y gestionar quedadas/eventos en un
servidor privado, con formularios nativos de Discord, sistema de asistencia
por botones y persistencia en SQLite.

## Estructura del proyecto

```
discord-quedadas/
├── bot.py              # Punto de entrada
├── config.py           # Carga y valida las variables de entorno
├── database.py         # Acceso a datos (SQLite / aiosqlite)
├── embeds.py            # Construcción de los Embeds públicos
├── views.py             # Modals y botones (vista persistente)
├── requirements.txt
├── .env.example
├── .gitignore
├── cogs/
│   └── quedadas.py      # Todos los slash commands /quedada
└── data/
    └── quedadas.db       # Se crea automáticamente al arrancar
```

## 1. Crear la aplicación de Discord

1. Ve a https://discord.com/developers/applications y pulsa **New Application**.
2. En la pestaña **Bot**, pulsa **Reset Token** y copia el token (lo necesitarás en el `.env`). **No lo compartas ni lo subas a git.**
3. En **Privileged Gateway Intents** no necesitas activar nada: este bot no
   solicita el intent de contenido de mensajes ni el de miembros, porque solo
   usa slash commands, modals y botones (nunca lee mensajes de texto normales).
4. En **OAuth2 → URL Generator**:
   - Scopes: `bot` y `applications.commands`.
   - Permisos del bot (mínimos necesarios, sin Administrador):
     - View Channels
     - Send Messages
     - Embed Links
     - Read Message History
     - Use Application Commands
   - Copia la URL generada, ábrela en el navegador e invita el bot a tu servidor.

## 2. Obtener los IDs necesarios

1. Activa el modo desarrollador: Ajustes de usuario → Avanzado → Modo desarrollador.
2. **GUILD_ID**: clic derecho sobre el icono del servidor → *Copiar ID*.
3. **EVENT_CHANNEL_ID**: crea un canal de texto (por ejemplo `#📅・quedadas`), clic derecho → *Copiar ID*.
4. **EVENT_MANAGER_ROLE_ID** (opcional): clic derecho sobre el rol en Ajustes del servidor → Roles → *Copiar ID*. Si lo dejas vacío, solo los administradores del servidor podrán gestionar quedadas.

## 3. Configurar el canal de quedadas

Para que los usuarios normales puedan ver el canal y pulsar los botones pero
**no** puedan escribir:

1. Ve a la configuración del canal `#quedadas` → **Permisos**.
2. Para el rol `@everyone`:
   - ✅ Ver canal
   - ✅ Leer historial de mensajes
   - ❌ Enviar mensajes (desactívalo explícitamente)
3. Para el rol del bot (o dale permisos individuales al bot en ese canal):
   - ✅ Ver canal, Enviar mensajes, Insertar enlaces, Leer historial de mensajes

Esto impide que los usuarios escriban directamente por permisos de Discord,
sin que el bot tenga que borrar mensajes.

## 4. Instalación

```bash
python -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

Copia la plantilla de configuración y rellénala:

```bash
cp .env.example .env
```

Edita `.env` con tu editor favorito y rellena `DISCORD_TOKEN`, `GUILD_ID`,
`EVENT_CHANNEL_ID` y, si quieres, `EVENT_MANAGER_ROLE_ID`.

Arranca el bot:

```bash
python bot.py
```

Si todo va bien verás en la consola algo como:

```
[INFO] quedadas.database: Base de datos inicializada en .../data/quedadas.db
[INFO] quedadas.bot: Vistas persistentes registradas para 0 quedada(s).
[INFO] quedadas.bot: Sincronizados 1 comando(s) en el servidor <GUILD_ID>.
[INFO] quedadas.bot: Sesión iniciada como TuBot#1234 (ID: ...)
```

Los comandos `/quedada crear`, `/quedada editar`, etc. deberían aparecer casi
al instante en el servidor configurado (sincronización por servidor, ver
sección 8 más abajo).

## 5. Uso

- `/quedada crear` → abre un formulario (nombre, fecha, hora, descripción) y
  publica la quedada en el canal configurado con botones de asistencia.
- Los usuarios pulsan **🟢 Asistiré** / **🔴 No asistiré** para registrar su
  respuesta (efímera para ellos, el Embed público se actualiza solo).
- **👥 Ver asistentes** y **📋 Ver respuestas** muestran el detalle, siempre
  de forma efímera.
- `/quedada editar`, `/quedada cancelar`, `/quedada cerrar` usan
  autocompletado: empieza a escribir el nombre de la quedada y Discord te
  sugerirá las opciones, sin que tengas que copiar IDs a mano.
- `/quedada lista` y `/quedada info` son de consulta, disponibles para
  cualquier usuario.

## 6. Persistencia y reinicios

Todas las quedadas y respuestas se guardan en `data/quedadas.db` (SQLite).
Al arrancar, `bot.py` vuelve a registrar una vista con los `custom_id`
correctos para cada quedada activa o cerrada, así que los botones de
mensajes ya publicados siguen funcionando después de reiniciar el bot sin
perder ni una sola respuesta.

## 7. Limitación conocida: contador "sin responder"

Discord no permite consultar de forma sencilla cuántas personas pueden ver
un canal concreto sin activar el intent privilegiado de miembros (que este
proyecto evita a propósito, para mantener la configuración simple y no
depender de aprobación adicional de Discord si el bot crece a >100
servidores). Como alternativa, el conteo **⚪ sin responder** se aproxima
usando el número total de miembros del servidor (descontando bots). Si tu
canal de quedadas está restringido a un rol concreto más pequeño que todo el
servidor, ese número será una sobreestimación — trátalo como una cifra
orientativa, no exacta. Los conteos de 🟢 y 🔴 sí son exactos siempre, porque
vienen directamente de la tabla `attendance`.

## 8. Pasar de comandos por servidor a comandos globales

Por defecto, `bot.py` sincroniza los comandos solo en `GUILD_ID` (aparecen
en segundos, ideal en desarrollo). Si más adelante quieres usar el bot en
varios servidores, en `bot.py`, dentro de `setup_hook`, sustituye:

```python
guild = discord.Object(id=config.GUILD_ID)
self.tree.copy_global_to(guild=guild)
synced = await self.tree.sync(guild=guild)
```

por:

```python
synced = await self.tree.sync()
```

Ten en cuenta que la sincronización global puede tardar hasta una hora en
propagarse por todos los servidores (limitación de la API de Discord, no del
código).

## 9. Seguridad

- El token nunca se imprime, se loguea ni se expone en ningún mensaje del bot.
- `.env` está en `.gitignore`; usa `.env.example` como plantilla para
  compartir la configuración sin exponer secretos.
- Si alguna vez el token se filtra, revócalo desde el Developer Portal
  (**Bot → Reset Token**) inmediatamente.
