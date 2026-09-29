"""Model package - importing it registers every table on ``Base.metadata``."""

from app.db.base import Base
from app.models.ai import AIConversation, AIMessage, AIRecommendation
from app.models.catalog import (
    Commodity,
    Market,
    MarketDataSyncLog,
    QualityAttribute,
)
from app.models.logistics import LogisticsQuote, LogisticsRequest, StorageFacility
from app.models.market import MarketArrival, MarketPrice
from app.models.quality import QualityInspection, QualityMeasurement
from app.models.support import (
    Grievance,
    GrievanceComment,
    GrievanceEvidence,
    Payment,
)
from app.models.trade import (
    BuyerDemand,
    FarmLot,
    LotImage,
    Offer,
    Order,
    Transaction,
)
from app.models.user import (
    AuditLog,
    BuyerProfile,
    FarmerProfile,
    FPOProfile,
    Notification,
    RefreshToken,
    Role,
    User,
    UserRole,
)

__all__ = [
    "AIConversation",
    "AIMessage",
    "AIRecommendation",
    "AuditLog",
    "Base",
    "BuyerDemand",
    "BuyerProfile",
    "Commodity",
    "FPOProfile",
    "FarmLot",
    "FarmerProfile",
    "Grievance",
    "GrievanceComment",
    "GrievanceEvidence",
    "LogisticsQuote",
    "LogisticsRequest",
    "LotImage",
    "Market",
    "MarketArrival",
    "MarketDataSyncLog",
    "MarketPrice",
    "Notification",
    "Offer",
    "Order",
    "Payment",
    "QualityAttribute",
    "QualityInspection",
    "QualityMeasurement",
    "RefreshToken",
    "Role",
    "StorageFacility",
    "Transaction",
    "User",
    "UserRole",
]
