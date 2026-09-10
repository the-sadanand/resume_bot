"""
Pytest configuration and shared fixtures
"""
import os
import sys
import pytest
from pathlib import Path

# Ensure the project root is in the Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use test environment settings
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_resume_screening.db")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("DEBUG", "false")


@pytest.fixture(scope="session")
def sample_jd_text():
    """Sample job description text."""
    return """Senior Python Backend Engineer

    Requirements:
    - 5+ years of Python development experience
    - FastAPI, Django experience required
    - Docker, Kubernetes
    - PostgreSQL, Redis
    - AWS or GCP
    - REST APIs, Microservices
    - CI/CD (GitHub Actions)
    - pytest for testing

    Preferred:
    - Elasticsearch
    - GraphQL
    - Celery
    
    Education: Bachelor's in Computer Science or related field
    """


@pytest.fixture(scope="session")
def sample_resume_text_strong():
    """Strong match resume text."""
    return """Alex Chen
    alex.chen@example.com | +1-555-0101

    Professional Summary
    Senior Python Backend Engineer with 7 years experience.

    Skills
    Python, FastAPI, Django, PostgreSQL, Redis, Docker, Kubernetes, AWS, GCP,
    GitHub Actions, Celery, Elasticsearch, SQLAlchemy, pytest, Git, Linux

    Experience
    Senior Backend Engineer — CloudScale Technologies (2020–Present)
    5 years experience building FastAPI microservices
    Docker and Kubernetes deployment
    PostgreSQL optimization, Redis caching
    CI/CD with GitHub Actions

    Backend Engineer — DataStream (2018–2020)
    Django REST APIs, Celery, PostgreSQL

    Projects
    AutoScaler
    Technologies: Python, Kubernetes, Docker, AWS
    Open source Kubernetes autoscaling tool

    RealtimeDB Pipeline
    Technologies: Python, FastAPI, PostgreSQL, Redis

    Education
    Bachelor of Science in Computer Science — State University 2017

    Certifications
    AWS Certified Solutions Architect
    Certified Kubernetes Administrator
    """


@pytest.fixture(scope="session")
def sample_resume_text_moderate():
    """Moderate match resume text."""
    return """James Miller
    james.miller@example.com

    Profile
    Full-stack developer with JavaScript, Node.js background.
    Some Python experience.

    Skills
    JavaScript, TypeScript, Node.js, React, Python, Flask, MongoDB, Docker, Git

    Experience
    Full Stack Developer — DigitalEdge (2022–2023)
    Node.js REST APIs, React frontend, MongoDB

    Projects
    Task App
    Technologies: Python, Flask, PostgreSQL
    """
