import os, re, copy, time
import aiohttp
import discord
from discord.ext import commands

PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()   # anthropic ya gemini
KEY = os.getenv("AI_KEY", "")
MODEL = os.getenv("AI_MODEL") or ("gemini-2.0-flash" if PROVIDER == "gemini" else "claude-haiku-4-5-20251001")
NOPING = discord.AllowedMentions.none()
# Ye commands bina confirm ke chal jaate hain (sirf padhne wale). Baaki sab pe Confirm button aata hai.
SAFE = {"ping", "help", "userinfo", "serverinfo", "avatar", "banner", "membercount", "uptime", "botinfo", "servericon", "roleinfo", "about", "invite", "list"}
ACTION_RE = re.compile(r"^\s*ACTION:\s*(.+?)\s*$", re.M)


def split_actions(text):
    acts = [a.strip() for a in ACTION_RE.findall(text)][:3]
    return ACTION_RE.sub("", text).strip(), acts


def catalog(bot, limit=3000):
    parts = []
    for name, cog in sorted(bot.cogs.items()):
        names = []
        for c in cog.get_commands():
            if c.hidden:
                continue
            if isinstance(c, commands.Group) and c.commands:
                names.append(c.name + "(" + "/".join(s.name for s in c.commands) + ")")
            else:
                names.append(c.name)
        if names:
            parts.append(f"{name}: " + ", ".join(names))
    return "\n".join(parts)[:limit]


class Confirm(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=45)
        self.user, self.value = user, None

    async def interaction_check(self, i):
        if i.user.id != self.user.id:
            await i.response.send_message("Ye tumhare liye nahi hai.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Haan, chalao", style=discord.ButtonStyle.green)
    async def yes(self, i, b):
        self.value = True
        await i.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def no(self, i, b):
        self.value = False
        await i.response.defer()
        self.stop()


class AI(commands.Cog, name="AI"):
    """AI assistant: sawal poocho ya bot ke commands chalwao"""

    def __init__(self, bot):
        self.bot = bot
        self.hist = {}
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45))

    async def cog_unload(self):
        await self.session.close()

    # ---------- LLM ----------
    async def ask_llm(self, system, msgs):
        if not KEY:
            raise RuntimeError("AI_KEY set nahi hai (.env me AI_KEY daalo)")
        if PROVIDER == "gemini":
            body = {"systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user" if r == "user" else "model", "parts": [{"text": t}]} for r, t in msgs],
                    "generationConfig": {"maxOutputTokens": 700}}
            async with self.session.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent", params={"key": KEY}, json=body) as r:
                d = await r.json()
                if r.status != 200:
                    raise RuntimeError(f"AI error {r.status}: {str(d.get('error', {}).get('message', d))[:150]}")
            return d["candidates"][0]["content"]["parts"][0]["text"]
        body = {"model": MODEL, "max_tokens": 700, "system": system, "messages": [{"role": r, "content": t} for r, t in msgs]}
        async with self.session.post("https://api.anthropic.com/v1/messages", json=body,
                                     headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}) as r:
            d = await r.json()
            if r.status != 200:
                raise RuntimeError(f"AI error {r.status}: {str(d.get('error', {}).get('message', d))[:150]}")
        return "".join(b.get("text", "") for b in d["content"])

    def system_prompt(self, guild, author, prefix):
        return (f"You are the AI assistant built into the Discord bot 'Zenix Prime'. Reply in the user's language/style (Hinglish is fine). "
                f"Be friendly and short (under 1500 characters), no markdown headings.\n"
                f"Bot prefix: {prefix}\nBot commands by category:\n{catalog(self.bot)}\n\n"
                f"If the user wants you to DO something the bot can do, briefly explain and then add, at the very end, one line per action: "
                f"'ACTION: <command without prefix> <args>' (max 3 lines). Use only commands from the list above. Use mentions/IDs/names only if the user gave them; "
                f"never invent users, roles or channels - ask for missing details instead. Never use ACTION for the ai command. "
                f"The user will be asked to confirm risky actions, and normal permission checks apply.\n"
                f"Server: {guild.name if guild else 'DM'} | User: {author.display_name} | User is admin: {author.guild_permissions.administrator if guild else False}")

    def get_hist(self, key):
        h = self.hist.get(key)
        if not h or time.time() - h["t"] > 1800:
            if len(self.hist) > 500:
                self.hist.pop(next(iter(self.hist)))
            h = self.hist[key] = {"t": time.time(), "m": []}
        return h

    async def think(self, guild, chan_id, author, text):
        h = self.get_hist((chan_id, author.id))
        h["m"].append(("user", text[:1500]))
        h["m"] = h["m"][-10:]
        while h["m"] and h["m"][0][0] != "user":
            h["m"].pop(0)
        prefix = self.bot._pc.get(guild.id, os.getenv("PREFIX", "!")) if guild else os.getenv("PREFIX", "!")
        try:
            reply = await self.ask_llm(self.system_prompt(guild, author, prefix), h["m"])
        except Exception:
            h["m"].pop()
            raise
        h["m"].append(("assistant", reply))
        h["t"] = time.time()
        return split_actions(reply)

    # ---------- actions ----------
    def valid_actions(self, acts, prefix):
        out = []
        for a in acts:
            if a.startswith(prefix):
                a = a[len(prefix):].strip()
            if not a:
                continue
            c = self.bot.get_command(a.split()[0].lower())
            if c and c.cog_name != "AI":
                out.append(a)
        return out

    async def run_actions(self, origin, acts):
        prefix = (await self.bot.get_prefix(origin))
        prefix = prefix if isinstance(prefix, str) else prefix[-1]
        acts = self.valid_actions(acts, prefix)
        if not acts:
            return
        if any(a.split()[0].lower() not in SAFE for a in acts):
            view = Confirm(origin.author)
            m = await origin.channel.send("🤖 AI ye commands chalana chahta hai:\n" + "\n".join(f"`{prefix}{a}`" for a in acts) + "\nChalau?", view=view, allowed_mentions=NOPING)
            await view.wait()
            try:
                await m.edit(content=m.content + ("\n✅ Chal raha hai..." if view.value else "\n❌ Cancel / time out"), view=None)
            except discord.HTTPException:
                pass
            if not view.value:
                return
        for a in acts:
            fake = copy.copy(origin)
            fake.content = prefix + a
            ctx = await self.bot.get_context(fake)
            if ctx.valid:
                await self.bot.invoke(ctx)

    # ---------- entry points ----------
    @commands.hybrid_group(name="ai", fallback="ask", description="AI se kuch bhi poocho ya kaam karwao", aliases=["ask", "chat"], invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def ai(self, ctx, *, prompt: str):
        """AI se kuch bhi poocho. Bot ke commands bhi chalwa sakta hai (confirm ke baad)."""
        async with ctx.typing():
            try:
                text, acts = await self.think(ctx.guild, ctx.channel.id, ctx.author, prompt)
            except Exception as e:
                return await ctx.reply(f"⚠️ {e}", mention_author=False)
        await ctx.reply(text[:1900] or "🤔", mention_author=False, allowed_mentions=NOPING)
        if acts:
            if ctx.interaction is None:
                await self.run_actions(ctx.message, acts)
            else:
                await ctx.send("Commands chalane ke liye prefix se likho: " + " | ".join(f"`{a}`" for a in acts))

    @ai.command(name="reset", description="AI ki yaadash saaf karo")
    async def ai_reset(self, ctx):
        self.hist.pop((ctx.channel.id, ctx.author.id), None)
        await ctx.reply("🧹 AI ki yaadash saaf ho gayi.", mention_author=False)

    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author.bot or not msg.guild or not self.bot.user:
            return
        m = re.match(rf"^<@!?{self.bot.user.id}>\s*(.*)$", msg.content, re.S)
        if not m or not m.group(1).strip():
            return
        text = m.group(1).strip()
        if self.bot.get_command(text.split()[0].lower()):
            return  # ye normal command hai
        async with msg.channel.typing():
            try:
                reply, acts = await self.think(msg.guild, msg.channel.id, msg.author, text)
            except Exception as e:
                return await msg.reply(f"⚠️ {e}", mention_author=False)
        await msg.reply(reply[:1900] or "🤔", mention_author=False, allowed_mentions=NOPING)
        if acts:
            await self.run_actions(msg, acts)


async def setup(bot):
    await bot.add_cog(AI(bot))
