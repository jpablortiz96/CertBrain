"""CertBrain — Engagement Agent.

Generates personalised reminder and celebration messages, adapts tone
based on student progress, and schedules delivery via the email sender
integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from config import get_settings, get_logger
from integrations.azure_ai import AzureAIClient
from integrations.email_sender import EmailMessage, EmailSender
from models.student import StudentProfile, StudySession, SessionStatus

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
class ReminderType(str, Enum):
    """Categories of engagement messages."""

    REMINDER = "reminder"
    CELEBRATION = "celebration"
    URGENCY = "urgency"
    ENCOURAGEMENT = "encouragement"


@dataclass
class ScheduledReminder:
    """A reminder scheduled for delivery."""

    scheduled_at: datetime
    message: str
    subject: str
    reminder_type: ReminderType
    sent: bool = False


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are an Engagement Coach for a student preparing for a Microsoft \
certification exam.

## Your role
Generate a SHORT, personalised message for the student based on their \
current progress. Adapt your tone:

- **Motivational** (on track): upbeat, brief praise, encourage to keep going.
- **Empathetic** (falling behind): understanding, normalise setbacks, offer \
a small actionable step.
- **Urgent** (exam approaching): direct, focused, highlight what to prioritise.
- **Celebration** (milestone reached): enthusiastic congratulations, state \
the achievement clearly.

## Output format — strict JSON, no markdown fences
{{
  "subject": "<email subject line, max 60 chars>",
  "message": "<the message body, 2-4 sentences>",
  "reminder_type": "reminder|celebration|urgency|encouragement"
}}

## Rules
- Keep messages under 100 words.
- Mention the student's name.
- Reference specific topics or milestones when possible.
- Never be condescending.
"""


# ---------------------------------------------------------------------------
# Engagement Agent
# ---------------------------------------------------------------------------
class EngagementAgent:
    """Generates and optionally sends personalised engagement messages.

    Parameters
    ----------
    student:
        Student profile.
    study_sessions:
        The full study plan.
    """

    def __init__(
        self,
        student: StudentProfile,
        study_sessions: list[StudySession],
    ) -> None:
        self._student = student
        self._sessions = study_sessions
        self._settings = get_settings()
        self._email_sender = EmailSender()

    # ------------------------------------------------------------------
    # Progress analysis
    # ------------------------------------------------------------------
    def _analyse_progress(self) -> dict[str, Any]:
        """Compute progress metrics for prompt context."""
        total = len(self._sessions)
        completed = sum(
            1 for s in self._sessions if s.status == SessionStatus.COMPLETED
        )
        skipped = sum(
            1 for s in self._sessions if s.status == SessionStatus.SKIPPED
        )
        pending = total - completed - skipped
        completion_rate = completed / total if total else 0.0

        # Days until next session
        now = datetime.utcnow().date()
        upcoming = [
            s for s in self._sessions
            if s.status == SessionStatus.SCHEDULED and s.scheduled_date >= now
        ]
        upcoming.sort(key=lambda s: s.scheduled_date)
        next_session_days = (
            (upcoming[0].scheduled_date - now).days if upcoming else None
        )

        return {
            "total_sessions": total,
            "completed": completed,
            "skipped": skipped,
            "pending": pending,
            "completion_rate": completion_rate,
            "overall_mastery": self._student.overall_mastery,
            "next_session_in_days": next_session_days,
            "next_topic": upcoming[0].objective_id if upcoming else None,
        }

    def _determine_tone(self, progress: dict[str, Any]) -> str:
        """Choose the appropriate tone based on progress metrics."""
        rate = progress["completion_rate"]
        mastery = progress["overall_mastery"]
        next_days = progress["next_session_in_days"]

        if rate >= 0.8 and mastery >= 0.7:
            return "celebration"
        if next_days is not None and next_days <= 2:
            return "urgency"
        if rate < 0.5 or progress["skipped"] > progress["completed"]:
            return "encouragement"
        return "motivational"

    # ------------------------------------------------------------------
    # LLM message generation
    # ------------------------------------------------------------------
    async def _generate_message(
        self,
        azure_client: AzureAIClient,
        progress: dict[str, Any],
        tone: str,
    ) -> dict[str, Any]:
        """Ask the LLM to generate a personalised message."""
        user_msg = (
            f"Student name: {self._student.name}\n"
            f"Certification: {self._student.certification_uid}\n"
            f"Overall mastery: {progress['overall_mastery']:.0%}\n"
            f"Sessions completed: {progress['completed']}/{progress['total_sessions']}\n"
            f"Sessions skipped: {progress['skipped']}\n"
            f"Completion rate: {progress['completion_rate']:.0%}\n"
            f"Next session in: {progress['next_session_in_days']} days\n"
            f"Next topic: {progress['next_topic']}\n"
            f"Desired tone: {tone}\n\n"
            "Generate a personalised engagement message."
        )

        try:
            return await azure_client.chat_completion_json(
                SYSTEM_PROMPT, user_msg, temperature=0.7, max_tokens=300
            )
        except Exception as exc:
            logger.warning("LLM message generation failed: %s", exc)
            return {
                "subject": f"CertBrain: Keep going, {self._student.name}!",
                "message": (
                    f"Hi {self._student.name}, you've completed "
                    f"{progress['completed']} sessions so far. Keep it up!"
                ),
                "reminder_type": "reminder",
            }

    # ------------------------------------------------------------------
    # Schedule generation
    # ------------------------------------------------------------------
    def _build_reminder_schedule(
        self,
    ) -> list[datetime]:
        """Generate reminder timestamps based on the study plan."""
        now = datetime.utcnow()
        schedule: list[datetime] = []

        for session in self._sessions:
            if session.status != SessionStatus.SCHEDULED:
                continue
            # Remind 1 day before and 1 hour before
            session_dt = datetime.combine(session.scheduled_date, datetime.min.time())
            day_before = session_dt - timedelta(days=1)
            hour_before = session_dt - timedelta(hours=1)
            if day_before > now:
                schedule.append(day_before)
            if hour_before > now:
                schedule.append(hour_before)

        schedule.sort()
        return schedule

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(self, send_emails: bool = False) -> list[ScheduledReminder]:
        """Generate engagement messages and optionally send them.

        Parameters
        ----------
        send_emails:
            If *True*, immediately send all generated messages via the
            email sender integration.

        Returns
        -------
        list[ScheduledReminder]
        """
        logger.info("Engagement Agent starting for student=%s", self._student.name)

        progress = self._analyse_progress()
        tone = self._determine_tone(progress)
        logger.info("Tone selected: %s (rate=%.0f%% mastery=%.0f%%)",
                     tone, progress["completion_rate"] * 100,
                     progress["overall_mastery"] * 100)

        reminders: list[ScheduledReminder] = []
        azure_client = AzureAIClient()

        try:
            reminder_times = self._build_reminder_schedule()
            immediate_data = await self._generate_message(azure_client, progress, tone)

            try:
                rtype = ReminderType(immediate_data.get("reminder_type", "reminder"))
            except ValueError:
                rtype = ReminderType.REMINDER

            immediate = ScheduledReminder(
                scheduled_at=datetime.utcnow(),
                message=immediate_data.get("message", ""),
                subject=immediate_data.get("subject", "CertBrain Reminder"),
                reminder_type=rtype,
            )
            reminders.append(immediate)

            for rt in reminder_times[:10]:
                msg_data = await self._generate_message(azure_client, progress, tone)
                try:
                    rt_type = ReminderType(msg_data.get("reminder_type", "reminder"))
                except ValueError:
                    rt_type = ReminderType.REMINDER
                reminders.append(ScheduledReminder(
                    scheduled_at=rt,
                    message=msg_data.get("message", ""),
                    subject=msg_data.get("subject", "CertBrain Reminder"),
                    reminder_type=rt_type,
                ))
        finally:
            await azure_client.close()

        # Optionally send immediate message
        if send_emails and self._student.email:
            email = EmailMessage(
                to=self._student.email,
                subject=immediate.subject,
                body=immediate.message,
            )
            sent = await self._email_sender.send(email)
            immediate.sent = sent

        logger.info(
            "Engagement Agent done: %d reminders generated, immediate sent=%s",
            len(reminders), immediate.sent if send_emails else "skipped",
        )
        return reminders
