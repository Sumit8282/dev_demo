"""QA sign-off validation service abstraction."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class QAService(ABC):
    @abstractmethod
    def is_signoff_completed(
        self,
        *,
        release_id: str,
        environment: str,
        release_version: str,
    ) -> bool:
        """Return True when QA sign-off is completed for the release."""


class DevelopmentQAService(QAService):
    """Development-only QA source controlled by QA_DEV_SIGNOFF_STATUS."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._status = self.settings.qa_dev_signoff_status.strip().lower()

    def is_signoff_completed(
        self,
        *,
        release_id: str,
        environment: str,
        release_version: str,
    ) -> bool:
        if self._status == "completed":
            logger.info(
                "[QA_SERVICE] Development override: sign-off completed for %s",
                release_id,
            )
            return True
        if self._status == "missing":
            logger.info(
                "[QA_SERVICE] Development override: sign-off missing for %s",
                release_id,
            )
            return False
        # Default development behavior: sign-off missing when required
        return False


class ProductionQAService(QAService):
    """Placeholder for future real QA/sign-off integration."""

    def is_signoff_completed(
        self,
        *,
        release_id: str,
        environment: str,
        release_version: str,
    ) -> bool:
        # Replace with real QA system lookup (ServiceNow, DB, API, etc.)
        logger.warning(
            "[QA_SERVICE] Production QA source not configured; treating sign-off as missing "
            "for release %s",
            release_id,
        )
        return False


def get_qa_service(settings: Settings | None = None) -> QAService:
    settings = settings or get_settings()
    if settings.is_development:
        return DevelopmentQAService(settings)
    return ProductionQAService()
