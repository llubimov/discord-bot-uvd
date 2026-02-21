"""
=====================================================
МОДАЛКА ОТКЛОНЕНИЯ РАПОРТОВ ОБ УВОЛЬНЕНИИ
=====================================================
"""

import logging
from config import Config
from state import active_firing_requests
from .base_reject import BaseRejectModal

logger = logging.getLogger(__name__)

class FiringRejectReasonModal(BaseRejectModal):
    """Модалка отклонения рапортов об увольнении"""
    
    @classmethod
    def get_modal_title(cls):
        return "отклонение рапорта об увольнении"
    
    async def get_staff_role_id(self, interaction):
        return Config.FIRING_STAFF_ROLE_ID
    
    async def get_request_data(self, message_id):
        return active_firing_requests.get(message_id)
    
    def get_view_class(self):
        from views.firing_view import FiringView
        return FiringView
    
    def get_state_dict(self):
        return active_firing_requests
    
    def get_table_name(self):
        return 'firing_requests'
    
    def get_notification_title(self):
        return "❌ рапорт об увольнении отклонен"
    
    def get_item_name(self):
        return "рапорт"