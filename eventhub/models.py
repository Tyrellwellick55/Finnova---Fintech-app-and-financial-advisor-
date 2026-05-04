import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class DomainEvent(models.Model):
    """A persisted domain event.

    This is the system-of-record for cross-module side effects.
    Handlers should be written to be idempotent.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event_type = models.CharField(max_length=80, db_index=True)

    # Optional categorization for richer activity feeds/incident correlation
    module = models.CharField(max_length=80, null=True, blank=True)
    severity = models.CharField(max_length=20, null=True, blank=True)
    action_url = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    organization = models.ForeignKey(
        'finnovaapp.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='domain_events',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='domain_events',
    )

    correlation_id = models.UUIDField(default=uuid.uuid4, db_index=True)

    # Optional key to prevent duplicate event emission
    idempotency_key = models.CharField(max_length=120, null=True, blank=True, db_index=True)

    metadata = models.JSONField(default=dict, blank=True)

    processed = models.BooleanField(default=False, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['event_type', 'idempotency_key'],
                condition=Q(idempotency_key__isnull=False),
                name='uniq_eventhub_type_idempotency_key',
            )
        ]

    def __str__(self):
        return f"{self.event_type} ({self.id})"
