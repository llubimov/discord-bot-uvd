import discord
from discord.ui import Modal, TextInput
import logging
import asyncio
from config import Config
from views.message_texts import ErrorMessages
from utils.validators import Validators
from utils.embed_utils import copy_embed, add_officer_field, add_reject_reason
from database import delete_request
from services.action_locks import action_lock

logger = logging.getLogger(__name__)


class BaseRejectModal(Modal):

    def __init__(self, user_id: int, message_id: int, **kwargs):
        super().__init__(title=self.get_modal_title())
        self.user_id = user_id
        self.message_id = message_id
        self.additional_data = kwargs

        self.reason = TextInput(
            label="Причина отказа",
            placeholder="укажите причину отклонения",
            max_length=Config.MAX_REASON_LENGTH,
            style=discord.TextStyle.paragraph,
            required=True,
        )
        self.add_item(self.reason)

    @classmethod
    def get_modal_title(cls):
        return "отклонение"

    async def get_staff_role_id(self, interaction: discord.Interaction) -> int:
        raise NotImplementedError

    async def get_allowed_role_ids(self, interaction: discord.Interaction) -> list[int]:
        rid = await self.get_staff_role_id(interaction)
        return [int(rid)] if rid else []

    async def get_request_data(self, message_id: int):
        raise NotImplementedError

    async def try_restore_missing_request(self, interaction: discord.Interaction) -> bool:
        return False

    def get_view_class(self):
        raise NotImplementedError

    def get_state_dict(self):
        raise NotImplementedError

    def get_table_name(self) -> str:
        raise NotImplementedError

    def get_notification_title(self) -> str:
        return "❌ заявка отклонена"

    def get_item_name(self) -> str:
        return "заявка"

    async def get_view_instance(self, interaction: discord.Interaction, request_data: dict):
        view_class = self.get_view_class()

        # Создаем экземпляр view с нужными параметрами
        if self.get_table_name() == "requests":
            from views.request_view import RequestView
            from enums import RequestType

            request_type = RequestType(request_data.get("request_type", "cadet"))
            view = RequestView(
                user_id=self.user_id,
                validated_data=request_data,
                request_type=request_type,
                **{
                    k: v
                    for k, v in request_data.items()
                    if k not in [
                        "user_id",
                        "message_id",
                        "message_link",
                        "embed",
                        "request_type",
                        "created_at",
                        "name",
                        "surname",
                        "static_id",
                    ]
                },
            )
        elif self.get_table_name() == "firing_requests":
            from views.firing_view import FiringView
            view = FiringView(user_id=self.user_id)
        elif self.get_table_name() == "promotion_requests":
            from views.promotion_view import PromotionView
            view = PromotionView(
                user_id=self.user_id,
                new_rank=self.additional_data.get("new_rank", ""),
                full_name=self.additional_data.get("full_name", ""),
                message_id=self.message_id,
            )
        else:
            view = view_class()

        # Отключаем все кнопки
        for item in view.children:
            item.disabled = True

        return view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            async with action_lock(self.message_id, f"отклонение {self.get_item_name()}"):
                # 1) Проверка прав
                allowed_role_ids = await self.get_allowed_role_ids(interaction)
                guild = interaction.guild
                member_roles = set(guild.get_member(interaction.user.id).roles) if guild else set()

                has_permission = False
                if guild and allowed_role_ids:
                    for rid in allowed_role_ids:
                        role = guild.get_role(int(rid))
                        if role and role in member_roles:
                            has_permission = True
                            break

                if not has_permission:
                    await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
                    return

                # 2) Валидация причины
                valid, reason = Validators.validate_reason(self.reason.value)
                if not valid:
                    await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
                    return

                # 3) Проверка существования заявки (+ fallback восстановление)
                request_data = await self.get_request_data(self.message_id)
                if not request_data:
                    restored = False
                    try:
                        restored = await self.try_restore_missing_request(interaction)
                    except Exception as e:
                        logger.warning(
                            "Ошибка fallback-восстановления %s %s: %s",
                            self.get_item_name(),
                            self.message_id,
                            e,
                            exc_info=True,
                        )

                    if restored:
                        request_data = await self.get_request_data(self.message_id)

                if not request_data:
                    await interaction.response.send_message(
                        ErrorMessages.NOT_FOUND.format(item=self.get_item_name()),
                        ephemeral=True,
                    )
                    return

                # 4) Получаем сообщение и обновляем embed
                try:
                    message = await interaction.channel.fetch_message(self.message_id)
                except discord.NotFound:
                    state_dict = self.get_state_dict()
                    state_dict.pop(self.message_id, None)
                    await delete_request(self.get_table_name(), self.message_id)

                    await interaction.response.send_message(
                        f"❌ {self.get_item_name()} не найдена (сообщение удалено). Запись очищена.",
                        ephemeral=True,
                    )
                    return
                except discord.Forbidden:
                    await interaction.response.send_message(
                        "❌ У бота нет доступа к сообщению в этом канале.",
                        ephemeral=True,
                    )
                    return
                except discord.HTTPException as e:
                    logger.warning("HTTP ошибка fetch_message при отклонении %s %s: %s", self.get_item_name(), self.message_id, e)
                    await interaction.response.send_message("❌ Ошибка Discord API при получении сообщения.", ephemeral=True)
                    return

                if not message.embeds:
                    await interaction.response.send_message(
                        f"❌ Невозможно обработать {self.get_item_name()}: у сообщения нет embed.",
                        ephemeral=True,
                    )
                    return

                new_embed = copy_embed(message.embeds[0])
                new_embed = add_officer_field(new_embed, interaction.user.mention)
                new_embed = add_reject_reason(new_embed, reason)
                new_embed.color = discord.Color.light_gray()

                # 5) Получаем view с отключенными кнопками
                view = await self.get_view_instance(interaction, request_data)

                try:
                    await message.edit(embed=new_embed, view=view)
                except discord.NotFound:
                    await interaction.response.send_message(
                        f"❌ {self.get_item_name()} не найдена (сообщение удалено).",
                        ephemeral=True,
                    )
                    return
                except discord.Forbidden:
                    await interaction.response.send_message(
                        "❌ У бота нет прав на редактирование сообщения.",
                        ephemeral=True,
                    )
                    return
                except discord.HTTPException as e:
                    logger.warning("HTTP ошибка edit при отклонении %s %s: %s", self.get_item_name(), self.message_id, e)
                    await interaction.response.send_message("❌ Ошибка Discord API при обновлении сообщения.", ephemeral=True)
                    return

                # 6) Уведомление пользователю (если получилось)
                dm_warning = None
                member = interaction.guild.get_member(self.user_id) if interaction.guild else None
                if member:
                    try:
                        item_name = self.get_item_name()
                        # Рапорт — мужской род (ваш/был отклонён), заявка — женский (ваша/была отклонена)
                        if "рапорт" in item_name.lower():
                            dm_desc = f"**{interaction.guild.name}**\n\nВаш {item_name} был отклонён."
                        else:
                            dm_desc = f"**{interaction.guild.name}**\n\nВаша {item_name} была отклонена."
                        dm_embed = discord.Embed(
                            title=self.get_notification_title(),
                            color=discord.Color.light_gray(),
                            description=dm_desc,
                            timestamp=interaction.created_at,
                        )
                        dm_embed.add_field(name="Причина", value=reason, inline=False)
                        dm_embed.add_field(name="Отклонил", value=interaction.user.mention, inline=True)

                        if self.get_table_name() == "promotion_requests":
                            dm_embed.add_field(
                                name="Звание",
                                value=self.additional_data.get("new_rank", "") or "—",
                                inline=True,
                            )

                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        dm_warning = f"⚠️ не удалось отправить уведомление пользователю {member.mention}"
                    except discord.HTTPException as e:
                        logger.warning("HTTP ошибка DM пользователю %s: %s", member.id, e)
                        dm_warning = f"⚠️ не удалось отправить уведомление пользователю {member.mention}"

                # 7) Удаление из state и БД
                state_dict = self.get_state_dict()
                if self.message_id in state_dict:
                    del state_dict[self.message_id]
                await delete_request(self.get_table_name(), self.message_id)

                # 8) Ответ
                _item = self.get_item_name()
                _end = "отклонён. Причина:" if "рапорт" in _item.lower() else "отклонена. Причина:"
                await interaction.response.send_message(
                    f"✅ {_item.capitalize()} {_end} {reason}",
                    ephemeral=True,
                )

                if dm_warning:
                    await interaction.followup.send(dm_warning, ephemeral=True)

                logger.info("%s %s отклонена сотрудником %s", self.get_item_name(), self.message_id, interaction.user.id)

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                if interaction.response.is_done():
                    await interaction.followup.send("⚠️ Это действие уже выполняется другим нажатием.", ephemeral=True)
                else:
                    await interaction.response.send_message("⚠️ Это действие уже выполняется другим нажатием.", ephemeral=True)
                return

            logger.error("Ошибка блокировки при отклонении %s: %s", self.get_item_name(), e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)

        except Exception as e:
            logger.error("Ошибка при отклонении %s: %s", self.get_item_name(), e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)