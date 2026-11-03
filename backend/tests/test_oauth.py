from app.connectors.oauth import OAuthStore, authorization_url


def test_oauth_state_is_provider_bound_and_single_use(tmp_path):
    store = OAuthStore(tmp_path / "oauth.sqlite3")
    state = store.new_state("jira")
    assert store.consume_state(state, "notion") is False
    assert store.consume_state(state, "jira") is True
    assert store.consume_state(state, "jira") is False


def test_authorization_urls_include_callback_and_state():
    jira = authorization_url("jira", "secure-state", "client", "http://localhost/callback", ["read:jira-work"])
    assert "auth.atlassian.com/authorize?" in jira
    assert "state=secure-state" in jira and "redirect_uri=http%3A%2F%2Flocalhost%2Fcallback" in jira
    notion = authorization_url("notion", "another-state", "client", "http://localhost/callback", [])
    assert "api.notion.com/v1/oauth/authorize?" in notion
    assert "state=another-state" in notion
    gmail = authorization_url("gmail", "google-state", "client", "http://localhost/callback",
                              ["https://www.googleapis.com/auth/gmail.readonly"])
    assert "accounts.google.com/o/oauth2/v2/auth?" in gmail
    assert "access_type=offline" in gmail and "prompt=consent" in gmail
    assert "gmail.readonly" in gmail


def test_tokens_persist_and_disconnect(tmp_path):
    store = OAuthStore(tmp_path / "oauth.sqlite3")
    store.save("jira", {"access_token": "example", "refresh_token": "refresh"})
    assert store.status() == {"jira": True, "notion": False, "gmail": False}
    assert store.get("jira")["access_token"] == "example"
    store.delete("jira")
    assert store.status()["jira"] is False
