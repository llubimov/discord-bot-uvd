import discord
from discord.ui import View, Button
import logging
from views.message_texts import ErrorMessages
from views.warehouse_selectors import CategorySelect
from services.warehouse_session import WarehouseSession

logger = logging.getLogger(__name__)


class WarehouseStartView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📦 ЗАПРОСИТЬ СНАРЯЖЕНИЕ",
        style=discord.ButtonStyle.primary,
        custom_id="warehouse_request_button",
        emoji="📦",
        row=0
    )
    async def request_button(self, interaction: discord.Interaction, button: Button):
        """Начать новый запрос"""
        try:
            view = View(timeout=180)
            view.add_item(CategorySelect())

            await interaction.response.send_message(
                "**📦 НОВЫЙ ЗАПРОС СНАРЯЖЕНИЯ**\n\n"
                "Выбери категорию из списка ниже:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error("Ошибка в request_button: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)

    @discord.ui.button(
        label="🛒 МОЯ КОРЗИНА",
        style=discord.ButtonStyle.secondary,
        custom_id="warehouse_cart_button",
        emoji="🛒",
        row=0
    )
    async def cart_button(self, interaction: discord.Interaction, button: Button):
        """Показать текущую корзину"""
        try:
            items = WarehouseSession.get_items(interaction.user.id)

            if not items:
                await interaction.response.send_message(
                    "🛒 **Корзина пуста**\n\nНажми «📦 ЗАПРОСИТЬ СНАРЯЖЕНИЕ» чтобы добавить предметы.",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="🛒 ТВОЯ КОРЗИНА",
                color=discord.Color.blue(),
                description="**Текущий состав запроса:**"
            )

            by_category = {}
            for item in items:
                cat = item["category"]
                by_category.setdefault(cat, []).append(item)

            weapon_count = 0
            armor_count = 0
            meds_count = 0

            for cat, cat_items in by_category.items():
                cat_text = ""
                for it in cat_items:
                    qty = int(it.get("quantity", 0))
                    cat_text += f"• {it['item']} — **{qty}** шт\n"

                    cat_norm = str(cat).lower()
                    if "оруж" in cat_norm:
                        weapon_count += qty
                    elif "брон" in cat_norm:
                        armor_count += qty
                    elif "мед" in cat_norm:
                        meds_count += qty

                embed.add_field(name=cat, value=cat_text, inline=False)

            stats = []
            if weapon_count > 0:
                stats.append(f"🔫 Оружие: {weapon_count}/3")
            if armor_count > 0:
                stats.append(f"🛡️ Броня: {armor_count}/20")
            if meds_count > 0:
                stats.append(f"💊 Медицина: {meds_count}/20")

            if stats:
                embed.add_field(name="📊 Лимиты", value=" | ".join(stats), inline=False)

            embed.set_footer(text=f"Всего предметов: {len(items)}")

            from views.warehouse_actions import WarehouseActionView
            view = WarehouseActionView()

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error("Ошибка в корзине: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)