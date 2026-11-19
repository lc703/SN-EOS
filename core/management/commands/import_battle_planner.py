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
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Full sync (implies --refresh). Also delete imported rows that are no longer in the file, "
            "so this database mirrors the export. Rows created in SN EOS are kept. Users missing from the "
            "file are deactivated, not deleted.",
        )

    def handle(self, path, refresh=False, sync=False, **opts):
        file = Path(path)
        if not file.exists():
            raise CommandError(f"File not found: {file}")
        try:
            rows = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Not valid JSON: {exc}") from exc
        if not isinstance(rows, list):
            raise CommandError("Expected a dumpdata list of objects.")

        importer = BattlePlannerImporter(rows, refresh=refresh, sync=sync)
        stats = importer.run()

        self.stdout.write(self.style.MIGRATE_HEADING(f"Imported {len(rows)} rows from {file.name}"))
        width = max((len(k) for k in stats), default=10)
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
        if sync:
            self.stdout.write(self.style.MIGRATE_HEADING("Removed (no longer in the export):"))
            lines = importer.removed_lines()
            width = max([width, *(len(label) for label, _ in lines), len("Users deactivated")])
            if not lines and not importer.deactivated:
                self.stdout.write("  Nothing.")
            for label, n in lines:
                self.stdout.write(f"  {label.ljust(width)}  {n}")
            if importer.deactivated:
                self.stdout.write(f"  {'Users deactivated'.ljust(width)}  {importer.deactivated}")
        self.stdout.write(self.style.SUCCESS("Done."))
