from __future__ import annotations

import logging

import discord
from discord.ui import View, Button

from modals.department_apply import open_apply_modal
from services.department_roles import get_dept_role_id

logger = logging.getLogger(__name__)


class ApplyChannelView(View):
    timeout = None

    def __init__(self, target_dept: str, buttons: list[tuple[str, str]]):
        super().__init__(timeout=None)
        self.target_dept = (target_dept or "").strip().lower()
        for source_dept, label in buttons:
            # Уникальный custom_id для персистентных view при перезапуске
            cid = f"apply_{self.target_dept}_{source_dept}"
            btn = Button(label=label, style=discord.ButtonStyle.primary, custom_id=cid)
            btn.callback = self._make_callback(source_dept)
            self.add_item(btn)

    def _make_callback(self, source_dept: str):
        async def callback(interaction: discord.Interaction):
            try:
                if isinstance(interaction.user, discord.Member):
                    guild = interaction.guild
                    dept_role_id = get_dept_role_id(source_dept)
                    role = guild.get_role(dept_role_id) if guild and dept_role_id else None
                    if role and role not in interaction.user.roles:
                        await interaction.response.send_message(
                            "❌ Вы не относитесь к этому отделу и не можете подавать заявку от его имени.",
                            ephemeral=True,
                        )
                        return
                modal = open_apply_modal(interaction, self.target_dept, source_dept)
                if modal:
                    await interaction.response.send_modal(modal)
                else:
                    await interaction.response.send_message("❌ Неизвестный канал заявок.", ephemeral=True)
            except Exception as e:
                logger.error("Ошибка открытия модала заявки: %s", e, exc_info=True)
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Ошибка.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Ошибка.", ephemeral=True)
        return callback
