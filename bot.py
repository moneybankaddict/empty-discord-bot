from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from discord.ext import commands


COMMAND_PREFIX = "&"
CONFIG_FILE = Path("config.json")
BLACKLIST_FILE = Path("blacklist.txt")

DEFAULT_CONFIG: Dict[str, Any] = {
    "TOKEN": "YOUR_BOT_TOKEN_HERE",
    "GUILD_ID": 0,
    "CHANNEL_ID": 0,
    "ROLE_ID": 0,
    "LOG_CHANNEL_ID": 0,
    "STAFF_ROLE_ID": 0,
    "BRANDING": "empty",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("empty-bot")


@dataclass
class BotConfig:
    token: str
    guild_id: int
    verification_channel_id: int
    verified_role_id: int
    log_channel_id: int
    staff_role_id: int
    branding: str


def ensure_config_file() -> None:
    if CONFIG_FILE.exists():
        return

    CONFIG_FILE.write_text(
        json.dumps(DEFAULT_CONFIG, indent=4),
        encoding="utf-8",
    )
    raise SystemExit(
        f"{CONFIG_FILE} was created. Fill it with your Discord values before "
        "starting the bot."
    )


def _as_int(raw_config: Dict[str, Any], key: str) -> int:
    try:
        return int(raw_config[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid or missing config value: {key}") from exc


def load_config() -> BotConfig:
    ensure_config_file()

    with CONFIG_FILE.open("r", encoding="utf-8") as config_file:
        raw_config = {**DEFAULT_CONFIG, **json.load(config_file)}

    return BotConfig(
        token=str(raw_config["TOKEN"]).strip(),
        guild_id=_as_int(raw_config, "GUILD_ID"),
        verification_channel_id=_as_int(raw_config, "CHANNEL_ID"),
        verified_role_id=_as_int(raw_config, "ROLE_ID"),
        log_channel_id=_as_int(raw_config, "LOG_CHANNEL_ID"),
        staff_role_id=_as_int(raw_config, "STAFF_ROLE_ID"),
        branding=str(raw_config["BRANDING"]),
    )


def validate_config(bot_config: BotConfig) -> None:
    if not bot_config.token or bot_config.token == DEFAULT_CONFIG["TOKEN"]:
        raise ValueError("Set TOKEN in config.json before starting the bot.")


def reload_bot_config() -> None:
    global config

    new_config = load_config()
    validate_config(new_config)
    config = new_config


def build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.message_content = True
    return intents


try:
    config = load_config()
    validate_config(config)
except ValueError as error:
    raise SystemExit(str(error)) from error

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=build_intents(),
    help_command=None,
)


# ---------------------------------------------------------------------------
# Blacklist storage
# ---------------------------------------------------------------------------

def load_blacklist() -> List[int]:
    if not BLACKLIST_FILE.exists():
        return []

    blacklisted_users: List[int] = []
    seen_ids = set()

    with BLACKLIST_FILE.open("r", encoding="utf-8") as blacklist_file:
        for line in blacklist_file:
            line = line.strip()
            if not line:
                continue

            try:
                user_id = int(line)
            except ValueError:
                logger.warning("Ignored invalid blacklist entry: %s", line)
                continue

            if user_id not in seen_ids:
                blacklisted_users.append(user_id)
                seen_ids.add(user_id)

    return blacklisted_users


def save_blacklist(blacklisted_users: List[int]) -> None:
    content = "\n".join(str(user_id) for user_id in blacklisted_users)
    BLACKLIST_FILE.write_text(f"{content}\n" if content else "", encoding="utf-8")


blacklist_ids = load_blacklist()


# ---------------------------------------------------------------------------
# Discord helpers
# ---------------------------------------------------------------------------

async def send_log(title: str, description: str, color: discord.Color) -> None:
    channel = bot.get_channel(config.log_channel_id)
    if channel is None or not hasattr(channel, "send"):
        return

    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=config.branding)

    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        logger.exception("Failed to send log message")


async def send_dm(member: discord.Member, message: str) -> None:
    try:
        await member.send(message)
    except discord.HTTPException:
        logger.info("Could not DM user %s", member.id)


async def delete_message(message: Optional[discord.Message]) -> None:
    if message is None:
        return

    try:
        await message.delete()
    except discord.HTTPException:
        pass


async def delete_message_later(message: discord.Message, delay: float = 2.0) -> None:
    await asyncio.sleep(delay)
    await delete_message(message)


async def send_temporary_message(
    channel: Optional[discord.abc.Messageable],
    content: str,
    delay: float = 2.0,
) -> None:
    if channel is None or not hasattr(channel, "send"):
        return

    try:
        message = await channel.send(content)
    except discord.HTTPException:
        return

    await delete_message_later(message, delay)


async def require_admin(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    if permissions and permissions.administrator:
        return True

    await interaction.response.send_message("Admin only.", ephemeral=True)
    return False


async def global_ban(user_id: int, reason: str = "Global blacklist") -> int:
    try:
        user = await bot.fetch_user(user_id)
    except discord.HTTPException:
        logger.exception("Could not fetch user %s before ban", user_id)
        return 0

    successful_bans = 0
    for guild in bot.guilds:
        try:
            await guild.ban(user, reason=reason)
            successful_bans += 1
        except discord.HTTPException:
            logger.info("Could not ban user %s in guild %s", user_id, guild.id)

    return successful_bans


async def global_unban(user_id: int, reason: str = "Global unblacklist") -> int:
    try:
        user = await bot.fetch_user(user_id)
    except discord.HTTPException:
        logger.exception("Could not fetch user %s before unban", user_id)
        return 0

    successful_unbans = 0
    for guild in bot.guilds:
        try:
            await guild.unban(user, reason=reason)
            successful_unbans += 1
        except discord.HTTPException:
            logger.info("Could not unban user %s in guild %s", user_id, guild.id)

    return successful_unbans


async def sync_blacklist_members() -> int:
    total_bans = 0
    for user_id in blacklist_ids:
        total_bans += await global_ban(user_id)
    return total_bans


async def sync_unban_members() -> int:
    total_unbans = 0
    for user_id in blacklist_ids:
        total_unbans += await global_unban(user_id)
    return total_unbans


async def reset_blacklist() -> int:
    total_unbans = await sync_unban_members()
    blacklist_ids.clear()
    save_blacklist(blacklist_ids)
    return total_unbans


# ---------------------------------------------------------------------------
# Verification flow
# ---------------------------------------------------------------------------

class VerificationView(discord.ui.View):
    def __init__(self, member: Optional[discord.Member] = None):
        super().__init__(timeout=None)
        self.member = member

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.green)
    async def verify_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await require_admin(interaction):
            return

        if self.member is None:
            await interaction.response.send_message("Member not found.", ephemeral=True)
            return

        if interaction.guild is None:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return

        role = interaction.guild.get_role(config.verified_role_id)
        if role is None:
            await interaction.response.send_message(
                "Configured verification role was not found.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await self.member.add_roles(role, reason=f"Verified by {interaction.user}")
        except discord.HTTPException:
            await interaction.followup.send(
                "I could not add the configured role.",
                ephemeral=True,
            )
            return

        await send_dm(
            self.member,
            f"You have been verified on **{interaction.guild.name}** "
            f"and received the {role.name} role.",
        )
        await send_log(
            "User verified",
            f"{self.member.mention} was verified by {interaction.user.mention}.",
            discord.Color.green(),
        )

        await send_temporary_message(
            interaction.channel,
            f"{self.member.mention} verified and received {role.mention}.",
        )
        await delete_message(interaction.message)

    @discord.ui.button(label="Refuse", style=discord.ButtonStyle.red)
    async def refuse_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await require_admin(interaction):
            return

        if self.member is None:
            await interaction.response.send_message("Member not found.", ephemeral=True)
            return

        if interaction.guild is None:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        await send_dm(
            self.member,
            f"Your verification on **{interaction.guild.name}** was refused.",
        )
        await send_log(
            "User refused",
            f"{self.member.mention} was refused by {interaction.user.mention}.",
            discord.Color.red(),
        )

        await send_temporary_message(interaction.channel, f"{self.member.mention} was refused.")
        await delete_message(interaction.message)


@bot.event
async def on_ready() -> None:
    logger.info("Bot connected as %s", bot.user)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    if member.bot:
        return

    channel = bot.get_channel(config.verification_channel_id)
    if channel is None or not hasattr(channel, "send"):
        return

    embed = discord.Embed(
        title="New user waiting for verification",
        description=f"{member.mention} joined the server.\nUse the buttons below.",
        color=discord.Color.blue(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=config.branding)

    await channel.send(content="@everyone", embed=embed, view=VerificationView(member))


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

@bot.command()
@commands.has_permissions(administrator=True)
async def syncblacklist(ctx: commands.Context) -> None:
    total_bans = await sync_blacklist_members()
    await ctx.send(f"Blacklist synchronized. Successful bans: {total_bans}.")


@bot.command()
@commands.has_permissions(administrator=True)
async def syncunban(ctx: commands.Context) -> None:
    total_unbans = await sync_unban_members()
    await ctx.send(f"Blacklist unban synchronized. Successful unbans: {total_unbans}.")


@bot.command()
@commands.has_permissions(administrator=True)
async def syncreset(ctx: commands.Context) -> None:
    total_unbans = await reset_blacklist()
    await ctx.send(f"Blacklist reset. Successful unbans: {total_unbans}.")


@bot.command()
@commands.has_permissions(administrator=True)
async def reloadconfig(ctx: commands.Context) -> None:
    try:
        reload_bot_config()
    except (json.JSONDecodeError, ValueError) as error:
        await ctx.send(f"Config reload failed: {error}")
        return

    await ctx.send("Config reloaded.")


class NukeConfirmView(discord.ui.View):
    def __init__(self, ctx: commands.Context):
        super().__init__(timeout=30)
        self.ctx = ctx

    async def _is_author(self, interaction: discord.Interaction) -> bool:
        if interaction.user == self.ctx.author:
            return True

        await interaction.response.send_message(
            "Only the command author can use this confirmation.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self._is_author(interaction):
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(content="Nuking channel...", embed=None, view=None)

        old_channel = self.ctx.channel
        channel_position = old_channel.position
        new_channel = await old_channel.clone(reason=f"Nuke by {self.ctx.author}")
        await old_channel.delete(reason=f"Nuke by {self.ctx.author}")
        await new_channel.edit(position=channel_position)
        await new_channel.send("Channel nuked.")

        await send_log(
            "Channel nuked",
            f"{self.ctx.author.mention} nuked {new_channel.mention}.",
            discord.Color.red(),
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self._is_author(interaction):
            return

        await interaction.response.edit_message(content="Nuke cancelled.", view=None)


async def send_nuke_confirmation(ctx: commands.Context) -> None:
    embed = discord.Embed(
        title="Nuke confirmation",
        description=(
            "Are you sure you want to nuke this channel? "
            "This action deletes and recreates it."
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text=config.branding)
    await ctx.send(embed=embed, view=NukeConfirmView(ctx))


@bot.command()
@commands.has_permissions(administrator=True)
async def nuke(ctx: commands.Context) -> None:
    await send_nuke_confirmation(ctx)


# ---------------------------------------------------------------------------
# Staff panel
# ---------------------------------------------------------------------------

class StaffPanel(discord.ui.View):
    def __init__(self, ctx: commands.Context):
        super().__init__(timeout=180)
        self.ctx = ctx

    async def is_staff(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return False

        if interaction.user.guild_permissions.administrator:
            return True

        staff_role = interaction.guild.get_role(config.staff_role_id)
        if staff_role is not None and staff_role in interaction.user.roles:
            return True

        await interaction.response.send_message("Staff only.", ephemeral=True)
        return False

    @discord.ui.button(label="Sync Blacklist", style=discord.ButtonStyle.red)
    async def sync_blacklist_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self.is_staff(interaction):
            return

        await interaction.response.defer(ephemeral=True)
        total_bans = await sync_blacklist_members()
        await interaction.followup.send(
            f"Blacklist synchronized. Successful bans: {total_bans}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Sync Unban", style=discord.ButtonStyle.green)
    async def sync_unban_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self.is_staff(interaction):
            return

        await interaction.response.defer(ephemeral=True)
        total_unbans = await sync_unban_members()
        await interaction.followup.send(
            f"Blacklist unban synchronized. Successful unbans: {total_unbans}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Sync Reset", style=discord.ButtonStyle.gray)
    async def sync_reset_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self.is_staff(interaction):
            return

        await interaction.response.defer(ephemeral=True)
        total_unbans = await reset_blacklist()
        await interaction.followup.send(
            f"Blacklist reset. Successful unbans: {total_unbans}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Reload Config", style=discord.ButtonStyle.blurple)
    async def reload_config_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self.is_staff(interaction):
            return

        try:
            reload_bot_config()
        except (json.JSONDecodeError, ValueError) as error:
            await interaction.response.send_message(
                f"Config reload failed: {error}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Config reloaded.", ephemeral=True)

    @discord.ui.button(label="Nuke Channel", style=discord.ButtonStyle.danger)
    async def nuke_channel_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self.is_staff(interaction):
            return

        await send_nuke_confirmation(self.ctx)
        await interaction.response.send_message(
            "Nuke confirmation sent.",
            ephemeral=True,
        )

    @discord.ui.button(label="Shutdown Bot", style=discord.ButtonStyle.danger)
    async def shutdown_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self.is_staff(interaction):
            return

        await interaction.response.send_message("Bot shutting down...", ephemeral=True)
        await bot.close()


@bot.command()
@commands.has_permissions(administrator=True)
async def panel(ctx: commands.Context) -> None:
    embed = discord.Embed(
        title="Staff panel",
        description="Use the buttons below to manage the bot.",
        color=discord.Color.orange(),
    )
    embed.set_footer(text=config.branding)
    await ctx.send(embed=embed, view=StaffPanel(ctx))


# ---------------------------------------------------------------------------
# Help menu
# ---------------------------------------------------------------------------

class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Staff Panel",
                description="Interactive staff commands",
            ),
            discord.SelectOption(
                label="Blacklist",
                description="Global blacklist commands",
            ),
            discord.SelectOption(
                label="Utilities",
                description="Utility commands",
            ),
            discord.SelectOption(
                label="Info",
                description="General bot information",
            ),
        ]
        super().__init__(
            placeholder="Select a category",
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(color=discord.Color.purple())

        if self.values[0] == "Staff Panel":
            embed.title = "Staff Panel"
            embed.add_field(
                name=f"{COMMAND_PREFIX}panel",
                value="Open the interactive staff panel.",
                inline=False,
            )
        elif self.values[0] == "Blacklist":
            embed.title = "Blacklist"
            embed.add_field(
                name=f"{COMMAND_PREFIX}syncblacklist",
                value="Ban every blacklisted ID across all connected guilds.",
                inline=False,
            )
            embed.add_field(
                name=f"{COMMAND_PREFIX}syncunban",
                value="Unban every blacklisted ID across all connected guilds.",
                inline=False,
            )
            embed.add_field(
                name=f"{COMMAND_PREFIX}syncreset",
                value="Unban every blacklisted ID and clear the blacklist file.",
                inline=False,
            )
            embed.add_field(
                name=f"{COMMAND_PREFIX}bl add <user_id>",
                value="Add a user ID to the blacklist and ban it globally.",
                inline=False,
            )
            embed.add_field(
                name=f"{COMMAND_PREFIX}bl remove <user_id>",
                value="Remove a user ID from the blacklist and unban it globally.",
                inline=False,
            )
            embed.add_field(
                name=f"{COMMAND_PREFIX}bl list",
                value="List every blacklisted ID.",
                inline=False,
            )
        elif self.values[0] == "Utilities":
            embed.title = "Utilities"
            embed.add_field(
                name=f"{COMMAND_PREFIX}reloadconfig",
                value="Reload config.json without restarting the bot.",
                inline=False,
            )
            embed.add_field(
                name=f"{COMMAND_PREFIX}nuke",
                value="Delete and recreate the current channel after confirmation.",
                inline=False,
            )
        elif self.values[0] == "Info":
            embed.title = "Info"
            embed.add_field(
                name="Bot",
                value=f"Verification and global blacklist bot.\n{config.branding}",
                inline=False,
            )

        embed.set_footer(text=config.branding)
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpSelect())


@bot.command(aliases=["aide"])
async def help(ctx: commands.Context) -> None:
    embed = discord.Embed(
        title="Help menu",
        description="Use the dropdown below to browse commands.",
        color=discord.Color.purple(),
    )
    embed.set_footer(text=config.branding)
    await ctx.send(embed=embed, view=HelpView())


@bot.command()
@commands.has_permissions(administrator=True)
async def bl(
    ctx: commands.Context,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
) -> None:
    action = action.lower() if action else None

    if action not in {"add", "remove", "list"}:
        await ctx.send(f"Usage: {COMMAND_PREFIX}bl <add/remove/list> <user_id>")
        return

    if action == "list":
        if not blacklist_ids:
            await ctx.send("Blacklist is empty.")
            return

        ids = "\n".join(str(user_id) for user_id in blacklist_ids)
        await ctx.send(f"Blacklisted IDs:\n```text\n{ids}\n```")
        return

    if user_id is None:
        await ctx.send("Please provide a user ID.")
        return

    if action == "add":
        if user_id in blacklist_ids:
            await ctx.send("This ID is already blacklisted.")
            return

        blacklist_ids.append(user_id)
        save_blacklist(blacklist_ids)
        successful_bans = await global_ban(user_id)
        await ctx.send(
            f"ID {user_id} added to the blacklist. "
            f"Successful bans: {successful_bans}."
        )
        await send_log(
            "Blacklist add",
            f"{ctx.author.mention} added `{user_id}` to the blacklist.",
            discord.Color.green(),
        )
        return

    if user_id not in blacklist_ids:
        await ctx.send("This ID is not in the blacklist.")
        return

    blacklist_ids.remove(user_id)
    save_blacklist(blacklist_ids)
    successful_unbans = await global_unban(user_id)
    await ctx.send(
        f"ID {user_id} removed from the blacklist. "
        f"Successful unbans: {successful_unbans}."
    )
    await send_log(
        "Blacklist remove",
        f"{ctx.author.mention} removed `{user_id}` from the blacklist.",
        discord.Color.red(),
    )


@bot.event
async def on_command_error(
    ctx: commands.Context,
    error: commands.CommandError,
) -> None:
    error = getattr(error, "original", error)

    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument. Check the help menu for the right format.")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Missing argument. Check the help menu for the right format.")
        return

    logger.error(
        "Unhandled command error",
        exc_info=(type(error), error, error.__traceback__),
    )
    await ctx.send("An unexpected error occurred while running this command.")


if __name__ == "__main__":
    bot.run(config.token)
