from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException


def install() -> None:
    import supabase_runtime as storage

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
            return {"ready": True, "created": False, "bucket": storage.BUCKET, "data": data}
        if not missing:
            raise HTTPException(
                502,
                f"Não foi possível consultar o bucket: HTTP {response.status_code}: {text[:240]}",
            )
        payload = {
            "id": storage.BUCKET,
            "name": storage.BUCKET,
            "public": False,
            "file_size_limit": storage.MAX_FILE_MB * 1024 * 1024,
        }
        created = storage._request("POST", "/bucket", payload)
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
        return {"ready": True, "created": not duplicate, "bucket": storage.BUCKET}

    storage.ensure_bucket = ensure_bucket
