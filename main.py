import os, json, time, pathlib, traceback
import discord
import aiosqlite
from discord.ext import commands

# .env file support (Pterodactyl / VPS)
if os.path.exists(".env"):
    for _l in open(".env", encoding="utf-8"):
        if "=" in _l and not _l.lstrip().startswith("#"):
            _k, _v = _l.strip().split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

DEFAULT_PREFIX = os.getenv("PREFIX", "!")
OWNERS = {int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.isdigit()}
ALLOWED = {x.strip() for x in os.getenv("ALLOWED_GUILDS", "").split(",") if x.strip()}


class ZenixBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix=self._prefix, intents=intents, help_command=None, case_insensitive=True,
                         strip_after_prefix=True, owner_ids=OWNERS or None,
                         allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False))
        self.start_time = time.time()
        self.db = None
        self.color = 0x7C5CFF
        self._pc = {}

    # ---------- per-server settings (key/value, JSON) ----------
    async def gget(self, gid, key, default=None):
        async with self.db.execute("SELECT value FROM kv WHERE guild=? AND key=?", (gid, key)) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else default

    async def gset(self, gid, key, value):
        await self.db.execute("INSERT OR REPLACE INTO kv(guild,key,value) VALUES(?,?,?)", (gid, key, json.dumps(value)))
        await self.db.commit()

    async def _prefix(self, bot, message):
        base = DEFAULT_PREFIX
        if message.guild:
            gid = message.guild.id
            if gid not in self._pc:
                self._pc[gid] = await self.gget(gid, "prefix", DEFAULT_PREFIX)
            base = self._pc[gid]
        return commands.when_mentioned_or(base)(self, message)

    async def setup_hook(self):
        self.db = await aiosqlite.connect("zenix.db")
        await self.db.execute("CREATE TABLE IF NOT EXISTS kv(guild INTEGER, key TEXT, value TEXT, PRIMARY KEY(guild,key))")
        await self.db.commit()
        for f in sorted(pathlib.Path("cogs").glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                await self.load_extension(f"cogs.{f.stem}")
                print("✅ cog loaded:", f.stem)
            except Exception:
                print("❌ cog load fail:", f.stem)
                traceback.print_exc()
        try:
            await self.tree.sync()
        except Exception as e:
            print("⚠️ slash sync error:", e)

    async def on_ready(self):
        for g in list(self.guilds):
            if ALLOWED and str(g.id) not in ALLOWED:
                await g.leave()
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=f"{DEFAULT_PREFIX}help | @mention AI"))
        print(f"✅ {self.user} online hai! Servers: {len(self.guilds)} | Cogs: {len(self.cogs)}")

    async def on_guild_join(self, g):
        if ALLOWED and str(g.id) not in ALLOWED:
            await g.leave()

    async def on_command_error(self, ctx, err):
        err = getattr(err, "original", err)
        if isinstance(err, commands.CommandNotFound):
            return
        usage = f"`{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}`" if ctx.command else ""
        if isinstance(err, commands.MissingPermissions):
            msg = "❌ Tumhare paas permission nahi hai: " + ", ".join(p.replace("_", " ").title() for p in err.missing_permissions)
        elif isinstance(err, commands.BotMissingPermissions):
            msg = "❌ Mere paas permission nahi hai: " + ", ".join(p.replace("_", " ").title() for p in err.missing_permissions)
        elif isinstance(err, commands.MissingRequiredArgument):
            msg = f"⚠️ Argument kam hai: `{err.param.name}`\nUsage: {usage}"
        elif isinstance(err, (commands.BadArgument, commands.BadUnionArgument)):
            msg = f"⚠️ Galat value di hai.\nUsage: {usage}"
        elif isinstance(err, commands.CommandOnCooldown):
            msg = f"⏳ {err.retry_after:.1f} second baad try karo."
        elif isinstance(err, commands.NoPrivateMessage):
            msg = "❌ Ye command sirf server me chalta hai."
        elif isinstance(err, commands.CheckFailure):
            msg = "🔒 Ye command tum nahi chala sakte."
        elif isinstance(err, discord.Forbidden):
            msg = "❌ Discord ne mana kar diya. Mera role us member/role se upar hona chahiye."
        else:
            traceback.print_exception(type(err), err, err.__traceback__)
            msg = f"⚠️ Error: {str(err)[:150]}"
        try:
            await ctx.reply(msg, mention_author=False)
        except discord.HTTPException:
            pass


if __name__ == "__main__":
    token = os.getenv("TOKEN")
    if not token:
        raise SystemExit("❌ .env me TOKEN nahi mila")
    ZenixBot().run(token)
