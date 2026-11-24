from django.core.management.base import BaseCommand

from core import asana_client


class Command(BaseCommand):
    help = (
        "Pull completions back from Asana (a to-do is checked off when its task is done) and assign tasks "
        "that went out before their owner was in Asana. Runs on its own from the To-Dos page at most every "
        "10 minutes; a Railway cron can call this too. Does nothing unless ASANA_PAT is set."
    )

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Look at every task in the project, not just recent changes.")

    def handle(self, all=False, **opts):
        if not asana_client.is_configured():
            self.stdout.write("Asana is not connected (no ASANA_PAT). Nothing to do.")
            return
        from django.utils import timezone

        from core.models import AppSetting

        since = None if all else (AppSetting.get("asana_last_sync") or None)
        started = timezone.now().isoformat()
        try:
            done = asana_client.sync_completed(since)
            fixed = asana_client.fix_unassigned()
        except asana_client.AsanaError as exc:
            self.stderr.write(f"Asana sync failed: {exc}")
            return
        AppSetting.put("asana_last_sync", started)
        self.stdout.write(f"Asana: {done} to-do(s) completed in Asana, {fixed} task(s) assigned.")
