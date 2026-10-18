"""Tests for links.canonicalize."""

import pytest

from src.links import canonicalize

LINKEDIN_CANONICAL = "https://www.linkedin.com/jobs/view/4012345678/"


@pytest.mark.parametrize("url", [
    # /comm/ link from an alert email, with every LinkedIn tracking param
    "https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=Ab12%2BCd%3D%3D"
    "&refId=xYz%3D%3D&lipi=urn%3Ali%3Apage%3Aemail&midToken=AQH-fake&midSig=0fakeSig"
    "&trk=eml-email_job_alert&trkEmail=eml-fake&eid=fake-eid&otpToken=fakeOtp",
    "https://www.linkedin.com/jobs/view/4012345678",
    "http://linkedin.com/jobs/view/4012345678/?trk=public_jobs#apply",
    "https://e.linkedin.com/comm/jobs/view/4012345678",
    "https://www.linkedin.com/jobs/view/product-manager-intern-at-acme-4012345678/?refId=x",
])
def test_linkedin_job_links_collapse_to_one_url(url):
    assert canonicalize(url) == LINKEDIN_CANONICAL


def test_linkedin_non_job_link_keeps_path_drops_tracking():
    url = "https://www.linkedin.com/comm/jobs/alerts?midToken=secret&trk=eml&view=all"
    assert canonicalize(url) == "https://www.linkedin.com/comm/jobs/alerts?view=all"


def test_non_linkedin_host_with_jobs_view_path_is_not_rewritten():
    url = "https://notlinkedin.com/jobs/view/123?utm_source=x"
    assert canonicalize(url) == "https://notlinkedin.com/jobs/view/123"


@pytest.mark.parametrize("url, expected", [
    ("https://jobright.ai/jobs/info/6a88?utm_campaign=1047&utm_source=git",
     "https://jobright.ai/jobs/info/6a88"),
    ("https://jobs.example.com/a?id=7&UTM_Medium=email&trk=x&page=2#section",
     "https://jobs.example.com/a?id=7&page=2"),  # other params kept, in order
    ("https://jobs.example.com/a?q=a%20b&TrackingID=zz",
     "https://jobs.example.com/a?q=a%20b"),  # kept params unchanged byte-for-byte
    ("https://simplify.jobs/p/abc?utm_source=Simplify&ref=Simplify",
     "https://simplify.jobs/p/abc?ref=Simplify"),
    ("https://jobs.example.com/plain", "https://jobs.example.com/plain"),
])
def test_tracking_params_and_fragments_stripped(url, expected):
    assert canonicalize(url) == expected


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/comm/jobs/view/4012345678/?trk=x",
    "https://jobs.example.com/a?id=7&utm_source=x#frag",
])
def test_idempotent(url):
    assert canonicalize(canonicalize(url)) == canonicalize(url)
