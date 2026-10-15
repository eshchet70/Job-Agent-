"""Composition root for application services."""
from app.db import repository
from app.services import tracker_writer
from app.services.job_analysis import JobAnalysisService


def create_job_analysis_service() -> JobAnalysisService:
    """Build the job-analysis use case with the application's infrastructure."""
    return JobAnalysisService(repository=repository, tracker=tracker_writer)
