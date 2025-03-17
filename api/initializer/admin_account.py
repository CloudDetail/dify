from models import Account
from extensions.ext_database import db
from services.account_service import RegisterService
from . import initializer


@initializer(priority=1)
def init_admin_account():
    if db.session.query(Account).filter_by(name="admin").first():
        return
    
    accountService = RegisterService()
    accountService.setup("admin@apo.com", "admin", "APO2024@admin", "")
