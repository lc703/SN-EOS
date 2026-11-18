import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.importer import BattlePlannerImporter


class Command(BaseCommand):
    help = "Import a Battle Planner dumpdata JSON export. Safe to run more than once."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the export .json file")
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Overwrite previously imported rows with values from the file (default: leave app edits alone).",
        )

    def handle(self, path, refresh=False, **opts):
        file = Path(path)
        if not file.exists():
            raise CommandError(f"File not found: {file}")
        try:
            rows = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Not valid JSON: {exc}") from exc
        if not isinstance(rows, list):
            raise CommandError("Expected a dumpdata list of objects.")

        importer = BattlePlannerImporter(rows, refresh=refresh)
        stats = importer.run()

        self.stdout.write(self.style.MIGRATE_HEADING(f"Imported {len(rows)} rows from {file.name}"))
        width = max(len(k) for k in stats) if stats else 10
        mapped = {k: v for k, v in stats.items() if "archived" not in v}
        archived = {k: v for k, v in stats.items() if "archived" in v}
        for label, counts in mapped.items():
            parts = ", ".join(f"{n} {kind}" for kind, n in counts.items())
            self.stdout.write(f"  {label.ljust(width)}  {parts}")
        if archived:
            self.stdout.write(self.style.MIGRATE_HEADING("Not mapped (kept raw in LegacyRecord / legacy fields):"))
            for label, counts in archived.items():
                self.stdout.write(f"  {label.ljust(width)}  {counts['archived']}")
        if importer.notes:
            self.stdout.write(self.style.MIGRATE_HEADING("Notes:"))
            for note in importer.notes:
                self.stdout.write(f"  - {note}")
        self.stdout.write(self.style.SUCCESS("Done."))
