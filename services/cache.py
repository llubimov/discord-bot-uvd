import asyncio
from typing import Optional, List
import discord

class RoleCache:
    def __init__(self, bot):
        self.bot = bot
        self._roles = {}
        self._lock = asyncio.Lock()

    async def get_role(self, guild_id: int, role_id: int) -> Optional[discord.Role]:
        key = (guild_id, role_id)
        if key in self._roles:
            return self._roles[key]
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        role = guild.get_role(role_id)
        if role:
            self._roles[key] = role
        return role

    async def get_many_roles(self, guild_id: int, role_ids: List[int]) -> List[discord.Role]:
        tasks = [self.get_role(guild_id, rid) for rid in role_ids]
        return await asyncio.gather(*tasks)

    async def refresh_guild(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        async with self._lock:
            for role in guild.roles:
                self._roles[(guild_id, role.id)] = role

class ChannelCache:
    def __init__(self, bot):
        self.bot = bot
        self._channels = {}

    def get_channel(self, channel_id: int):
        if channel_id in self._channels:
            return self._channels[channel_id]
        ch = self.bot.get_channel(channel_id)
        if ch:
            self._channels[channel_id] = ch
        return ch