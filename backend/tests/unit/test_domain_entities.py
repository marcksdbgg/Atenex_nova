"""Unit tests for domain entities."""
import pytest
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import (
    DocumentStatus, JobStatus, JobType, new_id,
)
from atenex_nova.shared.exceptions.base import InvalidStateTransitionError


class TestCollection:
    def test_create(self):
        c = Collection(id=new_id(), name="Test")
        assert c.name == "Test"

    def test_rename(self):
        c = Collection(id=new_id(), name="Old")
        c.rename("New")
        assert c.name == "New"

    def test_rename_empty_fails(self):
        c = Collection(id=new_id(), name="Test")
        with pytest.raises(ValueError):
            c.rename("   ")


class TestDocument:
    def _make_doc(self) -> Document:
        return Document(
            id=new_id(), collection_id=new_id(), title="test.pdf",
            source_path="/tmp/test.pdf", mime_type="application/pdf",
            checksum="abc123",
        )

    def test_initial_status(self):
        d = self._make_doc()
        assert d.status == DocumentStatus.REGISTERED

    def test_valid_transitions(self):
        d = self._make_doc()
        d.mark_parsed()
        assert d.status == DocumentStatus.PARSED
        d.mark_normalized()
        assert d.status == DocumentStatus.NORMALIZED
        d.mark_segmented()
        d.mark_embedded()
        d.mark_indexed()
        d.mark_ready()
        assert d.is_queryable

    def test_invalid_transition(self):
        d = self._make_doc()
        with pytest.raises(InvalidStateTransitionError):
            d.mark_ready()  # Can't go from registered to ready

    def test_fail(self):
        d = self._make_doc()
        d.fail("broken")
        assert d.status == DocumentStatus.FAILED
        assert d.error_message == "broken"


class TestJob:
    def test_lifecycle(self):
        j = Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=new_id())
        assert j.status == JobStatus.PENDING
        j.start()
        assert j.status == JobStatus.RUNNING
        j.succeed({"pages": 10})
        assert j.status == JobStatus.SUCCEEDED
        assert j.is_terminal

    def test_retry_logic(self):
        j = Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=new_id(), max_retries=2)
        j.start()
        j.fail("error 1")
        assert j.status == JobStatus.PENDING  # retried
        assert j.retries == 1
        j.start()
        j.fail("error 2")
        assert j.status == JobStatus.FAILED  # max retries reached
        assert not j.can_retry

    def test_cancel(self):
        j = Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=new_id())
        j.cancel()
        assert j.status == JobStatus.CANCELLED
        assert j.is_terminal
