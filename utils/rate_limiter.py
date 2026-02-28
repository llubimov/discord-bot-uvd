import asyncio
import discord
import logging
import random

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self):
        self.base_delay = 1
        self.max_delay = 60

    def get_wait_time(self, attempt: int, retry_after: float = None) -> float:
        if retry_after:
            return retry_after + random.uniform(0, 1)
        delay = min(self.max_delay, self.base_delay * (2 ** attempt))
        jitter = random.uniform(0, delay * 0.1)
        return delay + jitter


rate_limiter = RateLimiter()

async def discord_api_call(coro, *args, max_retries=5, **kwargs):
    for attempt in range(max_retries):
        try:
            return await coro(*args, **kwargs)
        except discord.HTTPException as e:
            if e.status == 429 and attempt < max_retries - 1:
                retry_after = getattr(e, 'retry_after', None)
                wait_time = rate_limiter.get_wait_time(attempt, retry_after)
                logger.warning(
                    f"Rate limit на попытке {attempt+1}/{max_retries}. Ожидание {wait_time:.2f}с"
                )
                await asyncio.sleep(wait_time)
                continue
            raise
    error_msg = f"Превышено максимальное количество попыток ({max_retries}) для {coro.__name__}"
    logger.error(error_msg)
    raise Exception(error_msg)

async def safe_discord_call(coro, *args, **kwargs):
    try:
        return await discord_api_call(coro, *args, **kwargs)
    except discord.Forbidden:
        logger.error(f"Нет прав для {coro.__name__}")
        raise
    except discord.NotFound:
        logger.error(f"Ресурс не найден в {coro.__name__}")
        raise
    except Exception as e:
        logger.error(f"Неожиданная ошибка в {coro.__name__}: {e}")
        raise

async def safe_send(channel, *args, **kwargs):
    return await safe_discord_call(channel.send, *args, **kwargs)

async def safe_edit(message, *args, **kwargs):
    return await safe_discord_call(message.edit, *args, **kwargs)

async def safe_delete(message):
    return await safe_discord_call(message.delete)

async def apply_role_changes(member, add=None, remove=None, delay: float = 0.5):
    add = add or []
    remove = remove or []
    for role in remove:
        if role and role in member.roles:
            await safe_discord_call(member.remove_roles, role)
            await asyncio.sleep(delay)
    for role in add:
        if role and role not in member.roles:
            await safe_discord_call(member.add_roles, role)
            await asyncio.sleep(delay)

async def batch_role_changes(member, add=None, remove=None):
    add = add or []
    remove = remove or []
    
    if add or remove:
        roles_to_add = [r for r in add if r and r not in member.roles]
        roles_to_remove = [r for r in remove if r and r in member.roles]
        if roles_to_add or roles_to_remove:
            new_roles = set(member.roles)
            new_roles.difference_update(roles_to_remove)
            new_roles.update(roles_to_add)
            await safe_discord_call(member.edit, roles=list(new_roles))
            return True
    return False