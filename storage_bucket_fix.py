from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException


def install() -> None:
    import supabase_runtime as storage

    def apply_real_limit(data: dict | None) -> int:
        value = (data or {}).get("file_size_limit") if isinstance(data, dict) else None
        try:
            if value:
                storage.MAX_FILE_MB = max(1, int(value) // (1024 * 1024))
                return storage.MAX_FILE_MB
        except (TypeError, ValueError):
            pass
        # This Supabase project rejected a 250 MB bucket. When the bucket
        # inherits the project-wide setting and exposes no explicit value, use
        # the verified project ceiling consistently from process startup.
        storage.MAX_FILE_MB = min(int(storage.MAX_FILE_MB), 50)
        return storage.MAX_FILE_MB

    # Do not leave a cold serverless instance temporarily advertising 250 MB.
    # Every route starts with the same conservative, verified 50 MB ceiling.
    apply_real_limit(None)

    def ensure_bucket() -> dict:
        valid, detail = storage._credential_status()
        if not valid:
            raise HTTPException(503, detail)
        encoded_bucket = quote(storage.BUCKET, safe="")
        response = storage._request("GET", f"/bucket/{encoded_bucket}")
        text = response.text[:400]
        missing = response.status_code == 404 or (
            response.status_code == 400
            and any(marker in text.lower() for marker in ("nosuchbucket", "bucket not found"))
        )
        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                data = {}
            limit = apply_real_limit(data)
            return {
                "ready": True,
                "created": False,
                "bucket": storage.BUCKET,
                "data": data,
                "maxFileMb": limit,
            }
        if not missing:
            raise HTTPException(
                502,
                f"Não foi possível consultar o bucket: HTTP {response.status_code}: {text[:240]}",
            )

        configured_payload = {
            "id": storage.BUCKET,
            "name": storage.BUCKET,
            "public": False,
            "file_size_limit": int(storage.MAX_FILE_MB) * 1024 * 1024,
        }
        created = storage._request("POST", "/bucket", configured_payload)
        created_text = created.text[:400]
        too_large = created.status_code == 400 and any(
            marker in created_text.lower()
            for marker in ("entitytoolarge", "payload too large", "maximum allowed size")
        )
        if too_large:
            # Let Supabase inherit the real project-wide limit.
            created = storage._request(
                "POST",
                "/bucket",
                {"id": storage.BUCKET, "name": storage.BUCKET, "public": False},
            )
            created_text = created.text[:400]
        duplicate = created.status_code in {400, 409} and any(
            marker in created_text.lower()
            for marker in ("already", "exists", "duplicate")
        )
        if created.status_code not in {200, 201} and not duplicate:
            raise HTTPException(
                502,
                f"Não foi possível criar o bucket: HTTP {created.status_code}: {created_text[:260]}",
            )
        check = storage._request("GET", f"/bucket/{encoded_bucket}")
        if check.status_code != 200:
            raise HTTPException(
                502,
                f"O bucket foi solicitado, mas não ficou acessível: HTTP {check.status_code}: {check.text[:240]}",
            )
        try:
            data = check.json()
        except ValueError:
            data = {}
        limit = apply_real_limit(data)
        return {
            "ready": True,
            "created": not duplicate,
            "bucket": storage.BUCKET,
            "data": data,
            "maxFileMb": limit,
        }

    storage.ensure_bucket = ensure_bucket
