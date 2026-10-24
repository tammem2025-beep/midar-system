from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Platform = Literal["Facebook", "Instagram", "WhatsApp", "Telegram", "X", "YouTube", "TikTok", "LinkedIn", "Other"]

class SetupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    organization_name: str = Field(min_length=2, max_length=160)
    timezone: str = Field(default="Asia/Hebron", min_length=1, max_length=64)

    @field_validator("full_name", "organization_name")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("يجب إدخال حرفين على الأقل")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("المنطقة الزمنية غير معروفة") from exc
        return value

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    organization_id: str
    organization_name: str
    must_change_password: bool = False



class UserProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)

    @field_validator("full_name")
    @classmethod
    def clean_full_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("يجب إدخال اسم صحيح")
        return value


class UserPreferencesOut(BaseModel):
    theme_mode: Literal["dark", "light", "system"] = "dark"
    accent_color: Literal["violet", "blue", "cyan", "emerald", "rose", "amber"] = "blue"
    density: Literal["comfortable", "compact"] = "comfortable"


class UserPreferencesUpdate(BaseModel):
    theme_mode: Literal["dark", "light", "system"] | None = None
    accent_color: Literal["violet", "blue", "cyan", "emerald", "rose", "amber"] | None = None
    density: Literal["comfortable", "compact"] | None = None

    @model_validator(mode="after")
    def require_preference(self):
        if self.theme_mode is None and self.accent_color is None and self.density is None:
            raise ValueError("حدد تفضيلًا واحدًا على الأقل")
        return self


class GoogleLoginCompleteIn(BaseModel):
    code: str = Field(min_length=32, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

class MemberCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    temporary_password: str = Field(min_length=12, max_length=128)
    role: Literal["admin", "editor", "support", "analyst"] = "editor"

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("يجب إدخال اسم صحيح")
        return value

class MemberUpdate(BaseModel):
    role: Literal["admin", "editor", "support", "analyst"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.role is None and self.is_active is None:
            raise ValueError("حدد صلاحية أو حالة جديدة")
        return self

class TemporaryPasswordResetIn(BaseModel):
    temporary_password: str = Field(min_length=12, max_length=128)

class MemberOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime

class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    timezone: str
    created_at: datetime

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut

class ContactBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    company: str = Field(default="", max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    source: str = Field(default="manual", max_length=80)
    stage: Literal["new", "contacted", "qualified", "proposal", "won", "lost"] = "new"
    value: float = Field(default=0, ge=0, le=1_000_000_000)
    follow_up_at: datetime | None = None
    notes: str = Field(default="", max_length=10000)

class ContactCreate(ContactBase): pass
class ContactUpdate(ContactBase): pass
class ContactOut(ContactBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    created_at: datetime
    updated_at: datetime

class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=10000)
    assignee: str = Field(default="", max_length=160)
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["open", "in_progress", "done", "cancelled"] = "open"
    due_at: datetime | None = None

class TaskCreate(TaskBase): pass
class TaskUpdate(TaskBase): pass
class TaskOut(TaskBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    created_at: datetime
    updated_at: datetime

class PostBase(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=30000)
    platform: Platform
    status: Literal["draft", "scheduled", "cancelled"] = "draft"
    scheduled_at: datetime | None = None
    social_account_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def scheduled_requires_date(self):
        if self.status == "scheduled" and self.scheduled_at is None:
            raise ValueError("يجب تحديد موعد عندما تكون حالة المنشور مجدولة")
        return self

class PostCreate(PostBase): pass
class PostUpdate(PostBase): pass
class PostOut(PostBase):
    model_config = ConfigDict(from_attributes=True)
    # Output includes delivery lifecycle states, while input schemas deliberately
    # only allow editable draft/scheduled/cancelled states.
    status: str
    id: str
    organization_id: str
    created_by: str
    published_at: datetime | None = None
    provider_post_id: str | None = None
    publish_error: str | None = None
    review_note: str | None = None
    created_at: datetime
    updated_at: datetime

class TelegramDestinationVerifyIn(BaseModel):
    social_account_id: str = Field(min_length=1, max_length=36)

class PostReviewNoteIn(BaseModel):
    note: str = Field(min_length=5, max_length=1000)

    @field_validator("note")
    @classmethod
    def clean_review_note(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("أدخل ملاحظة مراجعة واضحة (5 أحرف على الأقل)")
        return value


class TelegramDeliveryResolveIn(BaseModel):
    resolution: Literal["published", "failed"]
    note: str = Field(min_length=5, max_length=1000)
    provider_post_id: str | None = Field(default=None, max_length=180)

    @field_validator("note")
    @classmethod
    def clean_resolution_note(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("أدخل ملاحظة تحقق واضحة (5 أحرف على الأقل)")
        return value

class SocialAccountCreate(BaseModel):
    platform: Platform
    account_name: str = Field(min_length=1, max_length=160)
    handle: str | None = Field(default=None, max_length=180)

class SocialAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    platform: str
    account_name: str
    handle: str | None
    connection_status: str
    provider_account_id: str | None
    last_synced_at: datetime | None
    created_at: datetime

class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    conversation_id: str
    direction: str
    body: str
    delivery_status: str
    created_at: datetime

class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    channel: str
    contact_id: str | None
    status: str
    last_message_at: datetime | None
    created_at: datetime

class SetupStatusOut(BaseModel):
    setup_required: bool

class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("اسم مساحة العمل قصير جدًا")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("المنطقة الزمنية غير معروفة") from exc
        return value



ShortVideoPlatform = Literal["Facebook", "Instagram", "TikTok", "YouTube", "LinkedIn"]
ShortVideoStatus = Literal["draft", "ready", "archived"]
AspectRatio = Literal["9:16", "4:5", "1:1"]

class ShortVideoDraftBase(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    caption: str = Field(default="", max_length=5000)
    media_asset_id: str | None = None
    target_platforms: list[ShortVideoPlatform] = Field(min_length=1, max_length=5)
    aspect_ratio: AspectRatio = "9:16"
    duration_seconds: int | None = Field(default=None, ge=1, le=600)
    status: ShortVideoStatus = "draft"

    @field_validator("title")
    @classmethod
    def clean_video_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("عنوان الفيديو قصير جدًا")
        return value

    @field_validator("target_platforms")
    @classmethod
    def unique_target_platforms(cls, value: list[str]) -> list[str]:
        if not value or len(set(value)) != len(value):
            raise ValueError("اختر منصة واحدة على الأقل دون تكرار")
        return value

class ShortVideoDraftCreate(ShortVideoDraftBase):
    pass

class ShortVideoDraftUpdate(ShortVideoDraftBase):
    pass

class ShortVideoDraftOut(ShortVideoDraftBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime


# Campaigns
class CampaignBase(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    objective: Literal["awareness", "engagement", "leads", "sales", "traffic", "other"] = "awareness"
    status: Literal["planning", "active", "paused", "completed", "cancelled"] = "planning"
    budget: float = Field(default=0, ge=0, le=1_000_000_000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    notes: str = Field(default="", max_length=10000)

    @model_validator(mode="after")
    def valid_window(self):
        if self.start_at and self.end_at and self.end_at < self.start_at:
            raise ValueError("تاريخ نهاية الحملة يجب ألا يسبق تاريخ بدايتها")
        return self

class CampaignCreate(CampaignBase): pass
class CampaignUpdate(CampaignBase): pass
class CampaignOut(CampaignBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime

class ConversationCreate(BaseModel):
    channel: Platform
    contact_id: str | None = None
    status: Literal["open", "pending", "closed"] = "open"

class ConversationUpdate(BaseModel):
    status: Literal["open", "pending", "closed"]
    contact_id: str | None = None

class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    direction: Literal["inbound", "outbound"] = "outbound"

class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_filename: str
    media_type: str
    size_bytes: int
    created_by: str
    created_at: datetime
    download_url: str
