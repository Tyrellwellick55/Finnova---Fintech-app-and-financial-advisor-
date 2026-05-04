import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import DomainEvent

logger = logging.getLogger(__name__)


Handler = Callable[[DomainEvent], None]


_HANDLERS: Dict[str, List[Handler]] = {}


def subscribe(event_type: str, handler: Handler) -> None:
    """Register a handler for an event type."""
    _HANDLERS.setdefault(event_type, []).append(handler)


def emit(
    event_type: str,
    *,
    actor=None,
    organization=None,
    metadata: Optional[Dict[str, Any]] = None,
    correlation_id=None,
    idempotency_key: Optional[str] = None,
    dispatch: bool = True,
) -> DomainEvent:
    """Create (and optionally dispatch) a DomainEvent.

    If idempotency_key is provided, duplicate emits will return the existing event.
    """

    metadata = metadata or {}

    created_new = True
    try:
        with transaction.atomic():
            ev = DomainEvent.objects.create(
                event_type=event_type,
                actor=actor,
                organization=organization,
                metadata=metadata,
                correlation_id=correlation_id or uuid.uuid4(),
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # Idempotent emit
        ev = DomainEvent.objects.filter(event_type=event_type, idempotency_key=idempotency_key).first()
        if ev is None:
            raise
        created_new = False

    if dispatch and (created_new or not ev.processed):
        dispatch_event(ev)
    return ev


def dispatch_event(event: DomainEvent) -> None:
    """Dispatch event to registered handlers (best effort)."""
    handlers = _HANDLERS.get(event.event_type, [])
    if not handlers:
        event.processed = True
        event.processed_at = timezone.now()
        event.processing_error = None
        event.save(update_fields=['processed', 'processed_at', 'processing_error'])
        return

    errors: List[str] = []
    for handler in handlers:
        try:
            handler(event)
        except Exception as e:
            logger.exception("Event handler failed", extra={"event_type": event.event_type, "event_id": str(event.id)})
            errors.append(f"{handler.__module__}.{getattr(handler, '__name__', 'handler')}: {e}")

    if errors:
        event.processed = False
        event.processed_at = None
        event.processing_error = "\n".join(errors)[:8000]
        event.save(update_fields=['processed', 'processed_at', 'processing_error'])
    else:
        event.processed = True
        event.processed_at = timezone.now()
        event.processing_error = None
        event.save(update_fields=['processed', 'processed_at', 'processing_error'])
