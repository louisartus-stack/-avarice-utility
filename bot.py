import json
import os
import re
from typing import Optional

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

# ----------------------------
# Load config
# ----------------------------
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = os.getenv("DISCORD_TOKEN") or config.get("token")
TOP_IMAGE_URL = config.get("top_image_url", "")
BOTTOM_IMAGE_URL = config.get("bottom_image_url", "")
MAX_MEMBERS_PER_CUSTOM_ROLE = int(config.get("max_members_per_custom_role", 5))

if not TOKEN:
    raise ValueError("Missing bot token. Set DISCORD_TOKEN in Railway or token in config.json for local testing.")

# ----------------------------
# Intents
# ----------------------------
intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ----------------------------
# Storage
# ----------------------------
DATA_FILE = "role_data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def make_key(guild_id: int, user_id: int) -> str:
    return f"{guild_id}:{user_id}"

def get_user_role_id(guild_id: int, user_id: int) -> Optional[int]:
    data = load_data()
    role_id = data.get(make_key(guild_id, user_id))
    return int(role_id) if role_id is not None else None

def set_user_role_id(guild_id: int, user_id: int, role_id: int):
    data = load_data()
    data[make_key(guild_id, user_id)] = role_id
    save_data(data)

def remove_user_role_id(guild_id: int, user_id: int):
    data = load_data()
    key = make_key(guild_id, user_id)
    if key in data:
        del data[key]
        save_data(data)

# ----------------------------
# Helpers
# ----------------------------
def parse_hex_color(hex_string: str) -> discord.Color:
    hex_string = hex_string.strip().replace("#", "")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", hex_string):
        raise ValueError("Invalid hex color.")
    return discord.Color(int(hex_string, 16))

def user_is_booster(member: discord.Member) -> bool:
    return member.premium_since is not None

def get_owned_role(guild: discord.Guild, user_id: int) -> Optional[discord.Role]:
    role_id = get_user_role_id(guild.id, user_id)
    if role_id is None:
        return None
    return guild.get_role(role_id)

def guild_supports_role_icons(guild: discord.Guild) -> bool:
    return "ROLE_ICONS" in guild.features

def count_non_owner_members(role: discord.Role, owner_id: int) -> int:
    return sum(1 for m in role.members if m.id != owner_id)

async def fetch_image_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=20) as response:
            if response.status != 200:
                raise ValueError("Could not download image from URL.")
            content_type = response.headers.get("Content-Type", "").lower()
            if not any(x in content_type for x in ["image/png", "image/jpeg", "image/jpg", "image/webp"]):
                raise ValueError("Role icon URL must be a PNG, JPEG, or WEBP image.")
            return await response.read()

async def ensure_booster_interaction(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "This can only be used inside a server.",
            ephemeral=True
        )
        return False

    if not user_is_booster(interaction.user):
        await interaction.response.send_message(
            "Only active server boosters can use this panel.",
            ephemeral=True
        )
        return False

    return True

async def move_role_near_top(guild: discord.Guild, role: discord.Role):
    try:
        bot_member = guild.me
        if bot_member is None:
            return
        top_position = max(1, bot_member.top_role.position - 1)
        await role.edit(position=top_position, reason="Move custom booster role near top")
    except Exception as e:
        print(f"Failed to move role position: {e}")

def build_panel_embeds() -> list[discord.Embed]:
    embeds = []

    if TOP_IMAGE_URL:
        top_embed = discord.Embed(color=0x611232)
        top_embed.set_image(url=TOP_IMAGE_URL)
        embeds.append(top_embed)

    main_embed = discord.Embed(
        title="Manage a Custom Role",
        description=(
            "Want to create your own custom role on the server?\n\n"
            f"You may add up to **{MAX_MEMBERS_PER_CUSTOM_ROLE}** user(s) to your role.\n\n"
            "Use the buttons below to interact with the system."
        ),
        color=0x611232
    )

    if BOTTOM_IMAGE_URL:
        main_embed.set_image(url=BOTTOM_IMAGE_URL)

    embeds.append(main_embed)
    return embeds

def build_role_info_embed(member: discord.Member, role: discord.Role) -> discord.Embed:
    color_value = role.color.value if role.color.value != 0 else 0x611232
    member_count = count_non_owner_members(role, member.id)

    embed = discord.Embed(
        title="Your Custom Role",
        color=color_value
    )
    embed.add_field(name="Role Name", value=role.name, inline=False)
    embed.add_field(name="Role Mention", value=role.mention, inline=False)
    embed.add_field(name="Color", value=f"`#{role.color.value:06x}`", inline=False)
    embed.add_field(name="Added Members", value=f"{member_count}/{MAX_MEMBERS_PER_CUSTOM_ROLE}", inline=False)
    embed.add_field(name="Role Icon", value="Set" if role.display_icon else "Not set", inline=False)
    embed.set_footer(text=f"Owner: {member.display_name}")
    return embed

# ----------------------------
# Modals
# ----------------------------
class CreateRoleModal(discord.ui.Modal, title="Create Custom Role"):
    role_name = discord.ui.TextInput(
        label="Role Name",
        placeholder="Enter your custom role name",
        max_length=100
    )
    role_color = discord.ui.TextInput(
        label="Role Color (Hex)",
        placeholder="#611232",
        required=False,
        max_length=7
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user

        existing_role = get_owned_role(guild, member.id)
        if existing_role is not None:
            await interaction.response.send_message(
                f"You already have a custom role: {existing_role.mention}",
                ephemeral=True
            )
            return

        role = await guild.create_role(
            name=str(self.role_name).strip(),
            reason=f"Custom booster role created for {member}"
        )

        await move_role_near_top(guild, role)

        color_text = str(self.role_color).strip()
        if color_text:
            try:
                color = parse_hex_color(color_text)
                await role.edit(color=color, reason=f"Color set by {member}")
            except ValueError:
                await role.delete(reason="Invalid color supplied during role creation")
                await interaction.response.send_message(
                    "Invalid hex color. Use something like `#611232`.",
                    ephemeral=True
                )
                return

        await member.add_roles(role, reason="Assigning newly created custom booster role")
        set_user_role_id(guild.id, member.id, role.id)

        await interaction.response.send_message(
            f"Created your custom role {role.mention}.",
            ephemeral=True
        )

class EditRoleModal(discord.ui.Modal, title="Edit Custom Role"):
    role_name = discord.ui.TextInput(
        label="New Role Name",
        placeholder="Enter a new role name",
        required=False,
        max_length=100
    )
    role_color = discord.ui.TextInput(
        label="New Role Color (Hex)",
        placeholder="#611232",
        required=False,
        max_length=7
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role yet.",
                ephemeral=True
            )
            return

        new_name = str(self.role_name).strip()
        color_text = str(self.role_color).strip()

        kwargs = {}
        if new_name:
            kwargs["name"] = new_name

        if color_text:
            try:
                kwargs["color"] = parse_hex_color(color_text)
            except ValueError:
                await interaction.response.send_message(
                    "Invalid hex color. Use something like `#611232`.",
                    ephemeral=True
                )
                return

        if not kwargs:
            await interaction.response.send_message(
                "No changes were provided.",
                ephemeral=True
            )
            return

        await role.edit(reason=f"Custom role edited by {member}", **kwargs)
        await move_role_near_top(guild, role)

        await interaction.response.send_message(
            f"Updated your custom role {role.mention}.",
            ephemeral=True
        )

class RoleIconModal(discord.ui.Modal, title="Set Role Icon"):
    emoji_icon = discord.ui.TextInput(
        label="Unicode Emoji Icon",
        placeholder="Example: 🔥",
        required=False,
        max_length=10
    )
    image_url = discord.ui.TextInput(
        label="Image URL (PNG/JPEG/WEBP)",
        placeholder="https://example.com/icon.png",
        required=False,
        max_length=300
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role yet.",
                ephemeral=True
            )
            return

        if not guild_supports_role_icons(guild):
            await interaction.response.send_message(
                "This server does not have role icons enabled.",
                ephemeral=True
            )
            return

        emoji_value = str(self.emoji_icon).strip()
        url_value = str(self.image_url).strip()

        if emoji_value and url_value:
            await interaction.response.send_message(
                "Use either a Unicode emoji or an image URL, not both.",
                ephemeral=True
            )
            return

        if not emoji_value and not url_value:
            await interaction.response.send_message(
                "You must provide either a Unicode emoji or an image URL.",
                ephemeral=True
            )
            return

        try:
            if emoji_value:
                await role.edit(display_icon=emoji_value, reason=f"Role icon updated by {member}")
            else:
                image_bytes = await fetch_image_bytes(url_value)
                await role.edit(display_icon=image_bytes, reason=f"Role icon updated by {member}")
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected that role icon. Try a smaller PNG/JPEG/WEBP or a simple Unicode emoji.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Updated the icon for {role.mention}.",
            ephemeral=True
        )

# ----------------------------
# Select Menus
# ----------------------------
class AddUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="Choose a user to add to your role",
            min_values=1,
            max_values=1,
            custom_id="add_user_select"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role yet.",
                ephemeral=True
            )
            return

        selected_user = self.values[0]

        if selected_user.bot:
            await interaction.response.send_message(
                "You cannot add a bot to your role.",
                ephemeral=True
            )
            return

        if selected_user.id == member.id:
            await interaction.response.send_message(
                "You already have your own role.",
                ephemeral=True
            )
            return

        current_added = count_non_owner_members(role, member.id)
        if current_added >= MAX_MEMBERS_PER_CUSTOM_ROLE:
            await interaction.response.send_message(
                f"You have reached your limit of {MAX_MEMBERS_PER_CUSTOM_ROLE} added member(s).",
                ephemeral=True
            )
            return

        if role in selected_user.roles:
            await interaction.response.send_message(
                f"{selected_user.mention} already has your role.",
                ephemeral=True
            )
            return

        await selected_user.add_roles(role, reason=f"Added to custom role by {member}")
        new_count = count_non_owner_members(role, member.id)

        await interaction.response.send_message(
            f"Added {selected_user.mention} to {role.mention}. Usage: {new_count}/{MAX_MEMBERS_PER_CUSTOM_ROLE}.",
            ephemeral=True
        )

class AddUserView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(AddUserSelect())

class RemoveUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="Choose a user to remove from your role",
            min_values=1,
            max_values=1,
            custom_id="remove_user_select"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role yet.",
                ephemeral=True
            )
            return

        selected_user = self.values[0]

        if role not in selected_user.roles:
            await interaction.response.send_message(
                f"{selected_user.mention} does not have your role.",
                ephemeral=True
            )
            return

        if selected_user.id == member.id:
            await interaction.response.send_message(
                "Use the **Remove Me** button if you want to remove your role from yourself.",
                ephemeral=True
            )
            return

        await selected_user.remove_roles(role, reason=f"Removed from custom role by {member}")
        new_count = count_non_owner_members(role, member.id)

        await interaction.response.send_message(
            f"Removed {selected_user.mention} from {role.mention}. Usage: {new_count}/{MAX_MEMBERS_PER_CUSTOM_ROLE}.",
            ephemeral=True
        )

class RemoveUserView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(RemoveUserSelect())

# ----------------------------
# Persistent Button Panel
# ----------------------------
class RolePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Role", style=discord.ButtonStyle.primary, custom_id="y1", row=0)
    async def create_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return
        await interaction.response.send_modal(CreateRoleModal())

    @discord.ui.button(label="Edit Role", style=discord.ButtonStyle.secondary, custom_id="y2", row=0)
    async def edit_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return
        await interaction.response.send_modal(EditRoleModal())

    @discord.ui.button(label="View Role", style=discord.ButtonStyle.secondary, custom_id="y3", row=0)
    async def view_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role yet.",
                ephemeral=True
            )
            return

        embed = build_role_info_embed(member, role)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Add User", style=discord.ButtonStyle.success, custom_id="g1", row=0)
    async def add_user_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role yet.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Select a user to add to your custom role. Limit: {MAX_MEMBERS_PER_CUSTOM_ROLE}.",
            view=AddUserView(),
            ephemeral=True
        )

    @discord.ui.button(label="Remove User", style=discord.ButtonStyle.danger, custom_id="b3", row=1)
    async def remove_user_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role yet.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Select a user to remove from your custom role:",
            view=RemoveUserView(),
            ephemeral=True
        )

    @discord.ui.button(label="Set Icon", style=discord.ButtonStyle.primary, custom_id="set_icon", row=1)
    async def set_icon_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return
        await interaction.response.send_modal(RoleIconModal())

    @discord.ui.button(label="Remove Me", style=discord.ButtonStyle.secondary, custom_id="remove_me", row=1)
    async def remove_me_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role yet.",
                ephemeral=True
            )
            return

        if role not in member.roles:
            await interaction.response.send_message(
                "You do not currently have your custom role assigned to yourself.",
                ephemeral=True
            )
            return

        await member.remove_roles(role, reason=f"Owner removed own custom role assignment: {member}")
        await interaction.response.send_message(
            f"Removed {role.mention} from yourself. Your role still exists.",
            ephemeral=True
        )

    @discord.ui.button(label="Delete Role", style=discord.ButtonStyle.danger, custom_id="delete_role", row=1)
    async def delete_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return

        guild = interaction.guild
        member = interaction.user
        role = get_owned_role(guild, member.id)

        if role is None:
            await interaction.response.send_message(
                "You do not have a custom role to delete.",
                ephemeral=True
            )
            return

        role_name = role.name
        await role.delete(reason=f"Deleted by owner {member}")
        remove_user_role_id(guild.id, member.id)

        await interaction.response.send_message(
            f"Deleted your custom role **{role_name}**.",
            ephemeral=True
        )

# ----------------------------
# Ready Event
# ----------------------------
@bot.event
async def on_ready():
    try:
        synced = await tree.sync()
        print(f"Globally synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    bot.add_view(RolePanelView())
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# ----------------------------
# Global Slash Commands
# ----------------------------
@tree.command(name="setup_customroles_panel", description="Post the custom roles panel in this server")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_customroles_panel(interaction: discord.Interaction):
    await interaction.channel.send(
        embeds=build_panel_embeds(),
        view=RolePanelView()
    )
    await interaction.response.send_message("Custom roles panel posted.", ephemeral=True)

@tree.command(name="repost_customroles_panel", description="Repost the custom roles panel in this server")
@app_commands.checks.has_permissions(manage_guild=True)
async def repost_customroles_panel(interaction: discord.Interaction):
    await interaction.channel.send(
        embeds=build_panel_embeds(),
        view=RolePanelView()
    )
    await interaction.response.send_message("Custom roles panel reposted.", ephemeral=True)

@tree.command(name="delete_my_custom_role", description="Delete your custom role")
async def delete_my_custom_role(interaction: discord.Interaction):
    if not await ensure_booster_interaction(interaction):
        return

    guild = interaction.guild
    member = interaction.user
    role = get_owned_role(guild, member.id)

    if role is None:
        await interaction.response.send_message("You do not have a custom role to delete.", ephemeral=True)
        return

    role_name = role.name
    await role.delete(reason=f"Deleted by owner {member}")
    remove_user_role_id(guild.id, member.id)

    await interaction.response.send_message(
        f"Deleted your custom role **{role_name}**.",
        ephemeral=True
    )

@tree.command(name="set_my_role_icon_upload", description="Upload an image file to use as your role icon")
@app_commands.describe(icon_file="PNG, JPEG, or WEBP image file")
async def set_my_role_icon_upload(interaction: discord.Interaction, icon_file: discord.Attachment):
    if not await ensure_booster_interaction(interaction):
        return

    guild = interaction.guild
    member = interaction.user
    role = get_owned_role(guild, member.id)

    if role is None:
        await interaction.response.send_message(
            "You do not have a custom role yet.",
            ephemeral=True
        )
        return

    if not guild_supports_role_icons(guild):
        await interaction.response.send_message(
            "This server does not have role icons enabled.",
            ephemeral=True
        )
        return

    content_type = (icon_file.content_type or "").lower()
    if not any(x in content_type for x in ["image/png", "image/jpeg", "image/jpg", "image/webp"]):
        await interaction.response.send_message(
            "Upload a PNG, JPEG, or WEBP image.",
            ephemeral=True
        )
        return

    try:
        image_bytes = await icon_file.read()
        await role.edit(display_icon=image_bytes, reason=f"Role icon uploaded by {member}")
    except discord.HTTPException:
        await interaction.response.send_message(
            "Discord rejected that uploaded image. Try a smaller PNG/JPEG/WEBP file.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"Uploaded a new icon for {role.mention}.",
        ephemeral=True
    )

# ----------------------------
# Auto-delete if boost is removed
# ----------------------------
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    before_boosting = user_is_booster(before)
    after_boosting = user_is_booster(after)

    if before_boosting and not after_boosting:
        role = get_owned_role(after.guild, after.id)
        if role is not None:
            try:
                await role.delete(reason=f"{after} stopped boosting")
            except discord.Forbidden:
                print(f"Could not delete role for {after}; check role hierarchy.")
            except discord.HTTPException as e:
                print(f"Failed to delete role for {after}: {e}")
            finally:
                remove_user_role_id(after.guild.id, after.id)

# ----------------------------
# Error Handling
# ----------------------------
@setup_customroles_panel.error
async def setup_panel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "You need `Manage Server` permission to post this panel.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "There was an error posting the panel.",
            ephemeral=True
        )

@repost_customroles_panel.error
async def repost_panel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "You need `Manage Server` permission to repost this panel.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "There was an error reposting the panel.",
            ephemeral=True
        )

bot.run(TOKEN)
