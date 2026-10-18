"""Tests for llm_extract with a fake llm and a fake Anthropic client (no API calls)."""

import json
from datetime import date

import anthropic
import httpx2
import pytest

from src.llm_extract import build_prompt, extract_roles
from src.llm_extract import call_claude as real_call_claude  # captured before conftest stubs it

EMAIL_DATE = date(2026, 10, 16)
EMAIL_TEXT = """\
Your job alert
Product Manager Intern (Summer 2027) (https://jobs.example.com/acme/1)
Acme Robotics, New York, NY
Growth Intern (https://jobs.example.com/globex/2)
Globex, Remote
Product Intern - Spring 2027 (https://jobs.example.com/initech/3)
Initech, Austin, TX
"""


def fake_llm(response):
    """Return an llm that records its prompts and replies with `response`."""
    def llm(prompt):
        llm.prompts.append(prompt)
        return response if isinstance(response, str) else json.dumps(response)
    llm.prompts = []
    return llm


def role(company="Acme Robotics", title="Product Manager Intern (Summer 2027)",
         location="New York, NY", link="https://jobs.example.com/acme/1"):
    return {"company": company, "title": title, "location": location, "link": link}


def run(response, text=EMAIL_TEXT):
    return extract_roles(text, "linkedin", EMAIL_DATE, fake_llm(response))


def test_valid_extraction():
    roles, errors = run({"roles": [
        role(),
        role("Globex", "Growth Intern", "Remote", "https://jobs.example.com/globex/2"),
    ]})
    assert errors == []
    acme, globex = roles
    assert acme.company == "Acme Robotics"
    assert acme.title == "Product Manager Intern (Summer 2027)"
    assert acme.location == "New York, NY"
    assert acme.link == "https://jobs.example.com/acme/1"
    assert acme.links == [acme.link]
    assert acme.sources == ["linkedin"]
    assert acme.date_posted == EMAIL_DATE  # alerts carry no post date
    assert acme.term == "Summer 2027"
    assert globex.term == "unknown"


def test_empty_roles_list_is_fine():
    assert run({"roles": []}) == ([], [])


def test_missing_title_is_error_and_others_kept():
    bad = role()
    del bad["title"]
    roles, errors = run({"roles": [bad, role("Globex", "Growth Intern", "Remote",
                                             "https://jobs.example.com/globex/2")]})
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


def test_bad_link_is_error():
    text = EMAIL_TEXT + "www.example.com/x javascript:alert(1)\n"
    roles, errors = run({"roles": [
        role(link="www.example.com/x"),
        role(link="javascript:alert(1)"),
    ]}, text=text)
    assert roles == []
    assert len(errors) == 2 and all("not http" in e for e in errors)


def test_link_not_in_email_is_error_and_others_kept():
    roles, errors = run({"roles": [
        role(link="https://jobs.example.com/acme/999"),  # hallucinated
        role("Globex", "Growth Intern", "Remote", "https://jobs.example.com/globex/2"),
    ]})
    assert [r.company for r in roles] == ["Globex"]
    assert len(errors) == 1 and "link not found in email" in errors[0]
    assert "acme/999" not in errors[0]  # links are not echoed into logs


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


def test_off_cycle_title_dropped_not_error():
    roles, errors = run({"roles": [role("Initech", "Product Intern - Spring 2027", "Austin, TX",
                                        "https://jobs.example.com/initech/3")]})
    assert roles == [] and errors == []


def test_prompt_wraps_email_and_asks_for_json():
    llm = fake_llm({"roles": []})
    extract_roles(EMAIL_TEXT, "linkedin", EMAIL_DATE, llm)
    [prompt] = llm.prompts
    assert f"<email>\n{EMAIL_TEXT}\n</email>" in prompt
    assert '{"roles": [' in prompt
    assert prompt == build_prompt(EMAIL_TEXT)


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
