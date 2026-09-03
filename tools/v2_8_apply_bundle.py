import base64
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTS = sorted((ROOT / "tools" / "v2_8_bundle_safe").glob("part-*.b64"))
if not PARTS:
    raise SystemExit("No safe V2-8 bundle parts found")
encoded = "".join(part.read_text(encoding="utf-8").strip() for part in PARTS)
payload = base64.b64decode(encoded, validate=True)
with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
    members = archive.getmembers()
    for member in members:
        target = (ROOT / member.name).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError as exc:
            raise SystemExit(f"Unsafe bundle path: {member.name}") from exc
    archive.extractall(ROOT, members=members, filter="data")
print(f"Applied V2-8 prepared bundle: {len(members)} entries from {len(PARTS)} safe parts")
