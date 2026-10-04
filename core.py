import discord
from discord.ext import commands


def walk(cmds):
    for c in cmds:
        yield c
        if isinstance(c, commands.Group):
            yield from walk(c.commands)


def cog_cmds(cog):
    return [c for c in walk(cog.get_commands()) if not c.hidden]


def first_line(cog):
    return (cog.description or "").split("\n")[0]


def _cut(txt, lim=3900):
    if len(txt) <= lim:
        return txt
    c = txt[:lim]
    i = max(c.rfind("` "), c.rfind("\n"))
    return c[:i + 1] + "\n…aur bhi"


def home_embed(bot, prefix):
    cogs = [(n, c) for n, c in sorted(bot.cogs.items()) if cog_cmds(c)]
    total = sum(len(cog_cmds(c)) for _, c in cogs)
    lines = "\n".join(f"**{n}** ({len(cog_cmds(c))}) — {first_line(c)}" for n, c in cogs)
    return discord.Embed(title="✦ Zenix Prime", color=bot.color,
                         description=f"Prefix: `{prefix}` • Total **{total}** commands\nAI se baat: bot ko mention karo ya `{prefix}ai <sawal>`\nNeeche se category chuno 👇\n\n{lines}"[:4000])


def cog_embed(bot, name):
    cog = bot.get_cog(name)
    cmds = cog_cmds(cog)
    txt = " ".join(f"`{c.qualified_name}`" for c in cmds)
    return discord.Embed(title=f"{name} ({len(cmds)})", color=bot.color, description=_cut(f"{first_line(cog)}\n\n{txt}"))


class HelpView(discord.ui.View):
    def __init__(self, bot, author_id, prefix):
        super().__init__(timeout=180)
        self.bot, self.author_id, self.prefix = bot, author_id, prefix
        opts = [discord.SelectOption(label=n[:100], value=n, description=(first_line(c)[:100] or None))
                for n, c in sorted(bot.cogs.items()) if cog_cmds(c)][:24]
        opts.insert(0, discord.SelectOption(label="🏠 Home", value="__home"))
        sel = discord.ui.Select(placeholder="Category chuno...", options=opts)
        sel.callback = self.pick
        self.add_item(sel)

    async def interaction_check(self, i):
        if i.user.id != self.author_id:
            await i.response.send_message("Apna /help khud kholo 🙂", ephemeral=True)
            return False
        return True

    async def pick(self, i):
        v = i.data["values"][0]
        e = home_embed(self.bot, self.prefix) if v == "__home" else cog_embed(self.bot, v)
        await i.response.edit_message(embed=e, view=self)


class Core(commands.Cog, name="Core"):
    """Basic commands: help, ping, prefix"""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="ping", description="Bot ki speed")
    async def ping(self, ctx):
        await ctx.reply(f"🏓 Pong! **{round(self.bot.latency * 1000)}ms**", mention_author=False)

    @commands.hybrid_command(name="help", description="Saari commands ki list ya ek command ki help")
    async def help_cmd(self, ctx, *, command: str = None):
        prefix = ctx.clean_prefix
        if command:
            c = self.bot.get_command(command.strip().lower())
            if not c:
                return await ctx.reply("❌ Aisa command nahi mila.", mention_author=False)
            e = discord.Embed(title=f"{prefix}{c.qualified_name}", color=self.bot.color, description=c.help or c.description or "-")
            e.add_field(name="Usage", value=f"`{prefix}{c.qualified_name} {c.signature}`", inline=False)
            if c.aliases:
                e.add_field(name="Aliases", value=", ".join(c.aliases))
            e.add_field(name="Category", value=c.cog_name or "-")
            return await ctx.reply(embed=e, mention_author=False)
        await ctx.reply(embed=home_embed(self.bot, prefix), view=HelpView(self.bot, ctx.author.id, prefix), mention_author=False)

    @commands.hybrid_group(name="prefix", fallback="show", description="Bot ka prefix dekho ya badlo", invoke_without_command=True)
    @commands.guild_only()
    async def prefix(self, ctx):
        await ctx.reply(f"Is server ka prefix: `{ctx.clean_prefix}`", mention_author=False)

    @prefix.command(name="set", description="Naya prefix set karo")
    @commands.has_permissions(manage_guild=True)
    async def prefix_set(self, ctx, new: str):
        if len(new) > 5 or " " in new:
            return await ctx.reply("❌ Prefix max 5 akshar ka ho, space nahi.", mention_author=False)
        await self.bot.gset(ctx.guild.id, "prefix", new)
        self.bot._pc[ctx.guild.id] = new
        await ctx.reply(f"✅ Prefix ab `{new}` hai.", mention_author=False)


async def setup(bot):
    await bot.add_cog(Core(bot))
