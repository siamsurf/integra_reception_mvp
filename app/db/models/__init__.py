"""Import all ORM models so SQLAlchemy metadata is fully registered."""

from app.db.models.ai_output import AIOutput
from app.db.models.attachment import Attachment
from app.db.models.lead import Lead
from app.db.models.precheck_result import PrecheckResult

__all__ = ["Lead", "AIOutput", "PrecheckResult", "Attachment"]
