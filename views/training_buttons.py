import discord
from discord.ui import View, Button
import logging
import asyncio
from config import Config

logger = logging.getLogger(__name__)


class ExamButton(Button):

    def __init__(self):
        super().__init__(
            label="🔊 ПЕРЕЙТИ В КАНАЛ ЭКЗАМЕНА",
            style=discord.ButtonStyle.success,
            emoji="🎓",
            custom_id="exam_button"
        )

    async def callback(self, interaction: discord.Interaction):

        guild = interaction.client.get_guild(Config.GUILD_ID)
        if not guild:
            await interaction.response.send_message(
                "❌ Не удалось найти сервер.",
                ephemeral=True
            )
            return

        # Получаем целевой канал
        channel = guild.get_channel(Config.EXAM_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message(
                "❌ Канал экзамена не найден!",
                ephemeral=True
            )
            return

        # Получаем участника
        member = guild.get_member(interaction.user.id)

        # Проверяем, что пользователь в голосовом канале
        if not member or not member.voice or not member.voice.channel:
            await interaction.response.send_message(
                "❌ Вы должны находиться в голосовом канале!\n"
                "Зайдите в любой голосовой канал и нажмите кнопку снова.",
                ephemeral=True
            )
            return

        try:
            # Перемещаем пользователя
            await member.move_to(channel)

            # После успешного перемещения убираем кнопку,
            # чтобы нельзя было нажать повторно
            try:
                await interaction.message.edit(view=None)
                logger.info("Кнопка экзамена удалена после успешного перемещения user_id=%s", interaction.user.id)
            except discord.NotFound:
                logger.warning("Сообщение с кнопкой экзамена уже удалено (user_id=%s)", interaction.user.id)
            except discord.Forbidden:
                logger.warning("Нет прав на редактирование сообщения с кнопкой экзамена (user_id=%s)", interaction.user.id)
            except discord.HTTPException as e:
                logger.warning("HTTP ошибка при удалении кнопки экзамена (user_id=%s): %s", interaction.user.id, e)

            # Отправляем подтверждение
            await interaction.response.send_message(
                f"✅ Вы перемещены в канал {channel.mention}!",
                ephemeral=True
            )

            logger.info(
                "Пользователь %s перемещен в канал экзамена %s",
                interaction.user.id,
                Config.EXAM_CHANNEL_ID
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ У бота нет прав для перемещения!\n"
                "Требуется право **Перемещать участников**",
                ephemeral=True
            )
        except discord.HTTPException as e:
            logger.error("HTTP ошибка при перемещении пользователя %s: %s", interaction.user.id, e, exc_info=True)
            await interaction.response.send_message(
                "❌ Ошибка Discord API при перемещении.",
                ephemeral=True
            )
        except Exception as e:
            logger.error("Ошибка перемещения пользователя %s: %s", interaction.user.id, e, exc_info=True)
            await interaction.response.send_message(
                "❌ Ошибка при перемещении",
                ephemeral=True
            )


class ExamView(View):

    def __init__(self, timeout_seconds: int = 3600):
        super().__init__(timeout=None)
        self.add_item(ExamButton())

        self.timeout_seconds = timeout_seconds
        self.message = None
        self.user_id = None
        self._destroy_task: asyncio.Task | None = None

    async def start_timer(self, message: discord.Message, user_id: int):
        self.message = message
        self.user_id = user_id

        # На всякий случай отменим предыдущую задачу таймера
        if self._destroy_task and not self._destroy_task.done():
            self._destroy_task.cancel()

        self._destroy_task = asyncio.create_task(self._auto_destroy())
        self._destroy_task.add_done_callback(self._on_destroy_task_done)

    def _on_destroy_task_done(self, task: asyncio.Task):
        try:
            if task.cancelled():
                return
            exc = task.exception()
            if exc:
                logger.error("Ошибка в таймере автоудаления экзамена: %s", exc, exc_info=exc)
        except Exception as e:
            logger.error("Ошибка callback таймера автоудаления: %s", e, exc_info=True)

    async def _auto_destroy(self):
        try:
            await asyncio.sleep(self.timeout_seconds)

            if not self.message:
                return

            try:
                await self.message.delete()
                logger.info(
                    "Сообщение экзамена автоудалено (user_id=%s, timeout=%s)",
                    self.user_id,
                    self.timeout_seconds
                )
            except discord.NotFound:
                logger.info("Сообщение экзамена уже удалено ранее (user_id=%s)", self.user_id)
            except discord.Forbidden:
                logger.warning("Нет прав на автоудаление сообщения экзамена (user_id=%s)", self.user_id)
            except discord.HTTPException as e:
                logger.warning("HTTP ошибка при автоудалении сообщения экзамена: %s", e)

        except asyncio.CancelledError:
            logger.debug("Таймер автоудаления экзамена отменён (user_id=%s)", self.user_id)
            raise
        except Exception as e:
            logger.error("Ошибка в _auto_destroy (exam view): %s", e, exc_info=True)