# Import all models so SQLAlchemy registers them
from models.user import User, Role, Permission, UserRole, RolePermission  # noqa: F401
from models.chat import Chat  # noqa: F401
from models.message import Message  # noqa: F401
from models.kb_sync import KBSyncLog  # noqa: F401
