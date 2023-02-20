"""Provides a JSON API for common components."""

import json

from django.http.response import HttpResponse
from django.urls import include, path, re_path
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from django_filters.rest_framework import DjangoFilterBackend
from django_q.tasks import async_task
from djmoney.contrib.exchange.models import ExchangeBackend, Rate
from rest_framework import filters, permissions, serializers
from rest_framework.exceptions import NotAcceptable, NotFound
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

import common.models
import common.serializers
from InvenTree.api import BulkDeleteMixin
from InvenTree.config import CONFIG_LOOKUPS
from InvenTree.helpers import inheritors
from InvenTree.mixins import (ListAPI, RetrieveAPI, RetrieveUpdateAPI,
                              RetrieveUpdateDestroyAPI)
from InvenTree.permissions import IsSuperuser
from plugin.models import NotificationUserSetting
from plugin.serializers import NotificationUserSettingSerializer


class CsrfExemptMixin(object):
    """Exempts the view from CSRF requirements."""

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        """Overwrites dispatch to be extempt from csrf checks."""
        return super().dispatch(*args, **kwargs)


class WebhookView(CsrfExemptMixin, APIView):
    """Endpoint for receiving webhooks."""
    authentication_classes = []
    permission_classes = []
    model_class = common.models.WebhookEndpoint
    run_async = False

    def post(self, request, endpoint, *args, **kwargs):
        """Process incomming webhook."""
        # get webhook definition
        self._get_webhook(endpoint, request, *args, **kwargs)

        # check headers
        headers = request.headers
        try:
            payload = json.loads(request.body)
        except json.decoder.JSONDecodeError as error:
            raise NotAcceptable(error.msg)

        # validate
        self.webhook.validate_token(payload, headers, request)
        # process data
        message = self.webhook.save_data(payload, headers, request)
        if self.run_async:
            async_task(self._process_payload, message.id)
        else:
            self._process_result(
                self.webhook.process_payload(message, payload, headers),
                message,
            )

        data = self.webhook.get_return(payload, headers, request)
        return HttpResponse(data)

    def _process_payload(self, message_id):
        message = common.models.WebhookMessage.objects.get(message_id=message_id)
        self._process_result(
            self.webhook.process_payload(message, message.body, message.header),
            message,
        )

    def _process_result(self, result, message):
        if result:
            message.worked_on = result
            message.save()
        else:
            message.delete()

    def _escalate_object(self, obj):
        classes = inheritors(obj.__class__)
        for cls in classes:
            mdl_name = cls._meta.model_name
            if hasattr(obj, mdl_name):
                return getattr(obj, mdl_name)
        return obj

    def _get_webhook(self, endpoint, request, *args, **kwargs):
        try:
            webhook = self.model_class.objects.get(endpoint_id=endpoint)
            self.webhook = self._escalate_object(webhook)
            self.webhook.init(request, *args, **kwargs)
            return self.webhook.process_webhook()
        except self.model_class.DoesNotExist:
            raise NotFound()


class CurrencyExchangeView(APIView):
    """API endpoint for displaying currency information"""

    permission_classes = [
        permissions.IsAuthenticated,
    ]

    def get(self, request, format=None):
        """Return information on available currency conversions"""

        # Extract a list of all available rates
        try:
            rates = Rate.objects.all()
        except Exception:
            rates = []

        # Information on last update
        try:
            backend = ExchangeBackend.objects.get(name='InvenTreeExchange')
            updated = backend.last_update
        except Exception:
            updated = None

        response = {
            'base_currency': common.models.InvenTreeSetting.get_setting('INVENTREE_DEFAULT_CURRENCY', 'USD'),
            'exchange_rates': {},
            'updated': updated,
        }

        for rate in rates:
            response['exchange_rates'][rate.currency] = rate.value

        return Response(response)


class CurrencyRefreshView(APIView):
    """API endpoint for manually refreshing currency exchange rates.

    User must be a 'staff' user to access this endpoint
    """

    permission_classes = [
        permissions.IsAuthenticated,
        permissions.IsAdminUser,
    ]

    def post(self, request, *args, **kwargs):
        """Performing a POST request will update currency exchange rates"""

        from InvenTree.tasks import update_exchange_rates

        update_exchange_rates()

        return Response({
            'success': 'Exchange rates updated',
        })


class SettingsList(ListAPI):
    """Generic ListView for settings.

    This is inheritted by all list views for settings.
    """

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    ordering_fields = [
        'pk',
        'key',
        'name',
    ]

    search_fields = [
        'key',
    ]


class GlobalSettingsList(SettingsList):
    """API endpoint for accessing a list of global settings objects."""

    queryset = common.models.InvenTreeSetting.objects.all()
    serializer_class = common.serializers.GlobalSettingsSerializer


class GlobalSettingsPermissions(permissions.BasePermission):
    """Special permission class to determine if the user is "staff"."""

    def has_permission(self, request, view):
        """Check that the requesting user is 'admin'."""
        try:
            user = request.user

            if request.method in ['GET', 'HEAD', 'OPTIONS']:
                return True
            else:
                # Any other methods require staff access permissions
                return user.is_staff

        except AttributeError:  # pragma: no cover
            return False


class GlobalSettingsDetail(RetrieveUpdateAPI):
    """Detail view for an individual "global setting" object.

    - User must have 'staff' status to view / edit
    """

    lookup_field = 'key'
    queryset = common.models.InvenTreeSetting.objects.all()
    serializer_class = common.serializers.GlobalSettingsSerializer

    def get_object(self):
        """Attempt to find a global setting object with the provided key."""
        key = self.kwargs['key']

        if key not in common.models.InvenTreeSetting.SETTINGS.keys():
            raise NotFound()

        return common.models.InvenTreeSetting.get_setting_object(key)

    permission_classes = [
        permissions.IsAuthenticated,
        GlobalSettingsPermissions,
    ]


class UserSettingsList(SettingsList):
    """API endpoint for accessing a list of user settings objects."""

    queryset = common.models.InvenTreeUserSetting.objects.all()
    serializer_class = common.serializers.UserSettingsSerializer

    def filter_queryset(self, queryset):
        """Only list settings which apply to the current user."""
        try:
            user = self.request.user
        except AttributeError:  # pragma: no cover
            return common.models.InvenTreeUserSetting.objects.none()

        queryset = super().filter_queryset(queryset)

        queryset = queryset.filter(user=user)

        return queryset


class UserSettingsPermissions(permissions.BasePermission):
    """Special permission class to determine if the user can view / edit a particular setting."""

    def has_object_permission(self, request, view, obj):
        """Check if the user that requested is also the object owner."""
        try:
            user = request.user
        except AttributeError:  # pragma: no cover
            return False

        return user == obj.user


class UserSettingsDetail(RetrieveUpdateAPI):
    """Detail view for an individual "user setting" object.

    - User can only view / edit settings their own settings objects
    """

    lookup_field = 'key'
    queryset = common.models.InvenTreeUserSetting.objects.all()
    serializer_class = common.serializers.UserSettingsSerializer

    def get_object(self):
        """Attempt to find a user setting object with the provided key."""
        key = self.kwargs['key']

        if key not in common.models.InvenTreeUserSetting.SETTINGS.keys():
            raise NotFound()

        return common.models.InvenTreeUserSetting.get_setting_object(key, user=self.request.user)

    permission_classes = [
        UserSettingsPermissions,
    ]


class NotificationUserSettingsList(SettingsList):
    """API endpoint for accessing a list of notification user settings objects."""

    queryset = NotificationUserSetting.objects.all()
    serializer_class = NotificationUserSettingSerializer

    def filter_queryset(self, queryset):
        """Only list settings which apply to the current user."""
        try:
            user = self.request.user
        except AttributeError:
            return NotificationUserSetting.objects.none()

        queryset = super().filter_queryset(queryset)
        queryset = queryset.filter(user=user)
        return queryset


class NotificationUserSettingsDetail(RetrieveUpdateAPI):
    """Detail view for an individual "notification user setting" object.

    - User can only view / edit settings their own settings objects
    """

    queryset = NotificationUserSetting.objects.all()
    serializer_class = NotificationUserSettingSerializer
    permission_classes = [UserSettingsPermissions, ]


class NotificationMessageMixin:
    """Generic mixin for NotificationMessage."""
    queryset = common.models.NotificationMessage.objects.all()
    serializer_class = common.serializers.NotificationMessageSerializer
    permission_classes = [UserSettingsPermissions, ]


class NotificationList(NotificationMessageMixin, BulkDeleteMixin, ListAPI):
    """List view for all notifications of the current user."""

    permission_classes = [permissions.IsAuthenticated, ]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    ordering_fields = [
        'category',
        'name',
        'read',
        'creation',
    ]

    search_fields = [
        'name',
        'message',
    ]

    filterset_fields = [
        'category',
        'read',
    ]

    def filter_queryset(self, queryset):
        """Only list notifications which apply to the current user."""
        try:
            user = self.request.user
        except AttributeError:
            return common.models.NotificationMessage.objects.none()

        queryset = super().filter_queryset(queryset)
        queryset = queryset.filter(user=user)
        return queryset

    def filter_delete_queryset(self, queryset, request):
        """Ensure that the user can only delete their *own* notifications"""

        queryset = queryset.filter(user=request.user)
        return queryset


class NotificationDetail(NotificationMessageMixin, RetrieveUpdateDestroyAPI):
    """Detail view for an individual notification object.

    - User can only view / delete their own notification objects
    """


class NotificationReadAll(NotificationMessageMixin, RetrieveAPI):
    """API endpoint to mark all notifications as read."""

    def get(self, request, *args, **kwargs):
        """Set all messages for the current user as read."""
        try:
            self.queryset.filter(user=request.user, read=False).update(read=True)
            return Response({'status': 'ok'})
        except Exception as exc:
            raise serializers.ValidationError(detail=serializers.as_serializer_error(exc))


class NewsFeedMixin:
    """Generic mixin for NewsFeedEntry."""
    queryset = common.models.NewsFeedEntry.objects.all()
    serializer_class = common.serializers.NewsFeedEntrySerializer
    permission_classes = [IsAdminUser, ]


class NewsFeedEntryList(NewsFeedMixin, BulkDeleteMixin, ListAPI):
    """List view for all news items."""
    filter_backends = [
        DjangoFilterBackend,
        filters.OrderingFilter,
    ]

    ordering_fields = [
        'published',
        'author',
        'read',
    ]

    filterset_fields = [
        'read',
    ]


class NewsFeedEntryDetail(NewsFeedMixin, RetrieveUpdateDestroyAPI):
    """Detail view for an individual news feed object."""


class ConfigList(ListAPI):
    """List view for all accessed configurations."""

    queryset = CONFIG_LOOKUPS
    serializer_class = common.serializers.ConfigSerializer
    permission_classes = [IsSuperuser, ]


class ConfigDetail(RetrieveAPI):
    """Detail view for an individual configuration."""

    serializer_class = common.serializers.ConfigSerializer
    permission_classes = [IsSuperuser, ]

    def get_object(self):
        """Attempt to find a config object with the provided key."""
        key = self.kwargs['key']
        value = CONFIG_LOOKUPS.get(key, None)
        if not value:
            raise NotFound()
        return {key: value}


settings_api_urls = [
    # User settings
    re_path(r'^user/', include([
        # User Settings Detail
        re_path(r'^(?P<key>\w+)/', UserSettingsDetail.as_view(), name='api-user-setting-detail'),

        # User Settings List
        re_path(r'^.*$', UserSettingsList.as_view(), name='api-user-setting-list'),
    ])),

    # Notification settings
    re_path(r'^notification/', include([
        # Notification Settings Detail
        re_path(r'^(?P<pk>\d+)/', NotificationUserSettingsDetail.as_view(), name='api-notification-setting-detail'),

        # Notification Settings List
        re_path(r'^.*$', NotificationUserSettingsList.as_view(), name='api-notifcation-setting-list'),
    ])),

    # Global settings
    re_path(r'^global/', include([
        # Global Settings Detail
        re_path(r'^(?P<key>\w+)/', GlobalSettingsDetail.as_view(), name='api-global-setting-detail'),

        # Global Settings List
        re_path(r'^.*$', GlobalSettingsList.as_view(), name='api-global-setting-list'),
    ])),
]

common_api_urls = [
    # Webhooks
    path('webhook/<slug:endpoint>/', WebhookView.as_view(), name='api-webhook'),

    # Currencies
    re_path(r'^currency/', include([
        re_path(r'^exchange/', CurrencyExchangeView.as_view(), name='api-currency-exchange'),
        re_path(r'^refresh/', CurrencyRefreshView.as_view(), name='api-currency-refresh'),
    ])),

    # Notifications
    re_path(r'^notifications/', include([
        # Individual purchase order detail URLs
        re_path(r'^(?P<pk>\d+)/', include([
            re_path(r'.*$', NotificationDetail.as_view(), name='api-notifications-detail'),
        ])),
        # Read all
        re_path(r'^readall/', NotificationReadAll.as_view(), name='api-notifications-readall'),

        # Notification messages list
        re_path(r'^.*$', NotificationList.as_view(), name='api-notifications-list'),
    ])),

    # News
    re_path(r'^news/', include([
        re_path(r'^(?P<pk>\d+)/', include([
            re_path(r'.*$', NewsFeedEntryDetail.as_view(), name='api-news-detail'),
        ])),
        re_path(r'^.*$', NewsFeedEntryList.as_view(), name='api-news-list'),
    ])),

]

admin_api_urls = [
    # Admin
    path('config/', ConfigList.as_view(), name='api-config-list'),
    path('config/<str:key>/', ConfigDetail.as_view(), name='api-config-detail'),
]
