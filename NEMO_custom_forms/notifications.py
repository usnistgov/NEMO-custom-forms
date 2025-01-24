from datetime import timedelta

from NEMO.models import Notification
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from NEMO_custom_forms.models import CustomForm
from NEMO_custom_forms.utilities import CUSTOM_FORM_NOTIFICATION


def create_custom_form_notification(custom_form: CustomForm):
    users_to_notify = set(custom_form.next_action_candidates())
    if custom_form.status not in CustomForm.FormStatus.finished():
        users_to_notify.add(custom_form.creator)
    expiration = timezone.now() + timedelta(days=30)  # 30 days for custom form action to expire
    for user in users_to_notify:
        # Only update users other than the one who last updated it
        if not custom_form.last_updated_by or custom_form.last_updated_by != user:
            Notification.objects.get_or_create(
                user=user,
                notification_type=CUSTOM_FORM_NOTIFICATION,
                content_type=ContentType.objects.get_for_model(custom_form),
                object_id=custom_form.id,
                defaults={"expiration": expiration},
            )
