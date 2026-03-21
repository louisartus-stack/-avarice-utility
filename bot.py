import json
import os
import re
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

# ----------------------------
# Load config
# ----------------------------
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = os.getenv("DISCORD_TOKEN")
BOOSTER_ROLE_NAME = config["booster_role_name"]
GUILD_ID = config["guild_id"]

# Optional panel image URLs
TOP_IMAGE_URL = config.get("top_image_url", "")
BOTTOM_IMAGE_URL = config.get("bottom_image_url", "")

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

def get_user_role_id(user_id: int) -> Optional[int]:
    data = load_data()
    role_id = data.get(str(user_id))
    return int(role_id) if role_id is not None else None

def set_user_role_id(user_id: int, role_id: int):
    data = load_data()
    data[str(user_id)] = role_id
    save_data(data)

def remove_user_role_id(user_id: int):
    data = load_data()
    if str(user_id) in data:
        del data[str(user_id)]
        save_data(data)

# ----------------------------
# Helpers
# ----------------------------
def parse_hex_color(hex_string: str) -> discord.Color:
    hex_string = hex_string.strip().replace("#", "")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", hex_string):
        raise ValueError("Invalid hex color.")
    return discord.Color(int(hex_string, 16))

def get_booster_role(guild: discord.Guild) -> Optional[discord.Role]:
    return discord.utils.get(guild.roles, name=BOOSTER_ROLE_NAME)

def user_is_booster(member: discord.Member) -> bool:
    booster_role = get_booster_role(member.guild)
    return booster_role is not None and booster_role in member.roles

def get_owned_role(guild: discord.Guild, user_id: int) -> Optional[discord.Role]:
    role_id = get_user_role_id(user_id)
    if role_id is None:
        return None
    return guild.get_role(role_id)

async def ensure_booster_interaction(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "This can only be used inside the server.",
            ephemeral=True
        )
        return False

    if not user_is_booster(interaction.user):
        await interaction.response.send_message(
            "Only server boosters can use this panel.",
            ephemeral=True
        )
        return False

    return True

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

    embed = discord.Embed(
        title="Your Custom Role",
        color=color_value
    )
    embed.add_field(name="Role Name", value=role.name, inline=False)
    embed.add_field(name="Role Mention", value=role.mention, inline=False)
    embed.add_field(name="Color", value=f"`#{role.color.value:06x}`", inline=False)
    embed.add_field(name="Members", value=str(len(role.members)), inline=False)
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
            name=str(self.role_name),
            reason=f"Custom booster role created for {member}"
        )

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
        set_user_role_id(member.id, role.id)

        await interaction.response.send_message(
            f"Created your custom role {role.mention}.",
            ephemeral=True
        )

class EditRoleModal(discord.ui.Modal, title="Edit Custom Role"):
    role_name = discord.ui.TextInput(
        label="New Role Name",
        placeholder="Leave as current or enter a new name",
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
        await interaction.response.send_message(
            f"Updated your custom role {role.mention}.",
            ephemeral=True
        )

# ----------------------------
# Select Views
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

        await selected_user.add_roles(role, reason=f"Added to custom role by {member}")
        await interaction.response.send_message(
            f"Added {selected_user.mention} to {role.mention}.",
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

        await selected_user.remove_roles(role, reason=f"Removed from custom role by {member}")
        await interaction.response.send_message(
            f"Removed {selected_user.mention} from {role.mention}.",
            ephemeral=True
        )

class RemoveUserView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(RemoveUserSelect())

# ----------------------------
# Persistent Panel View
# ----------------------------
class RolePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Role", style=discord.ButtonStyle.primary, custom_id="y1")
    async def create_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return
        await interaction.response.send_modal(CreateRoleModal())

    @discord.ui.button(label="Edit Role", style=discord.ButtonStyle.secondary, custom_id="y2")
    async def edit_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_booster_interaction(interaction):
            return
        await interaction.response.send_modal(EditRoleModal())

    @discord.ui.button(label="View Role", style=discord.ButtonStyle.secondary, custom_id="y3")
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

    @discord.ui.button(label="Add User", style=discord.ButtonStyle.success, custom_id="g1")
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
            "Select a user to add to your custom role:",
            view=AddUserView(),
            ephemeral=True
        )

    @discord.ui.button(label="Remove User", style=discord.ButtonStyle.danger, custom_id="b3")
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

# ----------------------------
# Setup hook / ready
# ----------------------------
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)

    try:
        synced = await tree.sync(guild=guild)
        print(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Register persistent view so buttons keep working after restarts
    bot.add_view(RolePanelView())

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# ----------------------------
# Staff setup command
# ----------------------------
@tree.command(
    name="setup_customroles_panel",
    description="Post the custom roles panel",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_customroles_panel(interaction: discord.Interaction):
    embeds = build_panel_embeds()

    await interaction.channel.send(
        embeds=embeds,
        view=RolePanelView()
    )

    await interaction.response.send_message(
        "Custom roles panel posted.",
        ephemeral=True
    )

# ----------------------------
# Optional admin-only repost command
# ----------------------------
@tree.command(
    name="repost_customroles_panel",
    description="Repost the custom roles panel",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(manage_guild=True)
async def repost_customroles_panel(interaction: discord.Interaction):
    embeds = build_panel_embeds()

    await interaction.channel.send(
        embeds=embeds,
        view=RolePanelView()
    )

    await interaction.response.send_message(
        "Custom roles panel reposted.",
        ephemeral=True
    )

# ----------------------------
# Optional delete-my-role command
# ----------------------------
@tree.command(
    name="delete_my_custom_role",
    description="Delete your custom role",
    guild=discord.Object(id=GUILD_ID)
)
async def delete_my_custom_role(interaction: discord.Interaction):
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
    remove_user_role_id(member.id)

    await interaction.response.send_message(
        f"Deleted your custom role **{role_name}**.",
        ephemeral=True
    )

# ----------------------------
# Auto-delete role if user stops boosting
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
                remove_user_role_id(after.id)

# ----------------------------
# App command error handling
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
