from api.core.config import settings

if settings.storage_backend == "local":
    from api.core.local_blob_store import (  # noqa: F401
        check_blob_store,
        complete_multipart_upload,
        create_multipart_upload,
        download_bytes,
        ensure_bucket,
        upload_part,
    )
else:
    import aioboto3
    from botocore.config import Config

    def _client_config() -> Config:
        return Config(signature_version="s3v4", s3={"addressing_style": "path"})

    async def get_s3_client():
        session = aioboto3.Session()
        return session.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name=settings.minio_region,
            config=_client_config(),
        )

    async def ensure_bucket() -> None:
        async with await get_s3_client() as s3:
            try:
                await s3.head_bucket(Bucket=settings.minio_bucket)
            except Exception:
                await s3.create_bucket(Bucket=settings.minio_bucket)

    async def upload_part(key: str, upload_id: str, part_number: int, data: bytes) -> str:
        async with await get_s3_client() as s3:
            response = await s3.upload_part(
                Bucket=settings.minio_bucket,
                Key=key,
                UploadId=upload_id,
                PartNumber=part_number,
                Body=data,
            )
            return response["ETag"]

    async def create_multipart_upload(key: str, content_type: str) -> str:
        async with await get_s3_client() as s3:
            response = await s3.create_multipart_upload(
                Bucket=settings.minio_bucket,
                Key=key,
                ContentType=content_type,
            )
            return response["UploadId"]

    async def complete_multipart_upload(
        key: str, upload_id: str, parts: list[dict[str, str | int]]
    ) -> None:
        async with await get_s3_client() as s3:
            await s3.complete_multipart_upload(
                Bucket=settings.minio_bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )

    async def download_bytes(key: str) -> bytes:
        async with await get_s3_client() as s3:
            response = await s3.get_object(Bucket=settings.minio_bucket, Key=key)
            return await response["Body"].read()

    async def check_blob_store() -> bool:
        try:
            await ensure_bucket()
            return True
        except Exception:
            return False
