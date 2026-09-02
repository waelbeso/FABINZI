from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError

from apps.design.golden_reference import seed_fabinzi_reference_demo
from apps.design.reference_v2_4 import enrich_source_supported_reference_mapping


class Command(BaseCommand):
    help = "Seed the immutable FABINZI Golden reference/demo topology from directly verified packages or an explicit non-production contract fixture."

    def add_arguments(self, parser):
        parser.add_argument("--package-source", help="Outer Golden transport ZIP or directory containing the five canonical frozen inner ZIPs.")
        parser.add_argument(
            "--contract-fixture",
            action="store_true",
            help="Use source-supported contract metadata for controlled schema/QA only. This is NOT direct Golden package binary verification.",
        )

    def handle(self, *args, **options):
        try:
            result = seed_fabinzi_reference_demo(
                source_path=options.get("package_source"),
                contract_fixture=options.get("contract_fixture", False),
            )
            mapping = enrich_source_supported_reference_mapping()
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc

        evidence = "DIRECT BINARY VERIFIED SOURCE" if result["direct_binary_evidence"] else "CONTRACT FIXTURE / NOT BINARY PROOF"
        self.stdout.write(self.style.SUCCESS(f"FABINZI Golden reference demo seeded idempotently: {evidence}"))
        self.stdout.write(f"Dataset ID: {result['dataset_id']}")
        self.stdout.write(f"Products: {', '.join(sorted(result['products']))}")
        self.stdout.write(f"Creator schema mappings: {', '.join(mapping['version_refs'])}")
        self.stdout.write("Reference records remain DEMO / TRAINING REFERENCE / NOT FOR PRODUCTION.")
        if not result["direct_binary_evidence"]:
            self.stdout.write(self.style.WARNING("GOLDEN PACKAGE BYTES = NOT VERIFIED by contract-fixture mode."))
