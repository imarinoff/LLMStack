from functools import cache

from rest_framework import serializers

from llmstack.apps.app_types import AppTypeFactory
from llmstack.apps.yaml_loader import get_app_template_by_slug
from llmstack.assets.apis import AssetViewSet
from llmstack.base.models import Profile
from llmstack.processors.models import ApiBackend, Endpoint
from llmstack.processors.serializers import ApiProviderSerializer

from .models import App, AppAccessPermission, AppData, AppTemplate, AppTemplateCategory


class DynamicFieldsModelSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        # Don't pass the 'fields' arg up to the superclass
        fields = kwargs.pop("fields", None)
        self._request_user = kwargs.pop("request_user", None)

        # Instantiate the superclass normally
        super().__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)


@cache
def get_app_type_serializer(app_type_slug: str):
    app_type_handler_cls = AppTypeFactory.get_app_type_handler(app_type_slug)
    if app_type_handler_cls is None:
        return None

    return {
        "name": app_type_handler_cls.name(),
        "slug": app_type_handler_cls.slug(),
        "description": app_type_handler_cls.description(),
        "config_schema": app_type_handler_cls.get_config_schema(),
        "config_ui_schema": app_type_handler_cls.get_config_ui_schema(),
    }


class AppSerializer(DynamicFieldsModelSerializer):
    class AppProcessorEndpointSerializer(serializers.ModelSerializer):
        class AppProcessorEndpointApiBackendSerializer(
            serializers.ModelSerializer,
        ):
            api_provider = ApiProviderSerializer()

            class Meta:
                model = ApiBackend
                fields = ["id", "name", "api_provider"]

        api_backend = AppProcessorEndpointApiBackendSerializer()

        class Meta:
            model = Endpoint
            fields = ["name", "uuid", "api_backend", "description"]

    class AppTemplateSerializer(serializers.ModelSerializer):
        class Meta:
            model = AppTemplate
            fields = ["name", "slug"]

    type = serializers.SerializerMethodField()
    data = serializers.SerializerMethodField()
    processors = serializers.SerializerMethodField()
    unique_processors = serializers.SerializerMethodField()
    logo = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    icon = serializers.SerializerMethodField()
    is_shareable = serializers.SerializerMethodField()
    has_footer = serializers.SerializerMethodField()
    last_modified_by_email = serializers.SerializerMethodField()
    owner_email = serializers.SerializerMethodField()
    app_type_name = serializers.SerializerMethodField()
    app_type_slug = serializers.SerializerMethodField()
    discord_config = serializers.SerializerMethodField()
    slack_config = serializers.SerializerMethodField()
    twilio_config = serializers.SerializerMethodField()
    web_config = serializers.SerializerMethodField()
    access_permission = serializers.SerializerMethodField()
    read_accessible_by = serializers.SerializerMethodField()
    write_accessible_by = serializers.SerializerMethodField()
    last_modified_by_email = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    visibility = serializers.SerializerMethodField()
    has_live_version = serializers.SerializerMethodField()

    def get_logo(self, obj):
        profile = Profile.objects.get(user=obj.owner)
        return profile.logo if (profile.is_pro_subscriber() or profile.organization) else None

    def get_is_shareable(self, obj):
        profile = Profile.objects.get(user=obj.owner)
        return not profile.organization

    def get_has_footer(self, obj):
        profile = Profile.objects.get(user=obj.owner)
        return not profile.organization

    def get_last_modified_by_email(self, obj):
        return (
            obj.last_modified_by.email
            if obj.last_modified_by
            and obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_owner_email(self, obj):
        return (
            obj.owner.email
            if obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_data(self, obj):
        app_data = (
            AppData.objects.filter(
                app_uuid=obj.uuid,
            )
            .order_by("-created_at")
            .first()
        )
        if app_data and app_data.data:
            if not obj.has_write_permission(self._request_user):
                app_data.data.pop("processors", None)

            if "config" in app_data.data and "assistant_image" in app_data.data["config"]:
                asset_data = AssetViewSet().get_asset_data(
                    objref=app_data.data["config"]["assistant_image"],
                    request_user=self._request_user,
                )
                if asset_data and "url" in asset_data:
                    app_data.data["config"]["assistant_image"] = asset_data["url"]
            return {**app_data.data, "version": app_data.version}
        return None

    def get_has_live_version(self, obj):
        app_datas = AppData.objects.filter(
            app_uuid=obj.uuid,
            is_draft=False,
        ).first()
        return app_datas is not None

    def get_app_type_name(self, obj):
        return get_app_type_serializer(obj.type.slug if obj.type else obj.type_slug).get("name")

    def get_app_type_slug(self, obj):
        return obj.type.slug if obj.type else obj.type_slug

    def get_type(self, obj):
        return get_app_type_serializer(obj.type.slug if obj.type else obj.type_slug)

    def get_processors(self, obj):
        return []

    def get_unique_processors(self, obj):
        if obj.has_write_permission(self._request_user):
            data = self.get_data(obj)
            processors = data.get("processors", []) if data else []
            unique_processors = []
            for processor in processors:
                if "provider_slug" in processor and "processor_slug" in processor:
                    name = f"{processor['provider_slug']} / {processor['processor_slug']}"
                    if name not in unique_processors:
                        unique_processors.append(name)
            return unique_processors

        return []

    def get_discord_config(self, obj):
        return (
            obj.discord_config
            if obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_slack_config(self, obj):
        return (
            obj.slack_config
            if obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_twilio_config(self, obj):
        return (
            obj.twilio_config
            if obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_read_accessible_by(self, obj):
        return (
            obj.read_accessible_by
            if obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_write_accessible_by(self, obj):
        return (
            obj.write_accessible_by
            if obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_template(self, obj):
        if obj.template_slug is not None:
            app_template = get_app_template_by_slug(obj.template_slug)
            if app_template:
                return app_template.model_dump(exclude_none=True)
        return None

    def get_web_config(self, obj):
        return (
            obj.web_config
            if obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_visibility(self, obj):
        return (
            obj.visibility
            if obj.has_write_permission(
                self._request_user,
            )
            else None
        )

    def get_icon(self, obj):
        app_data = self.get_data(obj)

        if app_data and "icon" in app_data:
            return app_data["icon"]
        elif app_data and "config" in app_data and "assistant_image" in app_data["config"]:
            asset_data = AssetViewSet().get_asset_data(
                objref=app_data["config"]["assistant_image"],
                request_user=self._request_user,
            )
            if asset_data and "url" in asset_data:
                return asset_data["url"]

        return None

    def get_description(self, obj):
        app_data = self.get_data(obj)
        return app_data.get("description", obj.description)

    def get_access_permission(self, obj):
        return AppAccessPermission.WRITE if obj.has_write_permission(self._request_user) else AppAccessPermission.READ

    class Meta:
        model = App
        fields = [
            "name",
            "description",
            "data",
            "type",
            "uuid",
            "published_uuid",
            "store_uuid",
            "is_published",
            "unique_processors",
            "created_at",
            "last_updated_at",
            "logo",
            "icon",
            "is_shareable",
            "has_footer",
            "domain",
            "visibility",
            "last_modified_by_email",
            "owner_email",
            "web_config",
            "slack_config",
            "discord_config",
            "twilio_config",
            "app_type_name",
            "processors",
            "template",
            "app_type_slug",
            "read_accessible_by",
            "write_accessible_by",
            "has_live_version",
            "access_permission",
        ]


class AppTemplateCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AppTemplateCategory
        fields = ["name", "slug"]


class AppDataSerializer(serializers.ModelSerializer):
    data = serializers.SerializerMethodField()

    def get_data(self, obj):
        hide_details = self.context.get("hide_details", True)
        if hide_details:
            return None

        return obj.data

    class Meta:
        model = AppData
        fields = [
            "version",
            "app_uuid",
            "data",
            "created_at",
            "last_updated_at",
            "is_draft",
            "comment",
        ]


class AppAsStoreAppSerializer(DynamicFieldsModelSerializer):
    """
    Takes an App object and serializes it as an app store entry.
    """

    version = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    categories = serializers.SerializerMethodField()
    data = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    icon = serializers.SerializerMethodField()
    icon128 = serializers.SerializerMethodField()
    icon512 = serializers.SerializerMethodField()

    @cache
    def get_data(self, obj):
        include_processors = self.context.get("include_processors", False)
        include_config = self.context.get("include_config", False)
        app_data_obj = (
            AppData.objects.filter(
                app_uuid=obj.uuid,
            )
            .order_by("-created_at")
            .first()
        )
        app_data = app_data_obj.data if app_data_obj else None
        if app_data:
            app_data["version"] = str(app_data_obj.version)

        if app_data and not include_processors:
            app_data.pop("processors", None)

        if app_data and not include_config:
            app_data.pop("config", None)

        return app_data

    def get_username(self, obj):
        return obj.owner.username or obj.owner.email

    def get_slug(self, obj):
        return str(obj.uuid)

    def get_categories(self, obj):
        return []

    def get_icon(self, obj):
        app_data = self.get_data(obj)

        if app_data and "icon" in app_data:
            return app_data["icon"]
        elif app_data and "config" in app_data and "assistant_image" in app_data["config"]:
            asset_data = AssetViewSet().get_asset_data(
                objref=app_data["config"]["assistant_image"],
                request_user=self._request_user,
            )
            if asset_data and "url" in asset_data:
                return asset_data["url"]

        return None

    def get_icon128(self, obj):
        return self.get_icon(obj)

    def get_icon512(self, obj):
        return self.get_icon(obj)

    def get_version(self, obj):
        return self.get_data(obj).get("version", "")

    def get_description(self, obj):
        return self.get_data(obj).get("description", "")

    class Meta:
        model = App
        fields = [
            "uuid",
            "username",
            "version",
            "name",
            "slug",
            "description",
            "categories",
            "data",
            "created_at",
            "icon",
            "icon128",
            "icon512",
        ]
