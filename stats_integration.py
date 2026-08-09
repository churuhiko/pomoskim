import calendar
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

LOGGER = logging.getLogger("PomodoroOverlay")
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"

try:
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:  # pragma: no cover - integration remains optional
    AuthorizedSession = None
    Request = None
    Credentials = None
    InstalledAppFlow = None


def today_text():
    return date.today().isoformat()


COUNTER_KEYS = (
    "pomodoro_completed",
    "short_break_completed",
    "cheat_pomodoro_completed",
    "cheat_short_break_completed",
)
MAX_COUNTER_VALUE = 1_000_000_000
MAX_PENDING_REPORTS = 1_000


def _empty_counters():
    return {key: 0 for key in COUNTER_KEYS}


def default_today(current_date=None):
    return {
        "date": current_date or today_text(),
        **_empty_counters(),
    }


def default_month(current_date=None):
    value = date.fromisoformat(current_date or today_text())
    return {
        "year": value.year,
        "month": value.month,
        **_empty_counters(),
    }


def default_year(current_date=None):
    value = date.fromisoformat(current_date or today_text())
    return {"year": value.year, **_empty_counters()}


def default_stats_state(current_date=None):
    current_date = current_date or today_text()
    return {
        "schema_version": 1,
        "last_activity_date": current_date,
        "today": default_today(current_date),
        "current_month": default_month(current_date),
        "current_year": default_year(current_date),
        "pending_reports": [],
    }


def _nonnegative_int(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return 0
    return min(value, MAX_COUNTER_VALUE)


class StatisticsManager:
    def __init__(self, settings, current_date=None):
        self.settings = settings
        self.long_inactivity_reset = False
        self._new_reports = []
        current_date = current_date or today_text()
        self.normalize(current_date)
        self.rollover(current_date)

    def normalize(self, current_date):
        raw_integration = self.settings.get("integration")
        integration = {
            "google_calendar_enabled": False,
            "google_calendar_account": None,
        }
        if isinstance(raw_integration, dict):
            integration["google_calendar_enabled"] = (
                raw_integration.get("google_calendar_enabled") is True
            )
            account = raw_integration.get("google_calendar_account")
            integration["google_calendar_account"] = (
                account if isinstance(account, str) and len(account) <= 320 else None
            )
        self.settings["integration"] = integration

        raw = self.settings.get("stats_state")
        if not isinstance(raw, dict):
            state = default_stats_state(current_date)
            legacy_today = self.settings.get("daily_record")
            if isinstance(legacy_today, dict) and legacy_today.get("date") == current_date:
                for key in COUNTER_KEYS:
                    value = _nonnegative_int(legacy_today.get(key))
                    state["today"][key] = value
                    state["current_month"][key] = value
                    state["current_year"][key] = value
            self.settings["stats_state"] = state
            self.settings.pop("statistics", None)
            self.settings.pop("daily_record", None)
            return

        state = default_stats_state(current_date)
        last_activity = raw.get("last_activity_date")
        try:
            date.fromisoformat(last_activity)
            state["last_activity_date"] = last_activity
        except (TypeError, ValueError):
            pass
        state["today"] = self._clean_today(raw.get("today"), current_date)
        state["current_month"] = self._clean_month(raw.get("current_month"), current_date)
        state["current_year"] = self._clean_year(raw.get("current_year"), current_date)
        seen = set()
        raw_reports = raw.get("pending_reports", [])
        if not isinstance(raw_reports, list):
            raw_reports = []
        for report in raw_reports[:MAX_PENDING_REPORTS]:
            clean = self._clean_report(report)
            if clean and clean["report_id"] not in seen:
                state["pending_reports"].append(clean)
                seen.add(clean["report_id"])
        self.settings["stats_state"] = state

    def _clean_today(self, raw, current_date):
        result = default_today(current_date)
        if isinstance(raw, dict):
            try:
                date.fromisoformat(raw.get("date"))
                result["date"] = raw["date"]
            except (TypeError, ValueError):
                pass
            for key in COUNTER_KEYS:
                result[key] = _nonnegative_int(raw.get(key))
        return result

    def _clean_month(self, raw, current_date):
        result = default_month(current_date)
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("year"), int)
            and not isinstance(raw.get("year"), bool)
            and 1 <= raw["year"] <= 9999
            and isinstance(raw.get("month"), int)
            and not isinstance(raw.get("month"), bool)
            and 1 <= raw["month"] <= 12
        ):
            result["year"] = raw["year"]
            result["month"] = raw["month"]
            for key in COUNTER_KEYS:
                result[key] = _nonnegative_int(raw.get(key))
        return result

    def _clean_year(self, raw, current_date):
        result = default_year(current_date)
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("year"), int)
            and not isinstance(raw.get("year"), bool)
            and 1 <= raw["year"] <= 9999
        ):
            result["year"] = raw["year"]
            for key in COUNTER_KEYS:
                result[key] = _nonnegative_int(raw.get(key))
        return result

    def _clean_report(self, raw):
        if not isinstance(raw, dict) or raw.get("report_type") not in (
            "daily",
            "monthly",
            "yearly",
        ):
            return None
        report_id = raw.get("report_id")
        period = raw.get("period")
        if (
            not isinstance(report_id, str)
            or not 1 <= len(report_id) <= 128
            or not isinstance(period, str)
            or not 1 <= len(period) <= 32
        ):
            return None
        try:
            if raw["report_type"] == "daily":
                date.fromisoformat(period)
            elif raw["report_type"] == "monthly":
                year_text, month_text = period.split("-")
                if len(year_text) != 4 or len(month_text) != 2:
                    return None
                year, month = int(year_text), int(month_text)
                if not 1 <= year <= 9999 or not 1 <= month <= 12:
                    return None
            else:
                year = int(period)
                if str(year) != period or not 1 <= year <= 9999:
                    return None
        except (TypeError, ValueError):
            return None
        if report_id != f"{raw['report_type']}-{period}":
            return None
        created_at = raw.get("created_at")
        if not isinstance(created_at, str) or len(created_at) > 64:
            created_at = ""
        return {
            "report_id": report_id,
            "report_type": raw["report_type"],
            "period": period,
            "created_at": created_at,
            **{key: _nonnegative_int(raw.get(key)) for key in COUNTER_KEYS},
            "status": "pending",
        }

    def rollover(self, current_date=None):
        current_date = current_date or today_text()
        state = self.settings["stats_state"]
        now = date.fromisoformat(current_date)
        last_activity = date.fromisoformat(state["last_activity_date"])
        if (now - last_activity).days >= 365:
            self.settings["stats_state"] = default_stats_state(current_date)
            self.long_inactivity_reset = True
            return True

        changed = False
        month = state["current_month"]
        year = state["current_year"]
        if state["today"]["date"] != current_date:
            self._enqueue_daily(state["today"], current_date)
            state["today"] = default_today(current_date)
            changed = True
        if (month["year"], month["month"]) != (now.year, now.month):
            self._enqueue_monthly(month, current_date)
            state["current_month"] = default_month(current_date)
            changed = True
        if year["year"] != now.year:
            self._enqueue_yearly(year, current_date)
            state["current_year"] = default_year(current_date)
            changed = True
        if state["last_activity_date"] != current_date:
            state["last_activity_date"] = current_date
            changed = True
        return changed

    def _enqueue_daily(self, values, current_date):
        self._enqueue_report("daily", values["date"], values, current_date)

    def _enqueue_monthly(self, values, current_date):
        period = f"{values['year']:04d}-{values['month']:02d}"
        self._enqueue_report("monthly", period, values, current_date)

    def _enqueue_yearly(self, values, current_date):
        self._enqueue_report("yearly", str(values["year"]), values, current_date)

    def _enqueue_report(self, report_type, period, values, current_date):
        state = self.settings["stats_state"]
        report_id = f"{report_type}-{period}"
        if any(item["report_id"] == report_id for item in state["pending_reports"]):
            return False
        report = {
            "report_id": report_id,
            "report_type": report_type,
            "period": period,
            "created_at": datetime.now().astimezone().isoformat(),
            **{key: values[key] for key in COUNTER_KEYS},
            "status": "pending",
        }
        state["pending_reports"].append(report)
        self._new_reports.append(dict(report))
        return True

    def enqueue_current_daily_report(self, current_date=None):
        """Queue today's report for an explicit manual calendar write, including zero counts."""
        current_date = current_date or today_text()
        self.rollover(current_date)
        state = self.settings["stats_state"]
        report_id = f"daily-{state['today']['date']}"
        for report in state["pending_reports"]:
            if report["report_id"] != report_id:
                continue
            changed = any(report.get(key, 0) != state["today"][key] for key in COUNTER_KEYS)
            for key in COUNTER_KEYS:
                report[key] = state["today"][key]
            report["status"] = "pending"
            return changed
        return self._enqueue_report(
            "daily", state["today"]["date"], state["today"], current_date
        )

    def take_new_reports(self):
        reports = self._new_reports
        self._new_reports = []
        return reports

    def record_completion(self, mode, current_date=None, cheat=False):
        self.rollover(current_date)
        if mode == "work":
            daily_key = "pomodoro_completed"
            cheat_key = "cheat_pomodoro_completed"
        elif mode == "break":
            daily_key = "short_break_completed"
            cheat_key = "cheat_short_break_completed"
        else:
            return False
        state = self.settings["stats_state"]
        target_key = cheat_key if cheat else daily_key
        state["today"][target_key] += 1
        state["current_month"][target_key] += 1
        state["current_year"][target_key] += 1
        state["last_activity_date"] = current_date or today_text()
        if cheat:
            return True
        return True

    def pending_count(self):
        return len(self.settings["stats_state"]["pending_reports"])

    def clear_pending(self):
        self.settings["stats_state"]["pending_reports"] = []


class GoogleCalendarClient:
    def __init__(self, token_path):
        self.token_path = Path(token_path)

    @property
    def available(self):
        return all(item is not None for item in (AuthorizedSession, Request, Credentials, InstalledAppFlow))

    def connect(self, client_secrets_path):
        if not self.available:
            raise RuntimeError("Googleカレンダー連携ライブラリが利用できません。")
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, [CALENDAR_SCOPE])
        credentials = flow.run_local_server(port=0, prompt="consent")
        self._save_credentials(credentials)
        return self._account_name(credentials)

    def disconnect(self):
        if self.token_path.exists():
            self.token_path.unlink()

    def has_credentials(self):
        if not self.available or not self.token_path.exists():
            return False
        try:
            credentials = Credentials.from_authorized_user_file(
                self.token_path, [CALENDAR_SCOPE]
            )
        except (OSError, ValueError, TypeError):
            return False
        return credentials.has_scopes([CALENDAR_SCOPE])

    def send_record(self, record):
        credentials = self._load_credentials()
        session = AuthorizedSession(credentials)
        if record["report_type"] == "daily":
            record_date = date.fromisoformat(record["period"])
            summary = "ポモドーロ実績"
        elif record["report_type"] == "monthly":
            year, month = (int(value) for value in record["period"].split("-"))
            day = calendar.monthrange(year, month)[1]
            record_date = date(year, month, day)
            summary = f"{year}年{month}月 実績"
        else:
            year = int(record["period"])
            record_date = date(year, 12, 31)
            summary = f"{year}年 年間実績"
        next_date = (record_date + timedelta(days=1)).isoformat()
        base_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        description_lines = [
            f"ポモドーロ完了数：{record['pomodoro_completed']}回",
            f"小休憩完了数：{record['short_break_completed']}回",
        ]
        if record.get("cheat_pomodoro_completed") or record.get(
            "cheat_short_break_completed"
        ):
            description_lines.extend(
                [
                    f"ポモドーロ完了数（ズル）：{record.get('cheat_pomodoro_completed', 0)}回",
                    f"小休憩完了数（ズル）：{record.get('cheat_short_break_completed', 0)}回",
                ]
            )
        body = {
            "summary": summary,
            "description": "\n".join(description_lines),
            "start": {"date": record_date.isoformat()},
            "end": {"date": next_date},
        }
        response = session.post(base_url, json=body, timeout=15)
        response.raise_for_status()
        self._save_credentials(credentials)
        return True

    def _load_credentials(self):
        if not self.available or not self.token_path.exists():
            raise RuntimeError("Googleカレンダーに接続されていません。")
        credentials = Credentials.from_authorized_user_file(self.token_path, [CALENDAR_SCOPE])
        if not credentials.has_scopes([CALENDAR_SCOPE]):
            raise RuntimeError("Googleカレンダーを再連携してください。")
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._save_credentials(credentials)
        if not credentials.valid:
            raise RuntimeError("Googleカレンダーの認証が無効です。再連携してください。")
        return credentials

    def _save_credentials(self, credentials):
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")

    @staticmethod
    def _account_name(credentials):
        id_token = getattr(credentials, "id_token", None)
        if isinstance(id_token, dict) and isinstance(id_token.get("email"), str):
            return id_token["email"]
        return "Googleアカウント"
