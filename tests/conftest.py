# -*- coding: utf-8 -*-
import os
import pytest


@pytest.fixture(autouse=True, scope="session")
def minimal_env_for_imports():
    env = {
        "DISCORD_BOT_TOKEN": "test_token",
        "GUILD_ID": "1",
        "PROMOTION_CH_01": "1:2",
        "RANKMAP_01": "test:3",
    }
    for k, v in env.items():
        if k not in os.environ:
            os.environ[k] = v
