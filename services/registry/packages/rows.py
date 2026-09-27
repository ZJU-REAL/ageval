"""Package release, draft, and dataset ACL rows."""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ReleaseRow:
    dataset_id: str
    version: str
    visibility: str
    package_digest: str
    blob_digest: str
    size: int
    media_type: str
    created_at: float
    org_id: str | None = None
    uploaded_by: str = ""

@dataclass(frozen=True, slots=True)
class DraftRow:
    """One current draft slot per dataset (not a release)."""

    dataset_id: str
    org_id: str
    visibility: str
    package_digest: str
    blob_digest: str
    size: int
    media_type: str
    package_kind: str
    uploaded_by: str
    updated_at: float

    def as_release(self) -> ReleaseRow:
        return ReleaseRow(
            dataset_id=self.dataset_id,
            version="draft",
            visibility=self.visibility,
            package_digest=self.package_digest,
            blob_digest=self.blob_digest,
            size=self.size,
            media_type=self.media_type,
            created_at=self.updated_at,
            org_id=self.org_id,
            uploaded_by=self.uploaded_by,
        )

@dataclass(frozen=True, slots=True)
class DatasetAclRow:
    dataset_id: str
    user_id: str
    role: str
    created_at: float
