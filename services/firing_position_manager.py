import discord
from config import Config
from .base_position import BasePositionManager


class FiringStartView(discord.ui.View):
    timeout = None

    def __init__(self):
        super().__init__(timeout=None)
        btn = discord.ui.Button(
            label=Config.FIRING_BUTTON_LABEL,
            style=discord.ButtonStyle.danger,
            custom_id="firing_apply_btn",
        )
        btn.callback = self._on_click
        self.add_item(btn)

    async def _on_click(self, interaction: discord.Interaction):
        from modals.firing_apply_modal import FiringApplyModal
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        modal = FiringApplyModal(member=member)
        await interaction.response.send_modal(modal)


class FiringPositionManager(BasePositionManager):
    @property
    def channel_id(self) -> int:
        return Config.FIRING_CHANNEL_ID

    async def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=Config.FIRING_HEADER_TITLE,
            description=Config.FIRING_HEADER_DESC,
            color=discord.Color.red(),
        )
        return embed

    async def get_view(self) -> discord.ui.View:
        return FiringStartView()

    async def should_keep_message(self, message: discord.Message) -> bool:
        if not message.embeds:
            return False
        e = message.embeds[0]
        return (
            (e.title or "").strip() == Config.FIRING_HEADER_TITLE
            and (e.description or "").strip() == Config.FIRING_HEADER_DESC
        )
