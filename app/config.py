"""Settings loader.

Two rules here, both load-bearing:

1. Nothing in this file invents a value. Where the spec says a value is not
   guessable -- the CAN-SPAM postal address above all -- there is no default,
   and the code that needs it raises rather than proceeding with a placeholder.
2. Sending capacity is either configured or explicitly unknown. It is never
   reported as a number we made up, because the daily sourcing target is
   decided against it.
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    """A required setting is missing or unusable."""


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _int_or_none(raw: str | None) -> int | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"expected an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class SendingCapacity:
    """Section 6 arithmetic, with 'not configured' as a first-class state."""

    domains: list[str] = field(default_factory=list)
    mailboxes_per_domain: int | None = None
    #: Real count, when mailboxes are not split evenly across domains.
    #: Takes precedence over mailboxes_per_domain.
    total_mailboxes: int | None = None
    sends_per_mailbox_day: int | None = None

    @property
    def mailbox_count(self) -> int | None:
        if self.total_mailboxes is not None:
            return self.total_mailboxes
        if self.domains and self.mailboxes_per_domain is not None:
            return len(self.domains) * self.mailboxes_per_domain
        return None

    @property
    def configured(self) -> bool:
        return bool(
            self.domains
            and self.mailbox_count
            and self.sends_per_mailbox_day is not None
        )

    @property
    def emails_per_day(self) -> int | None:
        if not self.configured:
            return None
        return int(self.mailbox_count) * int(self.sends_per_mailbox_day)

    def enrollments_per_day(self, sequence_steps: int) -> int | None:
        """A 4-step sequence consumes 4 emails per lead."""
        if sequence_steps <= 0:
            raise ConfigError("sequence_steps must be positive")
        capacity = self.emails_per_day
        if capacity is None:
            return None
        return capacity // sequence_steps


@dataclass(frozen=True)
class Settings:
    database_url: str
    timezone_ops: str
    timezone_send: str

    company_name: str
    what_we_sell: str

    # Blocks sequence activation when absent. Deliberately has no default.
    physical_address: str | None

    capacity: SendingCapacity
    daily_sourcing_target: int | None

    north_star_metric: str
    auto_launch_campaigns: bool

    apollo_api_key: str | None
    apollo_credit_ceiling_per_run: int

    hubspot_portal_id: str | None
    hubspot_private_app_token: str | None
    hubspot_webhook_secret: str | None

    smartlead_api_key: str | None
    drive_sequence_folder: str | None

    signal_provider: str
    apify_actor_id: str | None

    log_level: str
    environment: str

    def require_physical_address(self) -> str:
        if not self.physical_address:
            raise ConfigError(
                "PHYSICAL_ADDRESS is not set. CAN-SPAM requires a physical "
                "postal address in every email; sequence activation is blocked "
                "until it is configured in .env. It is not guessable -- ask a "
                "human, do not substitute anything."
            )
        return self.physical_address

    def require_apollo_key(self) -> str:
        if not self.apollo_api_key:
            raise ConfigError("APOLLO_API_KEY is not set (needed from Phase 3).")
        return self.apollo_api_key

    def require_hubspot_token(self) -> str:
        if not self.hubspot_private_app_token:
            raise ConfigError(
                "HUBSPOT_PRIVATE_APP_TOKEN is not set (needed from Phase 2). "
                "Create a private app at Settings -> Integrations -> Private "
                "Apps; the token is shown once."
            )
        return self.hubspot_private_app_token

    def require_smartlead_key(self) -> str:
        if not self.smartlead_api_key:
            raise ConfigError("SMARTLEAD_API_KEY is not set (needed from Phase 5).")
        return self.smartlead_api_key


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader; real environment always wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_settings(dotenv: Path | None = None) -> Settings:
    _load_dotenv(dotenv or REPO_ROOT / ".env")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ConfigError("DATABASE_URL is required. See .env.example.")

    signal_provider = os.environ.get("SIGNAL_PROVIDER", "manual").strip()
    if signal_provider not in {"manual", "x_api", "apify"}:
        raise ConfigError(
            f"SIGNAL_PROVIDER={signal_provider!r} is not one of manual, x_api, apify."
        )

    apify_actor_id = os.environ.get("APIFY_ACTOR_ID") or None
    if signal_provider == "apify" and not apify_actor_id:
        # An Apify token alone must never be enough to turn on scraping.
        raise ConfigError(
            "SIGNAL_PROVIDER=apify requires an explicit APIFY_ACTOR_ID. "
            "A token by itself does not enable the provider."
        )

    north_star = os.environ.get("NORTH_STAR_METRIC", "positive_reply_rate").strip()
    if north_star not in {"positive_reply_rate", "reply_rate", "meeting_rate"}:
        raise ConfigError(f"NORTH_STAR_METRIC={north_star!r} is not a known metric.")

    return Settings(
        database_url=database_url,
        timezone_ops=os.environ.get("TIMEZONE_OPS", "Asia/Kolkata"),
        timezone_send=os.environ.get("TIMEZONE_SEND", "America/New_York"),
        company_name=os.environ.get("COMPANY_NAME", "Audria"),
        what_we_sell=os.environ.get(
            "WHAT_WE_SELL",
            "Meeting memory: the commitments made, decisions taken, and context "
            "that evaporates between conversations.",
        ),
        physical_address=os.environ.get("PHYSICAL_ADDRESS") or None,
        capacity=SendingCapacity(
            domains=_split_csv(os.environ.get("SENDING_DOMAINS")),
            mailboxes_per_domain=_int_or_none(os.environ.get("MAILBOXES_PER_DOMAIN")),
            total_mailboxes=_int_or_none(os.environ.get("TOTAL_MAILBOXES")),
            sends_per_mailbox_day=_int_or_none(
                os.environ.get("SENDS_PER_MAILBOX_DAY")
            ),
        ),
        daily_sourcing_target=_int_or_none(os.environ.get("DAILY_SOURCING_TARGET")),
        north_star_metric=north_star,
        auto_launch_campaigns=os.environ.get("AUTO_LAUNCH_CAMPAIGNS", "no").lower()
        in {"1", "true", "yes"},
        apollo_api_key=os.environ.get("APOLLO_API_KEY") or None,
        apollo_credit_ceiling_per_run=int(
            os.environ.get("APOLLO_CREDIT_CEILING_PER_RUN", "200")
        ),
        hubspot_portal_id=os.environ.get("HUBSPOT_PORTAL_ID") or None,
        hubspot_private_app_token=os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN") or None,
        hubspot_webhook_secret=os.environ.get("HUBSPOT_WEBHOOK_SECRET") or None,
        smartlead_api_key=os.environ.get("SMARTLEAD_API_KEY") or None,
        drive_sequence_folder=os.environ.get("DRIVE_SEQUENCE_FOLDER") or None,
        signal_provider=signal_provider,
        apify_actor_id=apify_actor_id,
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        environment=os.environ.get("ENVIRONMENT", "development"),
    )


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
