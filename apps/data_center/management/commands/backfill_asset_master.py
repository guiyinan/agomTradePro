from django.core.management.base import BaseCommand

from apps.data_center.infrastructure.asset_master_backfill import (
    AssetMasterBackfillService,
)


class Command(BaseCommand):
    help = "Backfill data center asset master rows from legacy sources."

    def add_arguments(self, parser):
        parser.add_argument(
            "--codes",
            nargs="*",
            default=[],
            help="Optional canonical or legacy asset codes to backfill.",
        )
        parser.add_argument(
            "--include-remote",
            action="store_true",
            help="Fetch missing names from EastMoney after exhausting local legacy sources.",
        )

    def handle(self, *args, **options):
        service = AssetMasterBackfillService()
        codes = options["codes"] or []
        if codes:
            report = service.backfill_codes(codes, include_remote=options["include_remote"])
        else:
            report = service.backfill_all(include_remote=options["include_remote"])

        self.stdout.write(self.style.SUCCESS("Asset master backfill completed"))
        self.stdout.write(str(report.to_dict()))
