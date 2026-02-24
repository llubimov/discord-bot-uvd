import discord
from discord.ui import View, Button
import logging
import asyncio

from config import Config
from enums import RequestType
from state import active_requests, bot
from utils.rate_limiter import apply_role_changes
from utils.embed_utils import update_embed_status, add_officer_field, copy_embed
from services.audit import send_to_audit
from services.action_locks import action_lock
from database import delete_request
from modals.reject_reason import RejectReasonModal
from modals.edit_request import EditRequestModal
from constants import StatusValues, FieldNames
from views.message_texts import AcceptMessages, ErrorMessages, SuccessMessages

logger = logging.getLogger(__name__)


class RequestView(View):
    def __init__(self, user_id: int, validated_data: dict, request_type: RequestType, **kwargs):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.validated_data = validated_data
        self.request_type = request_type
        self.additional_data = kwargs

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id")
        if custom_id in ["accept", "reject"]:
            staff_role_id = self.request_type.get_staff_role_id()
            staff_role = interaction.guild.get_role(staff_role_id)
            if staff_role not in interaction.user.roles:
                await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
                return False
        elif custom_id == "edit":
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ это не ваша заявка!", ephemeral=True)
                return False
        return True

    @discord.ui.button(label="✅ принять", style=discord.ButtonStyle.success, custom_id="accept")
    async def accept_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_accept(interaction)

    @discord.ui.button(label="❌ отклонить", style=discord.ButtonStyle.danger, custom_id="reject")
    async def reject_button(self, interaction: discord.Interaction, button: Button):
        modal = RejectReasonModal(user_id=self.user_id, request_type=self.request_type, message_id=interaction.message.id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✏️ редактировать", style=discord.ButtonStyle.secondary, custom_id="edit")
    async def edit_button(self, interaction: discord.Interaction, button: Button):
        embed = interaction.message.embeds[0]
        for field in embed.fields:
            if field.name == FieldNames.STATUS and ("✅" in field.value or "❌" in field.value):
                await interaction.response.send_message("❌ заявка уже обработана и не может быть отредактирована!", ephemeral=True)
                return

        request_data = active_requests.get(interaction.message.id, {})
        modal = EditRequestModal(
            user_id=self.user_id,
            request_type=self.request_type,
            current_data=request_data,
            message_id=interaction.message.id
        )
        await interaction.response.send_modal(modal)

    async def handle_accept(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(self.user_id)
        if not member:
            await interaction.response.send_message(ErrorMessages.NOT_FOUND.format(item="пользователь"), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            async with action_lock(interaction.message.id, "принятие заявки"):
                roles_to_give = self.request_type.get_roles_to_give()
                roles = [interaction.guild.get_role(rid) for rid in roles_to_give if interaction.guild.get_role(rid)]
                await apply_role_changes(member, add=roles)

                try:
                    prefix = self.request_type.get_nickname_prefix()
                    new_nick = f"{prefix} {self.validated_data['name']} {self.validated_data['surname']}"
                    await member.edit(nick=new_nick)
                except Exception as e:
                    logger.error(f"ошибка при смене ника: {e}")

                message_link = f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{interaction.message.id}"

                await send_to_audit(
                    interaction,
                    member,
                    Config.ACTION_ACCEPTED,
                    "Рядовой полиции",
                    message_link
                )

                # Элитное приветствие для курсанта
                if self.request_type == RequestType.CADET:
                    from datetime import datetime
                    import random
                    from views.training_buttons import ExamView
                    from constants import ExamMessages

                    now = datetime.now()
                    report_id = f"УВД-{random.randint(1000, 9999)}"

                    embed = discord.Embed(
                        title=ExamMessages.WELCOME_TITLE,
                        color=0x0B3B5B
                    )

                    embed.set_thumbnail(url=ExamMessages.HERB_URL)

                    embed.add_field(
                        name="",
                        value=(
                            ExamMessages.WELCOME_HEADER +
                            ExamMessages.WELCOME_TEXT.format(
                                report_id=report_id,
                                day=now.day,
                                month=ExamMessages.MONTHS[now.month],
                                year=now.year,
                                name=self.validated_data['name']
                            )
                        ),
                        inline=False
                    )

                    embed.add_field(
                        name="👤 Кандидат",
                        value=f"```{self.validated_data['name']} {self.validated_data['surname']}```",
                        inline=True
                    )

                    embed.add_field(
                        name="📋 Статус",
                        value="```Курсант```",
                        inline=True
                    )

                    embed.add_field(
                        name="🆔 Номер",
                        value=f"```{report_id.split('-')[1]}```",
                        inline=True
                    )

                    embed.add_field(
                        name="👮 Принял",
                        value=interaction.user.mention,
                        inline=False
                    )

                    embed.set_image(url=ExamMessages.SEAL_URL)

                    embed.set_footer(
                        text="Управление Внутренних Дел • Кадровый департамент",
                        icon_url=ExamMessages.HERB_URL
                    )

                    view = ExamView(timeout_seconds=Config.EXAM_BUTTON_TIMEOUT)
                    try:
                        msg = await member.send(embed=embed, view=view)
                        await view.start_timer(msg, member.id)
                    except discord.Forbidden:
                        logger.warning("Не удалось отправить ЛС с экзаменом пользователю %s (DM закрыты)", member.id)
                        await interaction.followup.send(
                            f"⚠️ Заявка принята, но не удалось отправить ЛС пользователю {member.mention}.",
                            ephemeral=True
                        )
                    except discord.HTTPException as e:
                        logger.warning("HTTP ошибка отправки ЛС с экзаменом пользователю %s: %s", member.id, e)
                        await interaction.followup.send(
                            f"⚠️ Заявка принята, но ЛС пользователю {member.mention} временно не доставлено.",
                            ephemeral=True
                        )

                # Обновление embed
                embed = copy_embed(interaction.message.embeds[0])
                embed = update_embed_status(embed, StatusValues.ACCEPTED, discord.Color.green())
                embed = add_officer_field(embed, interaction.user.mention)

                await interaction.message.edit(embed=embed, view=None)

                if interaction.message.id in active_requests:
                    del active_requests[interaction.message.id]
                    await asyncio.to_thread(delete_request, 'requests', interaction.message.id)

                await interaction.followup.send(f"✅ заявка принята! выдано ролей: {len(roles)}", ephemeral=True)

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                await interaction.followup.send("⚠️ эта заявка уже обрабатывается другим нажатием.", ephemeral=True)
                return
            logger.error("ошибка блокировки заявки: %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)

        except Exception as e:
            logger.error(f"ошибка при принятии заявки: {e}", exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)