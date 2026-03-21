import json
import os
import re
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

# ----------------------------
# Intents
# ----------------------------
intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ----------------------------
# Simple JSON storage helpers
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

def get_user_role_id(user_id: int):
    data = load_data()
    return data.get(str(user_id))

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
# Utility helpers
# ----------------------------
def parse_hex_color(hex_string: str) -> discord.Color:
    hex_string = hex_string.strip().replace("#", "")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", hex_string):
        raise ValueError("Invalid hex color.")
    return discord.Color(int(hex_string, 16))

def user_is_booster(member: discord.Member) -> bool:
    booster_role = discord.utils.get(member.guild.roles, name=BOOSTER_ROLE_NAME)
    return booster_role is not None and booster_role in member.roles

def get_owned_role(guild: discord.Guild, user_id: int):
    role_id = get_user_role_id(user_id)
    if role_id is None:
        return None
    return guild.get_role(role_id)

async def ensure_booster(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "This command only works in a server.",
            ephemeral=True
        )
        return False

    if not user_is_booster(interaction.user):
        await interaction.response.send_message(
            "You must be a server booster to use this command.",
            ephemeral=True
        )
        return False

    return True

# ----------------------------
# Bot ready event
# ----------------------------
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    try:
        synced = await tree.sync(guild=guild)
        print(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# ----------------------------
# /createrole
# ----------------------------
@tree.command(
    name="createrole",
    description="Create your personal booster role",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(name="The name of your custom role")
async def createrole(interaction: discord.Interaction, name: str):
    if not await ensure_booster(interaction):
        return

    member = interaction.user
    guild = interaction.guild

    existing_role = get_owned_role(guild, member.id)
    if existing_role is not None:
        await interaction.response.send_message(
            f"You already have a role: {existing_role.mention}",
            ephemeral=True
        )
        return

    role = await guild.create_role(
        name=name,
        reason=f"Custom booster role created for {member}"
    )

    await member.add_roles(role, reason="Assigning newly created custom booster role")
    set_user_role_id(member.id, role.id)

    await interaction.response.send_message(
        f"Created your role {role.mention} and assigned it to you.",
        ephemeral=True
    )

# ----------------------------
# /renamerole
# ----------------------------
@tree.command(
    name="renamerole",
    description="Rename your custom booster role",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(new_name="Your new role name")
async def renamerole(interaction: discord.Interaction, new_name: str):
    if not await ensure_booster(interaction):
        return

    guild = interaction.guild
    member = interaction.user
    role = get_owned_role(guild, member.id)

    if role is None:
        await interaction.response.send_message(
            "You do not have a custom role yet. Use /createrole first.",
            ephemeral=True
        )
        return

    await role.edit(name=new_name, reason=f"Role renamed by owner {member}")
    await interaction.response.send_message(
        f"Your role has been renamed to **{new_name}**.",
        ephemeral=True
    )

# ----------------------------
# /rolecolor
# ----------------------------
@tree.command(
    name="rolecolor",
    description="Change your role color using hex",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(hex_color="Example: #ff0000")
async def rolecolor(interaction: discord.Interaction, hex_color: str):
    if not await ensure_booster(interaction):
        return

    guild = interaction.guild
    member = interaction.user
    role = get_owned_role(guild, member.id)

    if role is None:
        await interaction.response.send_message(
            "You do not have a custom role yet. Use /createrole first.",
            ephemeral=True
        )
        return

    try:
        color = parse_hex_color(hex_color)
    except ValueError:
        await interaction.response.send_message(
            "Invalid hex color. Use something like `#ff0000`.",
            ephemeral=True
        )
        return

    await role.edit(color=color, reason=f"Role color changed by owner {member}")
    await interaction.response.send_message(
        f"Updated your role color to `{hex_color}`.",
        ephemeral=True
    )

# ----------------------------
# /addtorole
# ----------------------------
@tree.command(
    name="addtorole",
    description="Add a user to your custom role",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(user="The member to add to your role")
async def addtorole(interaction: discord.Interaction, user: discord.Member):
    if not await ensure_booster(interaction):
        return

    guild = interaction.guild
    member = interaction.user
    role = get_owned_role(guild, member.id)

    if role is None:
        await interaction.response.send_message(
            "You do not have a custom role yet. Use /createrole first.",
            ephemeral=True
        )
        return

    if user.bot:
        await interaction.response.send_message(
            "You cannot add a bot to your custom role.",
            ephemeral=True
        )
        return

    await user.add_roles(role, reason=f"Added to custom role by owner {member}")
    await interaction.response.send_message(
        f"Added {user.mention} to {role.mention}.",
        ephemeral=True
    )

# ----------------------------
# /removefromrole
# ----------------------------
@tree.command(
    name="removefromrole",
    description="Remove a user from your custom role",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(user="The member to remove from your role")
async def removefromrole(interaction: discord.Interaction, user: discord.Member):
    if not await ensure_booster(interaction):
        return

    guild = interaction.guild
    member = interaction.user
    role = get_owned_role(guild, member.id)

    if role is None:
        await interaction.response.send_message(
            "You do not have a custom role yet. Use /createrole first.",
            ephemeral=True
        )
        return

    if role not in user.roles:
        await interaction.response.send_message(
            f"{user.mention} does not have your role.",
            ephemeral=True
        )
        return

    await user.remove_roles(role, reason=f"Removed from custom role by owner {member}")
    await interaction.response.send_message(
        f"Removed {user.mention} from {role.mention}.",
        ephemeral=True
    )

# ----------------------------
# /deleterole
# ----------------------------
@tree.command(
    name="deleterole",
    description="Delete your custom booster role",
    guild=discord.Object(id=GUILD_ID)
)
async def deleterole(interaction: discord.Interaction):
    if not await ensure_booster(interaction):
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
# /myrole
# ----------------------------
@tree.command(
    name="myrole",
    description="See your custom booster role",
    guild=discord.Object(id=GUILD_ID)
)
async def myrole(interaction: discord.Interaction):
    if not await ensure_booster(interaction):
        return

    guild = interaction.guild
    member = interaction.user
    role = get_owned_role(guild, member.id)

    if role is None:
        await interaction.response.send_message(
            "You do not currently have a custom role.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"Your custom role is {role.mention} (ID: `{role.id}`).",
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

bot.run(TOKEN)