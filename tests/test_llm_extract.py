"""Tests for llm_extract with a fake llm and a fake Anthropic client (no API calls)."""

import json
from datetime import date

import anthropic
import httpx2
import pytest

from src.llm_extract import build_prompt, extract_roles, number_links, strip_company_suffix
from src.llm_extract import call_claude as real_call_claude  # captured before conftest stubs it

EMAIL_DATE = date(2026, 10, 16)
ACME_RAW = "https://www.linkedin.com/comm/jobs/view/1111111111/?trackingId=abc%3D%3D&refId=x&trk=eml"
EMAIL_TEXT = f"""\
Your job alert
Product Manager Intern (Summer 2027) ({ACME_RAW})
Acme Robotics, New York, NY
Growth Intern (https://jobs.example.com/globex/2?utm_source=alert)
Globex, Remote
Product Intern - Spring 2027 (https://jobs.example.com/initech/3)
Initech, Austin, TX
Manage alerts (https://www.linkedin.com/comm/jobs/alerts?midToken=secret).
"""


def fake_llm(response):
    """Return an llm that records its prompts and replies with `response`."""
    def llm(prompt):
        llm.prompts.append(prompt)
        return response if isinstance(response, str) else json.dumps(response)
    llm.prompts = []
    return llm


def role(company="Acme Robotics", title="Product Manager Intern (Summer 2027)",
         location="New York, NY", link_id="L1"):
    return {"company": company, "title": title, "location": location, "link_id": link_id}


GLOBEX = role("Globex", "Growth Intern", "Remote", "L2")


def run(response, text=EMAIL_TEXT):
    """Return (roles, errors); title fixes are tested separately."""
    roles, errors, _ = extract_roles(text, "linkedin", EMAIL_DATE, fake_llm(response))
    return roles, errors


# --- number_links -------------------------------------------------------------

def test_number_links_in_order_with_markers():
    marked, links = number_links(EMAIL_TEXT)
    assert links == {
        "L1": ACME_RAW,
        "L2": "https://jobs.example.com/globex/2?utm_source=alert",
        "L3": "https://jobs.example.com/initech/3",
        "L4": "https://www.linkedin.com/comm/jobs/alerts?midToken=secret",  # trailing "." trimmed
    }
    assert "Product Manager Intern (Summer 2027) ([L1])" in marked
    assert "Manage alerts ([L4])." in marked
    assert "http" not in marked


def test_number_links_reuses_id_for_repeated_url():
    marked, links = number_links("a https://x.example.com/1 b https://x.example.com/1, c")
    assert links == {"L1": "https://x.example.com/1"}
    assert marked == "a [L1] b [L1], c"


def test_number_links_no_links():
    assert number_links("no links here") == ("no links here", {})


def test_prompt_has_numbered_canonical_links_and_marked_email():
    llm = fake_llm({"roles": []})
    extract_roles(EMAIL_TEXT, "linkedin", EMAIL_DATE, llm)
    [prompt] = llm.prompts
    assert "L1: https://www.linkedin.com/jobs/view/1111111111/" in prompt
    assert "L2: https://jobs.example.com/globex/2\n" in prompt
    assert "Product Manager Intern (Summer 2027) ([L1])" in prompt
    # No raw tracking tokens are sent to the API.
    for token in ("trackingId", "refId", "trk=", "midToken", "utm_source"):
        assert token not in prompt
    assert '"link_id": "L1"' in prompt
    assert prompt == build_prompt(*number_links(EMAIL_TEXT))


# --- extract_roles --------------------------------------------------------------

def test_valid_link_ids_map_to_canonical_links():
    roles, errors = run({"roles": [role(), GLOBEX]})
    assert errors == []
    acme, globex = roles
    assert acme.company == "Acme Robotics"
    assert acme.title == "Product Manager Intern (Summer 2027)"
    assert acme.location == "New York, NY"
    assert acme.link == "https://www.linkedin.com/jobs/view/1111111111/"
    assert acme.links == [acme.link]
    assert acme.sources == ["linkedin"]
    assert acme.date_posted == EMAIL_DATE  # alerts carry no post date
    assert acme.term == "Summer 2027"
    assert globex.link == "https://jobs.example.com/globex/2"
    assert globex.term == "unknown"


def test_link_id_tolerates_case_and_spaces():
    roles, errors = run({"roles": [role(link_id=" l1 ")]})
    assert errors == [] and roles[0].link == "https://www.linkedin.com/jobs/view/1111111111/"


def test_unknown_link_id_is_error_and_others_kept():
    roles, errors = run({"roles": [role(link_id="L99"), GLOBEX]})
    assert [r.company for r in roles] == ["Globex"]
    assert errors == ["role #0 (Product Manager Intern (Summer 2027)): unknown link_id 'L99'"]


def test_url_instead_of_link_id_is_error():
    roles, errors = run({"roles": [role(link_id="https://jobs.example.com/made-up")]})
    assert roles == [] and len(errors) == 1 and "unknown link_id" in errors[0]
    assert "made-up" not in errors[0]  # only a short prefix is echoed


def test_missing_link_id_is_error():
    bad = role()
    del bad["link_id"]
    roles, errors = run({"roles": [bad]})
    assert roles == [] and len(errors) == 1 and "missing link_id" in errors[0]


def test_empty_roles_list_is_fine():
    assert run({"roles": []}) == ([], [])


def test_missing_title_is_error_and_others_kept():
    bad = role()
    del bad["title"]
    roles, errors = run({"roles": [bad, GLOBEX]})
    assert [r.company for r in roles] == ["Globex"]
    assert len(errors) == 1 and "missing title" in errors[0]


def test_blank_company_is_error():
    _, errors = run({"roles": [role(company="  ")]})
    assert len(errors) == 1 and "missing company" in errors[0]


def test_missing_location_key_is_error_but_empty_location_ok():
    no_loc = role()
    del no_loc["location"]
    roles, errors = run({"roles": [no_loc, role(location="")]})
    assert len(roles) == 1 and roles[0].location == ""
    assert len(errors) == 1 and "missing location" in errors[0]


def test_non_json_response_is_one_error():
    roles, errors = run("Sure! Here are the roles: Acme, Globex.")
    assert roles == []
    assert len(errors) == 1 and "not JSON" in errors[0]


def test_json_without_roles_list_is_error():
    for response in ({"jobs": []}, {"roles": "none"}, [role()]):
        roles, errors = run(response)
        assert roles == [] and len(errors) == 1 and '"roles"' in errors[0]


def test_non_object_item_is_error():
    _, errors = run({"roles": ["Acme PM intern"]})
    assert len(errors) == 1 and "not an object" in errors[0]


def test_fenced_json_is_accepted():
    roles, errors = run("```json\n" + json.dumps({"roles": [role()]}) + "\n```")
    assert errors == [] and len(roles) == 1


def test_off_cycle_title_kept_for_the_term_layer():
    # The pipeline's term layer drops it, so the drop is counted.
    roles, errors = run({"roles": [role("Initech", "Product Intern - Spring 2027", "Austin, TX", "L3")]})
    assert errors == [] and roles[0].term == "unknown"


# --- call_claude, with a fake Anthropic client (no network) ------------------

def bad_request(message):
    request = httpx2.Request("POST", "https://api.example.com/v1/messages")
    return anthropic.BadRequestError(
        message, response=httpx2.Response(400, request=request), body=None)


class FakeBlock:
    def __init__(self, text):
        self.type, self.text = "text", text


class FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content, self.stop_reason = [FakeBlock(text)], stop_reason


def fake_client(behavior):
    """Patchable stand-in for anthropic.Anthropic; `behavior(kwargs)` returns or raises."""
    class Client:
        calls = []

        def __init__(self, *args, **kwargs):
            self.messages = self

        def create(self, **kwargs):
            Client.calls.append(kwargs)
            return behavior(kwargs)
    return Client


def test_call_claude_sends_model_prompt_and_effort(monkeypatch):
    client = fake_client(lambda kw: FakeResponse('{"roles": []}'))
    monkeypatch.setattr(anthropic, "Anthropic", client)
    assert real_call_claude("hello") == '{"roles": []}'
    [kwargs] = client.calls
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["messages"] == [{"role": "user", "content": "hello"}]
    assert kwargs["output_config"] == {"effort": "low"}


def test_call_claude_drops_effort_if_rejected(monkeypatch):
    def behavior(kw):
        if "output_config" in kw:
            raise bad_request("output_config.effort: not supported for this model")
        return FakeResponse("ok")
    client = fake_client(behavior)
    monkeypatch.setattr(anthropic, "Anthropic", client)
    assert real_call_claude("hello") == "ok"
    assert len(client.calls) == 2 and "output_config" not in client.calls[1]


def test_call_claude_other_bad_requests_raise(monkeypatch):
    def behavior(kw):
        raise bad_request("messages: too long")
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(behavior))
    with pytest.raises(anthropic.BadRequestError):
        real_call_claude("hello")


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_call_claude_early_stop_raises(monkeypatch, stop_reason):
    client = fake_client(lambda kw: FakeResponse('{"roles": [', stop_reason))
    monkeypatch.setattr(anthropic, "Anthropic", client)
    with pytest.raises(RuntimeError, match=stop_reason):
        real_call_claude("hello")


# --- company-suffix guard -----------------------------------------------------


@pytest.mark.parametrize("title, company, expected", [
    ("2027 Summer Internship - Product Operations Q2", "Q2", "2027 Summer Internship - Product Operations"),
    ("Product Manager Intern - Acme", "Acme", "Product Manager Intern"),
    ("Product Manager Intern · ACME", "Acme", "Product Manager Intern"),
    ("Product Manager Intern, Acme Robotics", "Acme Robotics", "Product Manager Intern"),
    ("Product Manager Intern", "Acme", "Product Manager Intern"),  # nothing to strip
    ("Acme", "Acme", "Acme"),  # nothing would be left
    ("Product Intern - Acmeville", "Acme", "Product Intern - Acmeville"),  # whole name only
    ("Growth Intern", "", "Growth Intern"),
])
def test_strip_company_suffix(title, company, expected):
    assert strip_company_suffix(title, company) == expected


def test_extract_roles_reports_title_fixes():
    response = {"roles": [role(title="Product Manager Intern (Summer 2027) - Acme Robotics"), GLOBEX]}
    roles, errors, fixes = extract_roles(EMAIL_TEXT, "linkedin", EMAIL_DATE, fake_llm(response))
    assert errors == [] and roles[0].title == "Product Manager Intern (Summer 2027)"
    assert fixes == [("Product Manager Intern (Summer 2027) - Acme Robotics",
                      "Product Manager Intern (Summer 2027)")]
