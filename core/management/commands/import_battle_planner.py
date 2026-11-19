import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.importer import BattlePlannerImporter
from scorecard.values_csv import load_values_csv


class Command(BaseCommand):
    help = "Import a Battle Planner dumpdata JSON export. Safe to run more than once."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="Path to the export .json file (optional with --values-csv)")
        parser.add_argument(
            "--values-csv",
            metavar="FILE",
            help="Also load weekly Scorecard values from a CSV with columns metric, facility, week_start, value. "
            "Each row is an upsert, so re-running is safe. Works on its own, without an export path.",
        )
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

    def handle(self, path=None, refresh=False, sync=False, values_csv=None, **opts):
        if not path and not values_csv:
            raise CommandError("Give the export path, --values-csv FILE, or both.")
        if path:
            self.import_export(path, refresh, sync)
        if values_csv:
            self.import_values_csv(values_csv)
        self.stdout.write(self.style.SUCCESS("Done."))

    def import_values_csv(self, path):
        file = Path(path)
        if not file.exists():
            raise CommandError(f"File not found: {file}")
        try:
            result = load_values_csv(file.read_text(encoding="utf-8-sig"))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.MIGRATE_HEADING(f"Scorecard values from {file.name}"))
        counts = result.counts
        self.stdout.write(
            "  " + ", ".join(f"{counts[k]} {k}" for k in ("created", "updated", "unchanged", "skipped"))
        )
        if result.notes:
            self.stdout.write(self.style.MIGRATE_HEADING("Notes:"))
            for note in result.notes:
                self.stdout.write(f"  - {note}")

    def import_export(self, path, refresh, sync):
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
