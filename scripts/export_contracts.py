"""Write the machine-readable API contract for the api-contracts repo.

    python scripts/export_contracts.py [--out ../api-contracts]

Produces openapi/openapi.json (generated from the running app's routes and models) and errors/errors.yaml.
The backend is the source of the OpenAPI document; the mobile app and web admin generate/verify against it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET", "contract-export-only-secret-0123456789abcdef")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / "api-contracts"))
    out = Path(ap.parse_args().out)

    import yaml

    from app.errors import ERROR_CODES
    from app.main import create_app

    spec = create_app().openapi()
    (out / "openapi").mkdir(parents=True, exist_ok=True)
    (out / "openapi" / "openapi.json").write_text(
        json.dumps(spec, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "errors").mkdir(parents=True, exist_ok=True)
    (out / "errors" / "errors.yaml").write_text(
        '# Machine-readable error codes. Response body: {"error": {"code", "message", "request_id"}}\n'
        + yaml.safe_dump({"codes": ERROR_CODES}, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    print(
        f"wrote {out / 'openapi' / 'openapi.json'} ({len(spec['paths'])} paths) and errors.yaml ({len(ERROR_CODES)} codes)"
    )


if __name__ == "__main__":
    main()
