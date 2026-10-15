from app.services.job_analysis import JobAnalysisService


JOB_DESCRIPTION = (
    "Senior Technical Program Manager. Lead cross-functional programs, portfolio "
    "governance, Agile delivery, stakeholder management, roadmap and risk management."
)


class FakeRepository:
    def __init__(self):
        self.saved = []

    def find_duplicate_job(self, company, title):
        return None

    def get_brief_for_job(self, job_id):
        return None

    def get_job(self, job_id):
        return None

    def save_brief(self, brief):
        self.saved.append(brief)
        return 42

    def save_person(self, job_id, person):
        return 1

    def save_outreach(self, record):
        return 1


class FakeTracker:
    def __init__(self):
        self.written = []

    def write_brief_to_tracker(self, brief):
        self.written.append(brief)


def test_analyze_returns_brief_without_persistence_or_tracker_writes():
    service = JobAnalysisService(
        resume_loader=lambda: "Technical program management and Agile delivery",
        evidence_loader=lambda: [],
    )

    brief = service.analyze(
        company="Example Corp",
        title="Senior Technical Program Manager",
        description=JOB_DESCRIPTION,
    )

    assert brief.job.id is None
    assert brief.fit is not None
    assert brief.ats is not None


def test_execute_uses_injected_repository_and_tracker():
    repository = FakeRepository()
    tracker = FakeTracker()
    service = JobAnalysisService(
        repository=repository,
        tracker=tracker,
        resume_loader=lambda: "Technical program management and Agile delivery",
        evidence_loader=lambda: [],
    )

    brief = service.execute(
        company="Example Corp",
        title="Senior Technical Program Manager",
        description=JOB_DESCRIPTION,
        write_to_excel=True,
    )

    assert brief.job.id == 42
    assert repository.saved == [brief]
    assert tracker.written == [brief]
