"""Role based access control definitions.

Permissions are plain strings so they can be stored in the ``roles.permissions``
JSON column and checked without touching the database on every request.
"""

from __future__ import annotations

from app.core.enums import UserRole

# --- permission catalogue -------------------------------------------------
USER_READ_SELF = "user:read:self"
USER_UPDATE_SELF = "user:update:self"
USER_READ_ALL = "user:read:all"
USER_MANAGE = "user:manage"

LOT_CREATE = "lot:create"
LOT_READ = "lot:read"
LOT_UPDATE_OWN = "lot:update:own"
LOT_PUBLISH = "lot:publish"
LOT_CANCEL = "lot:cancel"

DEMAND_CREATE = "demand:create"
DEMAND_READ = "demand:read"
DEMAND_UPDATE_OWN = "demand:update:own"
DEMAND_MANAGE_OWN = "demand:manage:own"

OFFER_CREATE = "offer:create"
OFFER_READ = "offer:read"
OFFER_RESPOND = "offer:respond"

ORDER_READ = "order:read"
ORDER_UPDATE_STATUS = "order:update:status"
ORDER_UPDATE_OWN = "order:update:own"

LOGISTICS_READ = "logistics:read"
LOGISTICS_REQUEST = "logistics:request"
LOGISTICS_ASSIGN = "logistics:assign"
LOGISTICS_UPDATE = "logistics:update"

STORAGE_READ = "storage:read"
STORAGE_MANAGE_OWN = "storage:manage:own"
STORAGE_MANAGE_ALL = "storage:manage:all"

PAYMENT_READ = "payment:read"
PAYMENT_UPDATE = "payment:update"

GRIEVANCE_CREATE = "grievance:create"
GRIEVANCE_READ = "grievance:read"
GRIEVANCE_UPDATE = "grievance:update"
GRIEVANCE_COMMENT = "grievance:comment"
GRIEVANCE_MANAGE = "grievance:manage"

QUALITY_SUBMIT = "quality:submit"
QUALITY_VERIFY = "quality:verify"
QUALITY_READ = "quality:read"

MARKET_READ = "market:read"
MARKET_MANAGE = "market:manage"
COMMODITY_MANAGE = "commodity:manage"
PRICE_MANAGE = "price:manage"

BUYER_VERIFY = "buyer:verify"

MATCH_READ = "match:read"
AI_CHAT = "ai:chat"
AI_RECOMMEND = "ai:recommend"

ANALYTICS_READ = "analytics:read"
AUDIT_READ = "audit:read"
ADMIN_DASHBOARD = "admin:dashboard"


ROLE_PERMISSIONS: dict[UserRole, list[str]] = {
    UserRole.FARMER: [
        USER_READ_SELF,
        USER_UPDATE_SELF,
        LOT_CREATE,
        LOT_READ,
        LOT_UPDATE_OWN,
        LOT_PUBLISH,
        LOT_CANCEL,
        DEMAND_READ,
        OFFER_READ,
        OFFER_RESPOND,
        ORDER_READ,
        ORDER_UPDATE_STATUS,
        ORDER_UPDATE_OWN,
        LOGISTICS_READ,
        LOGISTICS_REQUEST,
        STORAGE_READ,
        STORAGE_MANAGE_OWN,
        PAYMENT_READ,
        GRIEVANCE_CREATE,
        GRIEVANCE_READ,
        GRIEVANCE_UPDATE,
        GRIEVANCE_COMMENT,
        QUALITY_SUBMIT,
        QUALITY_READ,
        MARKET_READ,
        MATCH_READ,
        AI_CHAT,
        AI_RECOMMEND,
    ],
    UserRole.FPO: [
        USER_READ_SELF,
        USER_UPDATE_SELF,
        LOT_CREATE,
        LOT_READ,
        LOT_UPDATE_OWN,
        LOT_PUBLISH,
        LOT_CANCEL,
        DEMAND_READ,
        OFFER_READ,
        OFFER_RESPOND,
        ORDER_READ,
        ORDER_UPDATE_STATUS,
        ORDER_UPDATE_OWN,
        LOGISTICS_READ,
        LOGISTICS_REQUEST,
        STORAGE_READ,
        STORAGE_MANAGE_OWN,
        PAYMENT_READ,
        GRIEVANCE_CREATE,
        GRIEVANCE_READ,
        GRIEVANCE_UPDATE,
        GRIEVANCE_COMMENT,
        QUALITY_SUBMIT,
        QUALITY_READ,
        MARKET_READ,
        MATCH_READ,
        AI_CHAT,
        AI_RECOMMEND,
    ],
    UserRole.BUYER: [
        USER_READ_SELF,
        USER_UPDATE_SELF,
        DEMAND_CREATE,
        DEMAND_READ,
        DEMAND_UPDATE_OWN,
        DEMAND_MANAGE_OWN,
        OFFER_CREATE,
        OFFER_READ,
        OFFER_RESPOND,
        LOT_READ,
        ORDER_READ,
        ORDER_UPDATE_OWN,
        LOGISTICS_READ,
        LOGISTICS_REQUEST,
        PAYMENT_READ,
        PAYMENT_UPDATE,
        GRIEVANCE_CREATE,
        GRIEVANCE_READ,
        GRIEVANCE_UPDATE,
        GRIEVANCE_COMMENT,
        QUALITY_SUBMIT,
        QUALITY_READ,
        MARKET_READ,
        MATCH_READ,
        AI_CHAT,
        AI_RECOMMEND,
    ],
    UserRole.LOGISTICS_PARTNER: [
        USER_READ_SELF,
        USER_UPDATE_SELF,
        LOGISTICS_READ,
        LOGISTICS_ASSIGN,
        LOGISTICS_UPDATE,
        ORDER_READ,
        ORDER_UPDATE_STATUS,
        GRIEVANCE_CREATE,
        GRIEVANCE_READ,
        GRIEVANCE_UPDATE,
        GRIEVANCE_COMMENT,
        MARKET_READ,
    ],
    UserRole.QUALITY_INSPECTOR: [
        USER_READ_SELF,
        USER_UPDATE_SELF,
        QUALITY_VERIFY,
        QUALITY_SUBMIT,
        QUALITY_READ,
        LOT_READ,
        ORDER_READ,
        MARKET_READ,
        GRIEVANCE_READ,
    ],
    UserRole.ADMIN: [
        USER_READ_SELF,
        USER_UPDATE_SELF,
        USER_READ_ALL,
        USER_MANAGE,
        LOT_READ,
        LOT_CANCEL,
        DEMAND_READ,
        OFFER_READ,
        ORDER_READ,
        LOGISTICS_READ,
        STORAGE_READ,
        STORAGE_MANAGE_ALL,
        PAYMENT_READ,
        PAYMENT_UPDATE,
        GRIEVANCE_READ,
        GRIEVANCE_MANAGE,
        GRIEVANCE_COMMENT,
        QUALITY_VERIFY,
        QUALITY_READ,
        MARKET_READ,
        MARKET_MANAGE,
        COMMODITY_MANAGE,
        PRICE_MANAGE,
        BUYER_VERIFY,
        MATCH_READ,
        ANALYTICS_READ,
        AUDIT_READ,
        ADMIN_DASHBOARD,
        AI_CHAT,
        AI_RECOMMEND,
    ],
}

ROLE_DESCRIPTIONS: dict[UserRole, tuple[str, str]] = {
    UserRole.FARMER: ("Farmer", "Individual farmer selling own produce"),
    UserRole.FPO: ("Farmer Producer Organisation", "Aggregated producer collective"),
    UserRole.BUYER: ("Buyer", "Wholesaler, processor, retailer or institution"),
    UserRole.ADMIN: ("Administrator", "Government / platform administrator"),
    UserRole.LOGISTICS_PARTNER: (
        "Logistics Partner",
        "Transporter providing pickup and delivery services",
    ),
    UserRole.QUALITY_INSPECTOR: (
        "Quality Inspector",
        "Agri-metrician verifying grades and quality parameters",
    ),
}

SELLER_ROLES = {UserRole.FARMER, UserRole.FPO}


def permissions_for(role: UserRole) -> list[str]:
    return list(ROLE_PERMISSIONS.get(role, []))


def has_any_role(user_role: UserRole | None, allowed: set[UserRole]) -> bool:
    return user_role in allowed
