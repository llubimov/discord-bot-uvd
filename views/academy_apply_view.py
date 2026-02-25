from __future__ import annotations

import logging

import discord
from discord.ui import View, Button

from config import Config
from modals.department_apply import open_apply_modal

logger = logging.getLogger(__name__)

ACADEMY_APPLY_BUTTONS = [
    ("pps", "「ППС」"),
    ("grom", "「ГРОМ」"),
    ("orls", "「ОРЛС」"),
    ("osb", "「ОСБ」"),
]


class AcademyApplyView(View):
    timeout = None

    def __init__(self):
        super().__init__(timeout=None)
        for target_dept, label in ACADEMY_APPLY_BUTTONS:
            cid = f"apply_academy_{target_dept}"
            btn = Button(label=label, style=discord.ButtonStyle.primary, custom_id=cid)
            btn.callback = self._make_callback(target_dept)
            self.add_item(btn)

    def _make_callback(self, target_dept: str):
        async def callback(interaction: discord.Interaction):
            try:
                role_academy = getattr(Config, "ROLE_ACADEMY", 0)
                if not role_academy:
                    await interaction.response.send_message(
                        "❌ Роль академии не настроена.",
                        ephemeral=True,
                    )
                    return
                if isinstance(interaction.user, discord.Member):
                    guild = interaction.guild
                    role = guild.get_role(role_academy) if guild else None
                    if not role or role not in interaction.user.roles:
                        await interaction.response.send_message(
                            "❌ Подавать заявку из Академии могут только **выпускники академии** (наличие соответствующей роли).",
                            ephemeral=True,
                        )
                        return
                modal = open_apply_modal(interaction, target_dept, "academy")
                if modal:
                    await interaction.response.send_modal(modal)
                else:
                    await interaction.response.send_message("❌ Неизвестный отдел.", ephemeral=True)
            except Exception as e:
                logger.error("Ошибка открытия модала заявки из Академии: %s", e, exc_info=True)
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Ошибка.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Ошибка.", ephemeral=True)
        return callback
