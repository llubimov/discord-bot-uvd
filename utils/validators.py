#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
==============================================================
🔍 ВАЛИДАТОРЫ ДАННЫХ
==============================================================

Все проверки пользовательского ввода:
✅ Имена (только буквы, дефис, пробел)
✅ Static ID (формат XXX-XXX, только цифры)
✅ Причины и ссылки (длина, формат URL)
✅ Звания (буквы, пробелы, точки)

Каждый метод возвращает tuple: (успех, результат/ошибка)
==============================================================
"""

import re
import logging
from config import Config

logger = logging.getLogger(__name__)

class Validators:
    """
    Класс со статическими методами для валидации данных
    """
    
    @staticmethod
    def validate_name(name: str):
        """
        Проверяет корректность имени/фамилии
        
        Правила:
        - Не пустое
        - Длина от MIN_NAME_LENGTH до MAX_NAME_LENGTH
        - Только буквы, дефис и пробел
        - Без цифр
        - Автоматический капиталайз (первая буква заглавная)
        
        Args:
            name (str): имя для проверки
            
        Returns:
            tuple: (True, отформатированное имя) или (False, сообщение об ошибке)
        """
        try:
            name = name.strip()
            if not name:
                return False, "имя не может быть пустым"
            if len(name) < Config.MIN_NAME_LENGTH:
                return False, f"имя должно содержать минимум {Config.MIN_NAME_LENGTH} символа"
            if len(name) > Config.MAX_NAME_LENGTH:
                return False, f"имя не может быть длиннее {Config.MAX_NAME_LENGTH} символов"
            if not re.match(Config.NAME_PATTERN, name):
                return False, "имя может содержать только буквы, дефис и пробел"
            if re.search(r'\d', name):
                return False, "имя не может содержать цифры"
            formatted_name = ' '.join(word.capitalize() for word in name.split())
            return True, formatted_name
        except Exception as e:
            logger.error(f"ошибка валидации имени: {e}")
            return False, "ошибка при проверке имени"

    @staticmethod
    def format_static_id(static_id: str):
        try:
            numbers = re.sub(r'\D', '', static_id)
            if not numbers:
                return False, "static id не может быть пустым"
            if not numbers.isdigit():
                return False, "static id может содержать только цифры"
            if len(numbers) != Config.STATIC_ID_LENGTH:
                return False, f"static id должен содержать ровно {Config.STATIC_ID_LENGTH} цифр"
            formatted_id = Config.STATIC_ID_FORMAT.format(numbers[:3], numbers[3:])
            return True, formatted_id
        except Exception as e:
            logger.error(f"ошибка форматирования static id: {e}")
            return False, "ошибка при обработке static id"

    @staticmethod
    def validate_reason(reason: str, require_link: bool = False):
        try:
            reason = reason.strip()
            if not reason:
                return False, "поле не может быть пустым"
            if len(reason) > Config.MAX_REASON_LENGTH:
                return False, f"текст слишком длинный (максимум {Config.MAX_REASON_LENGTH} символов)"
            if require_link and not re.match(Config.URL_PATTERN, reason):
                return False, "пожалуйста, укажите корректную ссылку"
            return True, reason
        except Exception as e:
            logger.error(f"ошибка валидации причины: {e}")
            return False, "ошибка при проверке текста"

    @staticmethod
    def validate_rank(rank: str):
        try:
            rank = rank.strip()
            if not rank:
                return False, "звание не может быть пустым"
            if len(rank) > Config.MAX_RANK_LENGTH:
                return False, f"звание слишком длинное (максимум {Config.MAX_RANK_LENGTH} символов)"
            if not re.match(Config.RANK_PATTERN, rank):
                return False, "звание может содержать только буквы, пробел, дефис и точку"
            return True, rank
        except Exception as e:
            logger.error(f"ошибка валидации звания: {e}")
            return False, "ошибка при проверке звания"